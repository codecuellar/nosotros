import unittest
import tempfile
from pathlib import Path
import app


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = app.Store(self.root / 'data', self.root / 'uploads', self.root / 'backups')

    def tearDown(self):
        self.tmp.cleanup()

    def test_sync_roundtrip(self):
        change = {'kind': 'events', 'id': 'event-1', 'payload': {'title': 'Test'}, 'updated_at': 100, 'deleted_at': None}
        result = self.store.sync(0, [change])
        self.assertEqual(result['changes'], [change])
        self.assertEqual(result['cursor'], 1)
        self.assertEqual(self.store.sync(1, [])['changes'], [])


class ImportTests(StoreTests):
    def test_actual_v1_shape_preserves_slots_and_encuadre(self):
        doc = {'app': 'nosotros-web', 'version': 1, 'state': {
            'events': [], 'ideas': [],
            'photos': [{'id': 'pic-1', 'crop': {'x': 0.2, 'y': 0.8}, 'scale': 1.4}],
            'days': {'2026-01-01': {'meet': True}},
            'notes': {'2026-01-01': 'nota'},
            'collage': {'template': 0, 'caption': 'caption', 'slots': {'0': {'id': 'pic-1', 'x': 0.4}}},
            'settings': {'theme': 'auto'}}, 'images': {}}
        result = self.store.import_backup(doc)
        self.assertEqual(result['imported'], 5)
        self.assertTrue(self.store.import_backup(doc)['duplicate'])
        rows = {x['kind']: x for x in self.store.sync()['changes']}
        self.assertEqual(rows['collages']['payload']['slots'], doc['state']['collage']['slots'])
        self.assertEqual(rows['photos']['payload']['crop'], {'x': 0.2, 'y': 0.8})
        self.assertEqual(rows['days']['payload'], {'meet': True, 'note': ''})


if __name__ == '__main__':
    unittest.main()
