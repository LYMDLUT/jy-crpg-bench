"""Historical GETs must remain on disk after the realtime cache rolls over."""
import collections
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

with mock.patch('ctypes.CDLL', return_value=mock.MagicMock()):
    import server
from recording_store import RecordingStore


class DiskHistoryMarkerTests(unittest.TestCase):
    def test_every_get_survives_realtime_cache_eviction(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer=RecordingStore(Path(tmp)/'recording.jsonl')
            try:
                with mock.patch.object(server,'recording_store',writer), \
                     mock.patch.object(server.warden,'ON',False), \
                     mock.patch.dict(os.environ,QUNXIA_PERSIST_HISTORY='1'), \
                     mock.patch.object(server,'history',collections.deque(maxlen=300)), \
                     mock.patch.object(server,'_seq',[0]), \
                     mock.patch.object(server,'persist_activity'):
                    for _ in range(350):server.log_action('agent','GET','screen')
                    self.assertEqual(len(server.history),300)
                events=[json.loads(line) for line in writer.path.read_text().splitlines()[1:]]
                self.assertEqual(len(events),350)
                self.assertTrue(all(row['act']=='GET' and row['history']==1 for row in events))
            finally:writer.close()

    def test_benchmark_never_adds_interactive_history_markers(self):
        writer=mock.Mock()
        with mock.patch.object(server,'recording_store',writer), \
             mock.patch.object(server.warden,'ON',True), \
             mock.patch.dict(os.environ,QUNXIA_PERSIST_HISTORY='1'):
            self.assertFalse(server.disk_history_enabled())
            server.record_activity(dict(at=1,verb='GET',src='agent',target='screen',detail='',ok=True))
            writer.append.assert_not_called()


class HistoryPageCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_exposes_explicit_history_capability(self):
        for benchmark in (False, True):
            with mock.patch.object(server.warden, 'ON', benchmark):
                response = await server.index(None)
            expected = str(not benchmark).lower()
            self.assertIn(f'data-history-enabled="{expected}"', response.text)
            self.assertNotIn('data-history-enabled="auto"', response.text)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')


if __name__=='__main__':unittest.main()
