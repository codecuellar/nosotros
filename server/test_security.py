"""Isolated real SQLite and HTTP regressions; no project/private state is opened."""
import base64
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
import zlib

import app


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    raw = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
    raw += chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00')) + chunk(b'IEND', b'')
    return raw


def image():
    return 'data:image/png;base64,' + base64.b64encode(png()).decode()


def change(key='a', updated=100, deleted=None, kind='events', payload=None):
    return {'kind': kind, 'id': key, 'payload': {'title': 'test'} if payload is None else payload,
            'updated_at': updated, 'deleted_at': deleted}


class StoreSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = app.Store(self.root / 'data', self.root / 'uploads', self.root / 'backups')

    def tearDown(self):
        self.temp.cleanup()

    def test_lww_tombstones_and_deterministic_tie(self):
        self.store.sync(0, [change(updated=200)])
        self.assertFalse(self.store.sync(0, [change(updated=100)])['accepted'])
        self.store.sync(0, [change(updated=200, deleted=200)])
        self.assertFalse(self.store.sync(0, [change(updated=200)])['accepted'])
        self.assertEqual(self.store.sync()['changes'][0]['deleted_at'], 200)
        self.store.sync(0, [change(updated=201)])
        self.assertIsNone(self.store.sync()['changes'][0]['deleted_at'])
        self.assertEqual(self.store.sync()['cursor'], 3)

    def test_batch_validation_atomic(self):
        with self.assertRaises(app.APIError):
            self.store.sync(0, [change(), change(key='../private')])
        self.assertEqual(self.store.sync()['cursor'], 0)
        for bad in (True, -1, '0'):
            with self.assertRaises(app.APIError):
                self.store.sync(bad, [])
        with self.assertRaises(app.APIError):
            self.store.sync(0, [change()] * 2001)
        with self.assertRaises(app.APIError) as raised:
            self.store.sync(99, [change()])
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.store.sync()['changes'], [])

    def test_invalid_kind_and_null_changes_rejected(self):
        for kind in ([], {}, None, 1):
            with self.assertRaises(app.APIError):
                self.store.sync(0, [change(kind=kind)])
        self.assertEqual(self.store.sync()['cursor'], 0)
        self.assertEqual(self.store.sync()['changes'], [])

    def test_session_expiry(self):
        self.store.create_user('expiry', 'test-expiry-password')
        token, _ = self.store.login('expiry', 'test-expiry-password', 'ip')
        with self.store.connection() as db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertIsNone(self.store.session(token))

    def test_all_kinds_and_missing_blob_metadata(self):
        changes = [change(kind=k, key='main' if k in ('settings', 'collages') else '2026-01-01', payload=p)
                   for k, p in [('events', {}), ('ideas', {}), ('photos', {'url': '/uploads/missing'}),
                                ('days', {'meet': True, 'note': ''}), ('notes', {'text': 'x'}),
                                ('settings', {'theme': 'auto'}),
                                ('collages', {'template': 0, 'caption': '', 'slots': {}})]]
        result = self.store.sync(0, changes)
        self.assertEqual(len(result['changes']), 7)
        self.assertEqual(len(result['accepted']), 7)
        self.assertEqual(len(self.store.sync(4)['changes']), 3)

    def test_auth_limit_durable_lockout_and_logout(self):
        self.store.create_user(' First ', 'a-strong-password')
        self.store.create_user('second', 'another-password')
        with self.assertRaises(app.APIError):
            self.store.create_user('third', 'another-password')
        for _ in range(5):
            with self.assertRaises(app.APIError) as raised:
                self.store.login('FIRST', 'incorrect-password', '127.0.0.1')
            self.assertEqual(raised.exception.status, 401)
            self.store = app.Store(self.store.data, self.store.uploads, self.store.backups)
        with self.assertRaises(app.APIError) as raised:
            self.store.login('first', 'a-strong-password', '127.0.0.1')
        self.assertEqual(raised.exception.status, 429)
        token, username = self.store.login('first', 'a-strong-password', 'other-ip')
        self.assertEqual(self.store.session(token), username)
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM sessions').fetchone()
            self.assertNotEqual(row['token_hash'], token)
            self.assertNotIn('a-strong-password', str(db.execute('SELECT * FROM users').fetchall()))
        self.store.logout(token)
        self.assertIsNone(self.store.session(token))
        token, _ = self.store.login('second', 'another-password', 'ip')
        self.store.revoke_sessions('second')
        self.assertIsNone(self.store.session(token))

    def test_photo_validation_idempotency_and_protection(self):
        self.assertEqual(self.store.upload('pic', image())['url'], '/uploads/pic')
        self.store.upload('pic', image())
        raw, mime = self.store.blob('pic')
        self.assertEqual(raw, png())
        self.assertEqual(mime, 'image/png')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM blobs').fetchone()[0], 1)
        for invalid in ('data:image/jpeg;base64,' + base64.b64encode(png()).decode(),
                        'data:image/png;base64,YmFk', image()[:-8], 'data:image/webp;base64,YmFk'):
            with self.assertRaises(app.APIError):
                self.store.upload('bad', invalid)
        with self.assertRaises(app.APIError):
            self.store.upload('../escape', image())
        with self.assertRaises(app.APIError) as raised:
            self.store.upload('huge', 'x' * (app.MAX_ENCODED + 33))
        self.assertEqual(raised.exception.status, 413)

    def test_backup_sqlite_uploads_daily_and_rotation(self):
        self.store.sync(0, [change()])
        self.store.upload('pic', image())
        archive = self.store.backup(daily=True)
        self.assertEqual(self.store.backup(daily=True), archive)
        with tarfile.open(archive) as tar:
            names = tar.getnames()
            self.assertIn('data/nosotros.sqlite3', names)
            self.assertEqual(sum(n.startswith('uploads/') for n in names), 1)
            raw = tar.extractfile('data/nosotros.sqlite3').read()
        staged = self.root / 'snapshot.db'
        staged.write_bytes(raw)
        with app.contextlib.closing(sqlite3.connect(staged)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM activities').fetchone()[0], 1)
        for _ in range(8):
            self.store.backup()
        self.assertEqual(len(list(self.store.backups.glob('*.tar.gz'))), 7)

    def test_import_rollback_and_dedup(self):
        doc = {'app': 'nosotros-web', 'version': 1, 'state': {'events': [{'id': 'x'}]}, 'images': {'x': 'invalid'}}
        with self.assertRaises(app.APIError):
            self.store.import_backup(doc)
        self.assertEqual(self.store.sync()['cursor'], 0)
        doc['images'] = {'x': image()}
        self.assertEqual(self.store.import_backup(doc)['imported'], 1)
        reopened = app.Store(self.store.data, self.store.uploads, self.store.backups)
        self.assertTrue(reopened.import_backup(doc)['duplicate'])
        self.assertEqual(reopened.blob('x')[0], png())

    def test_concurrent_independent_stores(self):
        def write(i):
            store = app.Store(self.store.data, self.store.uploads, self.store.backups)
            return store.sync(0, [change(key='row-' + str(i), updated=i)])
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(12)))
        result = self.store.sync()
        self.assertEqual(result['cursor'], 12)
        self.assertEqual(len(result['changes']), 12)

    def test_cli_entrypoints_isolated(self):
        common = ['--data', str(self.store.data), '--uploads', str(self.store.uploads), '--backups', str(self.store.backups)]
        server = Path(app.__file__).parent
        result = subprocess.run([sys.executable, str(server / 'crear-usuario'), 'cli-user', '--password-stdin'] + common,
                                input='cli-test-password\n', text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('cli-test-password', result.stdout + result.stderr)
        doc = self.root / 'import.json'
        doc.write_text(json.dumps({'app': 'nosotros-web', 'version': 1, 'state': {'notes': {'2026-01-01': 'x'}}, 'images': {}}))
        result = subprocess.run([sys.executable, str(server / 'importar_respaldo.py'), str(doc)] + common, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, str(server / 'backup.py')] + common, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list(self.store.backups.glob('*.tar.gz'))), 1)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.web = root / 'web'
        cls.web.mkdir()
        (cls.web / 'index.html').write_text('<!doctype html>shell')
        (cls.web / 'secret.txt').write_text('private')
        cls.server = app.create_server(port=0, data=root / 'data', uploads=root / 'uploads', backups=root / 'backups', root=cls.web)
        cls.server.store.create_user('tester', 'test-password-long')
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self, method, path, body=None, cookie=None, origin=None, headers=None):
        head = {'X-Nosotros-App': '1', 'Origin': origin or f'http://127.0.0.1:{self.port}'}
        if cookie:
            head['Cookie'] = cookie
        if body is not None:
            body = json.dumps(body)
            head['Content-Type'] = 'application/json'
        head.update(headers or {})
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            connection.request(method, path, body, head)
            result = connection.getresponse()
            return result.status, dict(result.getheaders()), result.read()
        finally:
            connection.close()

    def login(self):
        status, headers, raw = self.request('POST', '/api/login', {'username': 'tester', 'password': 'test-password-long'})
        self.assertEqual(status, 200, raw)
        cookie = headers['Set-Cookie']
        for flag in ('HttpOnly', 'Secure', 'SameSite=Lax', 'Path=/', 'Max-Age=7776000'):
            self.assertIn(flag, cookie)
        return cookie.split(';')[0]

    def test_public_shell_minimal_health_and_private_routes(self):
        for route in ('/', '/api/health'):
            status, headers, raw = self.request('GET', route)
            self.assertEqual(status, 200)
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        for route in ('/api/session', '/api/sync', '/uploads/pic', '/api/unknown'):
            self.assertEqual(self.request('GET', route)[0], 401)
        for route in ('/server/app.py', '/data/nosotros.sqlite3', '/respaldos/x', '/.env', '/secret.txt', '/%2e%2e/secret.txt'):
            self.assertEqual(self.request('GET', route)[0], 404)
        self.assertNotIn('Access-Control-Allow-Origin', self.request('GET', '/')[1])

    def test_login_session_sync_upload_and_revocation(self):
        cookie = self.login()
        self.assertEqual(json.loads(self.request('GET', '/api/session', cookie=cookie)[2]), {'username': 'tester'})
        result = self.request('POST', '/api/sync', {'since': 0, 'changes': [change(key='http-row')]}, cookie=cookie)
        self.assertEqual(result[0], 200, result[2])
        self.assertEqual(self.request('POST', '/api/photos/http-pic', {'image': image()}, cookie=cookie)[0], 200)
        self.assertEqual(self.request('PUT', '/api/photos/http-pic', {'image': image()}, cookie=cookie)[0], 200)
        status, headers, raw = self.request('GET', '/uploads/http-pic', cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertEqual(raw, png())
        self.assertEqual(self.request('POST', '/api/logout', cookie=cookie)[0], 200)
        self.assertEqual(self.request('GET', '/api/session', cookie=cookie)[0], 401)

    def test_csrf_and_invalid_inputs(self):
        cookie = self.login()
        payload = {'since': 0, 'changes': []}
        self.assertEqual(self.request('POST', '/api/sync', payload, cookie, origin='https://attacker.example')[0], 403)
        self.assertEqual(self.request('POST', '/api/sync', payload, cookie, headers={'X-Nosotros-App': ''})[0], 403)
        self.assertEqual(self.request('GET', '/api/sync?since=-1', cookie=cookie)[0], 400)
        self.assertEqual(self.request('GET', '/api/sync?since=bad', cookie=cookie)[0], 400)
        self.assertEqual(self.request('POST', '/api/sync', {'since': 0, 'changes': [change(key='../x')]}, cookie)[0], 400)
        self.assertEqual(self.request('POST', '/api/sync', payload, cookie, headers={'Content-Length': str(app.MAX_SYNC + 1)})[0], 413)
        self.assertEqual(self.request('POST', '/api/sync', {'since': 0, 'changes': None}, cookie)[0], 400)
        self.assertEqual(self.request('POST', '/api/sync', payload, cookie, headers={'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request('GET', '/uploads/..%2fsecret', cookie=cookie)[0], 400)
        self.assertEqual(self.request('GET', '/uploads/missing', cookie=cookie)[0], 404)
        self.assertEqual(self.request('POST', '/api/login', {'username': 'tester', 'password': 'test-password-long'}, origin='https://attacker.example')[0], 403)
        # Reverse proxy host is accepted exclusively for this loopback peer.
        self.assertEqual(self.request('POST', '/api/sync', payload, cookie, origin='https://nosotros.example', headers={'X-Forwarded-Host': 'nosotros.example'})[0], 200)


if __name__ == '__main__':
    unittest.main()
