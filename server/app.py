#!/usr/bin/env python3
"""Nosotros: HTTP + SQLite, Python stdlib only. No public registration."""
import argparse
import base64
import binascii
import contextlib
import datetime
import getpass
import hashlib
import hmac
import http.cookies
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
import struct
import tarfile
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote

ROOT = Path(__file__).resolve().parent.parent
TABLES = {'events': 'activities', 'ideas': 'list_items', 'photos': 'photos',
          'collages': 'collages', 'days': 'days', 'notes': 'notes', 'settings': 'settings'}
ID = re.compile(r'[A-Za-z0-9_.:-]{1,100}\Z')
COOKIE = '__Host-nosotros'
SESSION_SECONDS = 90 * 86400
MAX_SYNC = 8 * 1024 * 1024
MAX_PHOTO = 3 * 1024 * 1024
MAX_ENCODED = 4 * 1024 * 1024


class APIError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now_ms():
    return time.time_ns() // 1000000


def valid_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value) or value in ('.', '..'):
        raise APIError('ID inválido')
    return value


def integer(value, name):
    if type(value) is not int or not 0 <= value <= 9223372036854775807:
        raise APIError(name + ' debe ser entero no negativo')
    return value


def json_text(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    except (ValueError, TypeError, RecursionError):
        raise APIError('JSON inválido')


def validate_change(change):
    if not isinstance(change, dict) or not isinstance(change.get('kind'), str) or change['kind'] not in TABLES:
        raise APIError('kind inválido')
    kind = change['kind']
    key = valid_id(change.get('id'))
    updated = integer(change.get('updated_at'), 'updated_at')
    deleted = change.get('deleted_at')
    if deleted is not None:
        integer(deleted, 'deleted_at')
    payload = change.get('payload')
    if not isinstance(payload, dict):
        raise APIError('payload debe ser objeto')
    if deleted is None:
        required = {'days': ('meet', 'note'), 'notes': ('text',), 'settings': ('theme',),
                    'collages': ('template', 'caption', 'slots')}.get(kind, ())
        if any(field not in payload for field in required):
            raise APIError('payload incompleto para ' + kind)
        if kind == 'collages' and (key != 'main' or not isinstance(payload['slots'], (list, dict))):
            raise APIError('collage requiere id main y slots objeto o array')
        if kind == 'notes' and not isinstance(payload['text'], str):
            raise APIError('notes.text debe ser texto')
        if kind == 'settings' and not isinstance(payload['theme'], str):
            raise APIError('settings.theme debe ser texto')
        if kind == 'days' and (not isinstance(payload['note'], str) or type(payload['meet']) is not bool):
            raise APIError('days requiere meet boolean y note texto')
    return kind, key, json_text(payload), updated, deleted


def decode_image(dataurl):
    if not isinstance(dataurl, str) or len(dataurl) > MAX_ENCODED + 32:
        raise APIError('Imagen demasiado grande', 413)
    match = re.fullmatch(r'data:image/(jpeg|png);base64,([A-Za-z0-9+/=\r\n]+)', dataurl)
    if not match:
        raise APIError('Sólo se admiten JPEG o PNG base64')
    try:
        data = base64.b64decode(match[2].replace('\r', '').replace('\n', ''), validate=True)
    except (binascii.Error, ValueError):
        raise APIError('Base64 inválido')
    if len(data) > MAX_PHOTO:
        raise APIError('Imagen supera 3 MB', 413)
    mime, width, height = image_info(data)
    if mime != 'image/' + match[1]:
        raise APIError('Firma no coincide con MIME')
    if width <= 0 or height <= 0 or width > 20000 or height > 20000 or width * height > 100000000:
        raise APIError('Dimensiones de imagen inválidas')
    return data, mime


def image_info(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 45:
        if data[12:16] != b'IHDR' or struct.unpack('>I', data[8:12])[0] != 13:
            raise APIError('PNG inválido')
        width, height = struct.unpack('>II', data[16:24])
        pos, ended, saw_data = 8, False, False
        while pos + 12 <= len(data):
            size = struct.unpack('>I', data[pos:pos + 4])[0]
            end = pos + 12 + size
            if end > len(data):
                raise APIError('PNG truncado')
            tag = data[pos + 4:pos + 8]
            import zlib
            if zlib.crc32(data[pos + 4:pos + 8 + size]) & 0xffffffff != struct.unpack('>I', data[pos + 8 + size:end])[0]:
                raise APIError('CRC PNG inválido')
            saw_data |= tag == b'IDAT'
            if tag == b'IEND':
                ended = size == 0 and end == len(data)
                break
            pos = end
        if not ended or not saw_data:
            raise APIError('PNG incompleto')
        return 'image/png', width, height
    if data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'):
        pos = 2
        while pos + 4 <= len(data):
            if data[pos] != 255:
                break
            while pos < len(data) and data[pos] == 255:
                pos += 1
            marker = data[pos]
            pos += 1
            if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
                continue
            length = int.from_bytes(data[pos:pos + 2], 'big')
            if length < 2 or pos + length > len(data):
                break
            if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf) and length >= 8:
                height, width = struct.unpack('>HH', data[pos + 3:pos + 7])
                return 'image/jpeg', width, height
            if marker == 0xda:
                break
            pos += length
    raise APIError('Firma/dimensiones JPEG o PNG inválidas')


class Store:
    def __init__(self, data=None, uploads=None, backups=None):
        self.data = Path(data or os.environ.get('NOSOTROS_DATA', ROOT / 'data')).resolve()
        self.uploads = Path(uploads or os.environ.get('NOSOTROS_UPLOADS', ROOT / 'uploads')).resolve()
        self.backups = Path(backups or os.environ.get('NOSOTROS_BACKUPS', ROOT / 'respaldos')).resolve()
        for directory in (self.data, self.uploads, self.backups):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)
        self.db = self.data / 'nosotros.sqlite3'
        self.lock = threading.RLock()
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS sequence (seq INTEGER PRIMARY KEY AUTOINCREMENT)')
            for table in TABLES.values():
                db.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at INTEGER NOT NULL, deleted_at INTEGER, server_seq INTEGER NOT NULL)')
                db.execute(f'CREATE INDEX IF NOT EXISTS {table}_seq ON {table}(server_seq)')
            db.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, salt BLOB NOT NULL, password BLOB NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES users(username), expires INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS login_attempts (username TEXT NOT NULL, ip TEXT NOT NULL, failures INTEGER NOT NULL, blocked_until INTEGER NOT NULL, PRIMARY KEY(username,ip))')
            db.execute('CREATE TABLE IF NOT EXISTS blobs (id TEXT PRIMARY KEY, filename TEXT NOT NULL, mime TEXT NOT NULL, digest TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS migrations (sha256 TEXT PRIMARY KEY, imported_at INTEGER NOT NULL)')
            db.commit()
        os.chmod(self.db, 0o600)

    @contextlib.contextmanager
    def connection(self):
        db = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=30000')
        try:
            yield db
        finally:
            if db.in_transaction:
                db.rollback()
            db.close()

    @staticmethod
    def username(value):
        if not isinstance(value, str):
            raise APIError('Usuario inválido')
        value = value.strip().casefold()
        if not re.fullmatch(r'[a-z0-9_.-]{1,64}', value):
            raise APIError('Usuario inválido')
        return value

    def create_user(self, username, password):
        username = self.username(username)
        if not isinstance(password, str) or not 10 <= len(password) <= 1024:
            raise APIError('Contraseña requiere entre 10 y 1024 caracteres')
        salt = secrets.token_bytes(16)
        hashed = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
        with self.lock, self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
                raise APIError('Usuario ya existe', 409)
            if db.execute('SELECT COUNT(*) FROM users').fetchone()[0] >= 2:
                raise APIError('Máximo dos usuarios', 409)
            db.execute('INSERT INTO users VALUES (?,?,?)', (username, salt, hashed))
            db.commit()

    def login(self, username, password, ip):
        username = self.username(username)
        if not isinstance(password, str) or len(password) > 1024:
            raise APIError('Credenciales inválidas', 401)
        current = int(time.time())
        with self.lock, self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            attempt = db.execute('SELECT * FROM login_attempts WHERE username=? AND ip=?', (username, ip)).fetchone()
            if attempt and attempt['blocked_until'] > current:
                raise APIError('Demasiados intentos; espere 10 minutos', 429)
            user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
            calculated = hashlib.scrypt(password.encode(), salt=user['salt'] if user else b'\x00' * 16, n=16384, r=8, p=1)
            if not user or not hmac.compare_digest(calculated, user['password']):
                failures = (attempt['failures'] if attempt and attempt['blocked_until'] == 0 else 0) + 1
                blocked = current + 600 if failures >= 5 else 0
                db.execute('INSERT OR REPLACE INTO login_attempts VALUES (?,?,?,?)', (username, ip, failures, blocked))
                db.commit()  # Persist failures even though authentication raises.
                raise APIError('Credenciales inválidas', 401)
            db.execute('DELETE FROM login_attempts WHERE username=? AND ip=?', (username, ip))
            db.execute('DELETE FROM sessions WHERE expires<=?', (current,))
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (self.token_hash(token), username, current + SESSION_SECONDS))
            db.commit()
            return token, username

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def session(self, token):
        if not token:
            return None
        with self.connection() as db:
            row = db.execute('SELECT username FROM sessions WHERE token_hash=? AND expires>?', (self.token_hash(token), int(time.time()))).fetchone()
            return row['username'] if row else None

    def logout(self, token):
        with self.lock, self.connection() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (self.token_hash(token),))

    def revoke_sessions(self, username):
        with self.lock, self.connection() as db:
            db.execute('DELETE FROM sessions WHERE username=?', (self.username(username),))

    def _apply(self, db, validated):
        accepted = []
        for kind, key, payload, updated, deleted in validated:
            table = TABLES[kind]
            previous = db.execute(f'SELECT * FROM {table} WHERE id=?', (key,)).fetchone()
            # Timestamp wins; tombstone wins ties, then a stable payload order for convergence.
            incoming = (updated, deleted is not None, deleted or 0, payload)
            existing = None if previous is None else (previous['updated_at'], previous['deleted_at'] is not None, previous['deleted_at'] or 0, previous['payload'])
            if existing is not None and incoming <= existing:
                continue
            seq = db.execute('INSERT INTO sequence DEFAULT VALUES').lastrowid
            db.execute(f'INSERT OR REPLACE INTO {table} VALUES (?,?,?,?,?)', (key, payload, updated, deleted, seq))
            accepted.append({'kind': kind, 'id': key, 'updated_at': updated})
        return accepted

    def sync(self, since=0, changes=None):
        integer(since, 'since')
        changes = [] if changes is None else changes
        if not isinstance(changes, list) or len(changes) > 2000:
            raise APIError('changes debe ser array con máximo 2000 registros')
        validated = [validate_change(change) for change in changes]
        with self.lock, self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            cursor = db.execute('SELECT COALESCE(MAX(seq),0) FROM sequence').fetchone()[0]
            if since > cursor:
                raise APIError('Cursor posterior al servidor; resincronice desde 0', 409)
            accepted = self._apply(db, validated)
            rows = []
            for kind, table in TABLES.items():
                for row in db.execute(f'SELECT * FROM {table} WHERE server_seq>?', (since,)):
                    rows.append((row['server_seq'], {'kind': kind, 'id': row['id'], 'payload': json.loads(row['payload']), 'updated_at': row['updated_at'], 'deleted_at': row['deleted_at']}))
            cursor = db.execute('SELECT COALESCE(MAX(seq),0) FROM sequence').fetchone()[0]
            db.commit()
            return {'cursor': cursor, 'changes': [row for _, row in sorted(rows)], 'accepted': accepted, 'server_time': now_ms()}

    def _write_blob(self, db, key, data, mime):
        # Content-addressed files never change beneath an in-flight reader/backup.
        digest = hashlib.sha256(data).hexdigest()
        filename = digest + ('.jpg' if mime == 'image/jpeg' else '.png')
        target = self.uploads / filename
        if not target.exists():
            fd, temp = tempfile.mkstemp(prefix='.upload-', dir=self.uploads)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    os.chmod(temp, 0o600)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, target)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        db.execute('INSERT OR REPLACE INTO blobs VALUES (?,?,?,?)', (key, filename, mime, digest))

    def upload(self, key, dataurl):
        valid_id(key)
        data, mime = decode_image(dataurl)
        with self.lock, self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._write_blob(db, key, data, mime)
            db.commit()
        return {'ok': True, 'url': '/uploads/' + key}

    def blob(self, key):
        valid_id(key)
        with self.lock, self.connection() as db:
            row = db.execute('SELECT filename,mime FROM blobs WHERE id=?', (key,)).fetchone()
            if not row:
                raise APIError('Imagen no encontrada', 404)
            try:
                return (self.uploads / row['filename']).read_bytes(), row['mime']
            except FileNotFoundError:
                raise APIError('Imagen no encontrada', 404)

    def backup(self, daily=False):
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
        with self.lock, self.connection() as source:
            source.execute('BEGIN IMMEDIATE')  # Also excludes other CLI writers.
            if daily:
                found = sorted(self.backups.glob('nosotros-' + stamp + '-*.tar.gz'))
                if found:
                    return found[-1]
            filename = 'nosotros-' + stamp + '-' + secrets.token_hex(4) + '.tar.gz'
            destination = self.backups / filename
            with tempfile.TemporaryDirectory(prefix='.backup-', dir=self.backups) as staging:
                snapshot = Path(staging) / 'nosotros.sqlite3'
                # Separate read connection avoids backing up our own active write transaction.
                with self.connection() as reader:
                    target = sqlite3.connect(snapshot)
                    try:
                        reader.backup(target)
                    finally:
                        target.close()
                os.chmod(snapshot, 0o600)
                temp = Path(staging) / 'archive.tar.gz'
                with tarfile.open(temp, 'w:gz') as archive:
                    archive.add(snapshot, arcname='data/nosotros.sqlite3')
                    for row in source.execute('SELECT DISTINCT filename FROM blobs'):
                        path = self.uploads / row['filename']
                        if not path.is_file():
                            raise APIError('Falta un archivo de imagen; respaldo cancelado', 409)
                        archive.add(path, arcname='uploads/' + path.name)
                os.chmod(temp, 0o600)
                os.replace(temp, destination)
            source.commit()
            for obsolete in sorted(self.backups.glob('nosotros-*.tar.gz'), key=lambda p: p.stat().st_mtime, reverse=True)[7:]:
                obsolete.unlink()
            return destination

    def import_backup(self, document):
        if not isinstance(document, dict) or document.get('app') != 'nosotros-web' or document.get('version') != 1 or not isinstance(document.get('state'), dict):
            raise APIError('Formato de respaldo inválido')
        digest = hashlib.sha256(json_text(document).encode()).hexdigest()
        state = document['state']
        changes = []
        timestamp = now_ms()
        def add(kind, key, payload):
            if not isinstance(payload, dict):
                raise APIError('Registro de respaldo inválido')
            changes.append({'kind': kind, 'id': key, 'payload': payload, 'updated_at': payload.get('updated_at', timestamp), 'deleted_at': payload.get('deleted_at')})
        for kind in ('events', 'ideas', 'photos'):
            entries = state.get(kind, [])
            if not isinstance(entries, list):
                raise APIError(kind + ' debe ser array')
            for payload in entries:
                if not isinstance(payload, dict):
                    raise APIError('Registro inválido')
                add(kind, payload.get('id'), payload)
        for kind in ('days', 'notes'):
            entries = state.get(kind, {})
            if not isinstance(entries, dict):
                raise APIError(kind + ' debe ser objeto')
            for key, payload in entries.items():
                if kind == 'notes' and isinstance(payload, str):
                    payload = {'text': payload}
                if kind == 'days' and isinstance(payload, dict):
                    payload = {'meet': False, 'note': '', **payload}
                add(kind, key, payload)
        if state.get('collage') is not None:
            add('collages', 'main', state['collage'])
        if state.get('settings') is not None:
            add('settings', 'main', state['settings'])
        validated = [validate_change(change) for change in changes]
        images = document.get('images', {})
        if not isinstance(images, dict):
            raise APIError('images debe ser objeto')
        decoded = [(valid_id(key), *decode_image(dataurl)) for key, dataurl in images.items()]
        with self.lock, self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM migrations WHERE sha256=?', (digest,)).fetchone():
                return {'imported': 0, 'duplicate': True}
            for key, data, mime in decoded:
                self._write_blob(db, key, data, mime)
            accepted = self._apply(db, validated)
            db.execute('INSERT INTO migrations VALUES (?,?)', (digest, timestamp))
            db.commit()
            return {'imported': len(accepted), 'duplicate': False}


