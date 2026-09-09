import collections
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from activity import ActivityStore, MAX_BYTES


def entry(seq, **extra):
    return dict(id=seq, at=1700000000 + seq, src='agent', verb='KEY',
                target='up', detail='', ok=True, **extra)


class ActivityStoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'activity.json'
        self.store = ActivityStore(self.path)

    def test_restart_retains_order_timestamps_and_thumbnails(self):
        rows = [entry(1), entry(2, thumb='data:image/webp;base64,AAAA')]
        self.store.save(rows)
        self.assertEqual(ActivityStore(self.path).load(), rows)

    def test_retention_and_thumbnail_budget(self):
        self.store.save([entry(i, thumb='data:image/webp;base64,AAAA') for i in range(1, 502)])
        rows = self.store.load()
        self.assertEqual([r['id'] for r in rows], list(range(202, 502)))
        self.assertEqual(sum('thumb' in r for r in rows), 40)
        self.assertLess(self.path.stat().st_size, MAX_BYTES)

    def test_failed_replace_keeps_old_snapshot_and_cleans_temp(self):
        self.store.save([entry(1)])
        before = self.path.read_bytes()
        with mock.patch('activity.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.store.save([entry(2)])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_fsync_keeps_old_snapshot(self):
        self.store.save([entry(1)])
        with mock.patch('activity.os.fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.save([entry(2)])
        self.assertEqual(self.store.load(), [entry(1)])

    def test_reset_and_missing_snapshot(self):
        self.assertEqual(self.store.load(), [])
        self.store.save([entry(1)])
        self.store.save([])
        self.assertEqual(ActivityStore(self.path).load(), [])

    def test_rejects_corrupt_oversized_and_nonmonotonic_files(self):
        for raw in [b'{', b'x' * (MAX_BYTES + 1),
                    json.dumps({'version': 1, 'entries': [entry(2), entry(1)]}).encode(),
                    json.dumps({'version': 2, 'entries': []}).encode()]:
            with self.subTest(size=len(raw)):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    self.store.load()
                self.assertEqual(self.path.read_bytes(), raw)


class ServerActivityTests(unittest.TestCase):
    def setUp(self):
        with mock.patch('ctypes.CDLL', return_value=mock.MagicMock()):
            import server
        self.server = server
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'activity.json'
        for patch in [mock.patch.object(server, 'SAVES', tmp.name),
                      mock.patch.object(server, 'history', collections.deque(maxlen=300)),
                      mock.patch.object(server, '_seq', [0]),
                      mock.patch.object(server, 'activity_store', None),
                      mock.patch.object(server.warden, 'ON', False),
                      mock.patch.dict(os.environ, QUNXIA_PERSIST_HISTORY='1')]:
            patch.start()
            self.addCleanup(patch.stop)

    def test_real_log_hook_restores_ids_without_changing_session_counters(self):
        s = self.server
        counters = dict(s.session)
        ActivityStore(self.path).save([entry(123)])
        s.restore_activity()
        self.assertEqual(s.session, counters)
        new = s.log_action('agent', 'GET', 'screen')
        self.assertEqual(new['id'], 124)
        self.assertEqual(ActivityStore(self.path).load()[-1], new)
        s.history.clear()
        s.activity_store = None
        s.restore_activity()
        self.assertEqual([e['id'] for e in s.history], [123, 124])
        s.history.clear()
        s.persist_activity()
        self.assertEqual(ActivityStore(self.path).load(), [])

    def test_benchmark_and_default_do_not_load_or_write(self):
        s = self.server
        for bench, flag in [(True, '1'), (False, '0')]:
            with mock.patch.object(s.warden, 'ON', bench), mock.patch.dict(os.environ, QUNXIA_PERSIST_HISTORY=flag):
                s.restore_activity()
                s.log_action('agent', 'GET', 'screen')
                self.assertIsNone(s.activity_store)
                self.assertFalse(self.path.exists())

    def test_corruption_is_preserved_and_game_logging_continues(self):
        self.path.write_text('{broken')
        self.server.restore_activity()
        self.server.log_action('web', 'GET', 'screen')
        self.assertIsNone(self.server.activity_store)
        self.assertEqual(self.path.read_text(), '{broken')
        self.assertEqual(len(self.server.history), 1)

class LegacyImportTests(unittest.TestCase):
    def test_import_matches_legacy_timestamp_precision(self):
        from import_activity import import_recording
        with tempfile.TemporaryDirectory() as tmp:
            recording, history = Path(tmp) / 'recording.jsonl', Path(tmp) / 'activity.json'
            events = [{'t': 1.358, 'act': 'GET', 'who': 'agent', 'on': 'screen'}]
            raw = '\n'.join(json.dumps(x) for x in [{'version': 1, 'started': 1700000000}, *events]) + '\n'
            recording.write_text(raw)
            old = entry(1)
            old['detail'] = 'legacy'
            old['ok'] = True
            old['verb'] = 'GET'
            old['target'] = 'screen'
            old['at'] = 1700000001.358023
            ActivityStore(history).save([old])
            report = import_recording(recording, history)
            rows = ActivityStore(history).load()
            self.assertEqual(report['recording_actions'], 1)
            self.assertEqual(report['retained_entries'], 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['at'], 1700000001.358023)
            self.assertEqual(rows[0]['detail'], 'legacy')
            import_recording(recording, history)
            self.assertEqual(ActivityStore(history).load(), rows)
            self.assertEqual(recording.read_text(), raw)

    def test_import_capacity_keeps_new_entries_when_recording_is_full(self):
        from import_activity import import_recording
        with tempfile.TemporaryDirectory() as tmp:
            recording, history = Path(tmp) / 'recording.jsonl', Path(tmp) / 'activity.json'
            events = [{'t': i, 'act': 'GET', 'who': 'old-agent', 'on': 'screen'}
                      for i in range(300)]
            raw = '\n'.join(json.dumps(x) for x in [{'version': 1, 'started': 1700000000}, *events]) + '\n'
            recording.write_text(raw)
            newer = []
            for i in range(1, 301):
                row = entry(i)
                row['src'] = 'new-agent'
                row['detail'] = 'new'
                row['at'] = 1700001000 + i
                newer.append(row)
            ActivityStore(history).save(newer)
            report = import_recording(recording, history)
            rows = ActivityStore(history).load()
            self.assertEqual(report['recording_actions'], 300)
            self.assertEqual(report['retained_entries'], 300)
            self.assertEqual([row['src'] for row in rows], ['new-agent'] * 300)
            self.assertEqual(rows[-1]['at'], 1700001300)
            self.assertEqual(recording.read_text(), raw)

    def test_import_merges_deduplicates_and_leaves_recording_unchanged(self):
        from import_activity import import_recording
        with tempfile.TemporaryDirectory() as tmp:
            recording, history = Path(tmp) / 'recording.jsonl', Path(tmp) / 'activity.json'
            raw = json.dumps({'version': 1, 'started': 1700000000}) + '\n'
            raw += '\n'.join(json.dumps({'t': i, 'act': 'GET', 'who': 'old-agent', 'on': 'screen'}) for i in range(1, 305)) + '\n'
            raw += '{"t": 305, "d":"frame"}\n{"t":306'
            recording.write_text(raw)
            ActivityStore(history).save([entry(1, thumb='data:image/webp;base64,AAAA') | {'at': 1700000400}])
            report = import_recording(recording, history)
            self.assertEqual(report['recording_actions'], 304)
            rows = ActivityStore(history).load()
            self.assertEqual(len(rows), 300)
            self.assertEqual(rows[0]['at'], 1700000006)
            self.assertIsNone(rows[0]['ok'])
            self.assertEqual(rows[-1]['src'], 'agent')
            import_recording(recording, history)
            self.assertEqual(ActivityStore(history).load(), rows)
            self.assertEqual(recording.read_text(), raw)

    def test_import_rejects_invalid_time_without_overwriting(self):
        from import_activity import import_recording
        with tempfile.TemporaryDirectory() as tmp:
            recording, history = Path(tmp) / 'recording.jsonl', Path(tmp) / 'activity.json'
            recording.write_text('{"started":0}\n{"t":-1,"act":"KEY"}\n')
            ActivityStore(history).save([entry(1)])
            before = history.read_bytes()
            with self.assertRaises(ValueError):
                import_recording(recording, history)
            self.assertEqual(history.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