PUBLIC = {'index.html', 'sync.js', 'sw.js', 'manifest.json', 'icon-192.png', 'icon-512.png', 'favicon.ico', 'favicon.png', 'favicon.svg'}
CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"


class Handler(BaseHTTPRequestHandler):
    server_version = 'Nosotros'
    sys_version = ''

    def log_message(self, format, *args):
        pass  # Never log URLs, usernames, cookies, payloads or personal data.

    def respond(self, status, data, mime='application/json; charset=utf-8', headers=None):
        if not isinstance(data, bytes):
            data = json_text(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', CSP)
        self.send_header('Referrer-Policy', 'no-referrer')
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def read_json(self, limit):
        if self.headers.get('Transfer-Encoding'):
            raise APIError('Transfer-Encoding no permitido')
        content_type = self.headers.get('Content-Type', '').split(';')[0].strip().lower()
        if content_type != 'application/json':
            raise APIError('Se requiere application/json', 415)
        try:
            length = int(self.headers.get('Content-Length', '-1'))
        except ValueError:
            raise APIError('Content-Length inválido')
        if length < 0:
            raise APIError('Content-Length requerido', 411)
        if length > limit:
            raise APIError('Cuerpo demasiado grande', 413)
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise APIError('Cuerpo incompleto')
            result = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise APIError('JSON inválido')
        if not isinstance(result, dict):
            raise APIError('Se requiere objeto JSON')
        return result

    def csrf(self):
        if self.headers.get('X-Nosotros-App') != '1':
            raise APIError('Falta X-Nosotros-App', 403)
        origin = self.headers.get('Origin')
        if not origin:
            raise APIError('Origin requerido', 403)
        host = self.headers.get('Host', '')
        try:
            local = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            local = False
        forwarded = self.headers.get('X-Forwarded-Host')
        if local and forwarded:
            host = forwarded
        parsed = urlsplit(origin)
        if parsed.scheme not in ('http', 'https') or parsed.netloc.lower() != host.lower() or parsed.path or parsed.query or parsed.fragment or parsed.username or ',' in host:
            raise APIError('Origin no autorizado', 403)

    def token(self):
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except http.cookies.CookieError:
            return ''
        return cookie[COOKIE].value if COOKIE in cookie else ''

    def dispatch(self):
        try:
            self.connection.settimeout(30)
            self.route()
        except APIError as error:
            self.respond(error.status, {'error': str(error)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except sqlite3.OperationalError:
            self.respond(503, {'error': 'Almacenamiento temporalmente no disponible'})
        except Exception:
            self.respond(500, {'error': 'Error interno'})

    def route(self):
        path = unquote(urlsplit(self.path).path)
        method = self.command
        store = self.server.store
        if path == '/api/health' and method in ('GET', 'HEAD'):
            return self.respond(200, {'ok': True})
        if path == '/api/login' and method == 'POST':
            body = self.read_json(8192)
            self.csrf()
            token, username = store.login(body.get('username'), body.get('password'), self.client_address[0])
            return self.respond(200, {'username': username}, headers={'Set-Cookie': f'{COOKIE}={token}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={SESSION_SECONDS}'})
        if path.startswith('/api/') or path.startswith('/uploads/'):
            token = self.token()
            username = store.session(token)
            if not username:
                raise APIError('Sesión requerida', 401)
            body = None
            if method not in ('GET', 'HEAD'):
                # Consume bounded recognized request bodies before CSRF rejection. This
                # avoids dropping the error response with an unread-body TCP reset.
                if path == '/api/sync' and method == 'POST':
                    body = self.read_json(MAX_SYNC)
                elif path.startswith('/api/photos/') and method in ('POST', 'PUT'):
                    body = self.read_json(MAX_ENCODED + 1024)
                self.csrf()
            if path == '/api/session' and method in ('GET', 'HEAD'):
                return self.respond(200, {'username': username})
            if path == '/api/logout' and method == 'POST':
                store.logout(token)
                return self.respond(200, {'ok': True}, headers={'Set-Cookie': f'{COOKIE}=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0'})
            if path == '/api/sync':
                if method == 'GET':
                    query = parse_qs(urlsplit(self.path).query)
                    try:
                        since = int(query.get('since', ['0'])[0])
                    except ValueError:
                        raise APIError('since inválido')
                    return self.respond(200, store.sync(since, []))
                if method == 'POST':
                    if 'since' not in body or not isinstance(body.get('changes'), list):
                        raise APIError('Se requieren since y changes (array)')
                    return self.respond(200, store.sync(body['since'], body['changes']))
            if path.startswith('/api/photos/') and method in ('POST', 'PUT'):
                return self.respond(200, store.upload(path[len('/api/photos/'):], body.get('image')))
            if path.startswith('/uploads/') and method in ('GET', 'HEAD'):
                data, mime = store.blob(path[len('/uploads/'):])
                return self.respond(200, data, mime)
            raise APIError('Ruta no encontrada', 404)
        if method not in ('GET', 'HEAD'):
            raise APIError('Método no permitido', 405)
        name = 'index.html' if path == '/' else path.lstrip('/')
        if name not in PUBLIC:
            raise APIError('Ruta no encontrada', 404)
        target = self.server.root / name
        # Resolved containment also blocks symlinks pointing at private files.
        if target.resolve().parent != self.server.root or not target.is_file():
            raise APIError('Archivo no encontrado', 404)
        return self.respond(200, target.read_bytes(), mimetypes.guess_type(name)[0] or 'application/octet-stream')

    do_GET = dispatch
    do_HEAD = dispatch
    do_POST = dispatch
    do_PUT = dispatch
    do_DELETE = dispatch
    do_OPTIONS = dispatch


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(host='127.0.0.1', port=8787, data=None, uploads=None, backups=None, root=None, **kwargs):
    # Binding beyond loopback is intentional only when explicitly requested by CLI.
    server = Server((host, port), Handler)
    try:
        server.store = Store(data, uploads, backups)
        server.root = Path(root or ROOT).resolve()
    except Exception:
        server.server_close()
        raise
    return server


def storage_arguments(parser):
    parser.add_argument('--data', default=None, help='Directorio SQLite (NOSOTROS_DATA)')
    parser.add_argument('--uploads', default=None, help='Directorio imágenes (NOSOTROS_UPLOADS)')
    parser.add_argument('--backups', default=None, help='Directorio respaldos (NOSOTROS_BACKUPS)')


def store_from_args(args):
    return Store(args.data, args.uploads, args.backups)


def user_main():
    parser = argparse.ArgumentParser(description='Crear uno de los dos usuarios; no acepta contraseñas como argumento')
    parser.add_argument('username')
    parser.add_argument('--password-stdin', action='store_true')
    storage_arguments(parser)
    args = parser.parse_args()
    try:
        if args.password_stdin:
            import sys
            password = sys.stdin.readline(4096).rstrip('\r\n')
        else:
            password = getpass.getpass('Contraseña (mínimo 10 caracteres): ')
            if password != getpass.getpass('Repetir contraseña: '):
                raise APIError('Las contraseñas no coinciden')
        store_from_args(args).create_user(args.username, password)
        print('Usuario creado.')
    except APIError as error:
        parser.exit(1, str(error) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=int(os.environ.get('NOSOTROS_PORT', '8787')))
    storage_arguments(parser)
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.data, args.uploads, args.backups)
    stop = threading.Event()
    def periodic():
        while not stop.is_set():
            try:
                server.store.backup(daily=True)
            except Exception:
                print('No se pudo crear el respaldo automático.', flush=True)
            stop.wait(24 * 3600)
    thread = threading.Thread(target=periodic, name='backup.daily', daemon=True)
    thread.start()
    print('Nosotros listo.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        thread.join(timeout=30)


if __name__ == '__main__':
    main()
