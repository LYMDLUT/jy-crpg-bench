"""File recording regressions: complete history, stable readers and exact retry."""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from recording import Snapshot, RecordingAPI
from recording_store import RecordingStore
from storage import validate_recording_directory


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'run.jsonl'
        self.store=RecordingStore(self.path,started=10)
        self.addCleanup(self.store.close)

    def snapshot(self):
        snap=Snapshot(**self.store.pin())
        self.addCleanup(snap.close)
        return snap

    def test_reset_keeps_full_old_recording_and_open_reader(self):
        self.store.append({'t':0,'d':'old'})
        old=self.snapshot()
        archive=self.store.reset(20)
        self.store.append({'t':1,'d':'new'})
        self.assertEqual(list(old),[{'t':0,'d':'old'}])
        self.assertEqual(list(self.snapshot()),[{'t':1,'d':'new'}])
        self.assertIn(b'old',archive.read_bytes())
        self.assertEqual(old.header['started'],10)

    def test_failed_partial_append_and_fsync_retry_exactly_once(self):
        self.store.append({'t':0,'key':'up','down':True})
        before=self.path.read_bytes()
        real=os.write
        calls=[0]
        def broken(fd,data):
            calls[0]+=1
            if calls[0]==1:return real(fd,data[:4])
            raise OSError('disk full')
        with mock.patch('recording_store.os.write',side_effect=broken):
            self.assertFalse(self.store.append({'t':1,'key':'up','down':False}))
        self.assertEqual(self.path.read_bytes(),before)
        with mock.patch('recording_store.os.fsync',side_effect=OSError('flush failed')):
            self.assertFalse(self.store.flush())
        self.assertEqual(self.path.read_bytes(),before)
        self.assertTrue(self.store.flush())
        self.assertEqual([e['down'] for e in self.snapshot()],[True,False])
        self.assertEqual(self.store.pending_bytes,0)

    def test_complete_history_exceeds_old_memory_cap_with_bounded_pages(self):
        payload=base64.b64encode(b'x'*(768<<10)).decode()
        for i in range(14):self.store.append({'t':i*40,'d':payload})
        self.assertGreater(self.path.stat().st_size,12<<20)
        snap=self.snapshot()
        start=None;count=0
        while True:
            page=snap.page(start)
            self.assertLessEqual(len(page['events']),1)
            count+=len(page['events'])
            if page['done']:break
            start=page['next']
        self.assertEqual(count,14)
        self.assertEqual(snap.duration,520)
        self.assertEqual(self.store.pending_bytes,0)

    def test_reader_excludes_later_appends_and_rejects_midline_cursor(self):
        self.store.append({'t':1,'key':'up','down':True})
        old=self.snapshot()
        self.store.append({'t':2,'key':'up','down':False})
        self.assertEqual(len(list(old)),1)
        with self.assertRaises(ValueError):old.page(old.begin+1)

    def test_reset_failure_keeps_active_file_and_lease(self):
        self.store.append({'t':0,'key':'up','down':True})
        before=self.path.read_bytes()
        with mock.patch.object(self.store,'_prepare_file',side_effect=OSError('full')):
            with self.assertRaises(OSError):self.store.reset(20)
        self.assertEqual(self.path.read_bytes(),before)
        with self.assertRaises(RuntimeError):RecordingStore(self.path)
        self.store.reset(20)
        with self.assertRaises(RuntimeError):RecordingStore(self.path)

    def test_cloud_container_root_is_not_accepted_as_disk(self):
        mount='1 0 0:1 / / rw - overlay overlay rw\n'
        with self.assertRaises(RuntimeError):
            validate_recording_directory(self.temp.name,cloud=True,mountinfo=mount)


class RecordingApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_paged_reader_survives_reset_and_can_close(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            store=RecordingStore(Path(directory)/'run.jsonl',started=10)
            api=RecordingAPI(store)
            try:
                store.append({'t':1,'key':'up','down':True})
                response=await api.handle(SimpleNamespace(query={'view':'paged'}))
                page=json.loads(response.body)
                store.reset(20)
                response=await api.handle(SimpleNamespace(query={'view':'paged','token':page['token']}))
                self.assertEqual(json.loads(response.body)['events'],page['events'])
                await api.handle(SimpleNamespace(query={'view':'paged','token':page['token'],'close':'1'}))
                self.assertFalse(api.readers)
            finally:
                api.close();store.close()


class RecordingWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_worker_health as workers
        workers.WorkerIntegrationTests.setUpClass.__func__(cls)

    def setUp(self):
        import test_worker_health as workers
        workers.WorkerIntegrationTests.setUp(self)

    def test_reset_without_viewers_records_full_frame_and_preserves_old_reader(self):
        import test_worker_health as workers
        import zlib
        workers.WorkerIntegrationTests.launch(self)
        def healthy():return workers.WorkerIntegrationTests.healthy(self)
        workers.wait_for(healthy)
        status,body=workers.request(self.port,'/api/reset?token=test',{})
        self.assertEqual(status,200,body)
        page=json.loads(workers.request(self.port,'/api/recording?view=paged')[1])
        picture=next(e for e in page['events'] if 'd' in e)
        self.assertEqual(zlib.decompress(base64.b64decode(picture['d']))[0],1)
        status,body=workers.request(self.port,'/api/reset?token=test',{})
        self.assertEqual(status,200,body)
        old=json.loads(workers.request(self.port,'/api/recording?view=paged&token='+page['token'])[1])
        self.assertEqual(old['events'],page['events'])
        raw=workers.request(self.port,'/api/recording?format=jsonl')[1]
        self.assertIn('version',json.loads(raw.splitlines()[0]))
        exported=json.loads(workers.request(self.port,'/api/recording')[1])
        self.assertTrue(any('d' in e for e in exported['events']))
        self.assertEqual(healthy()['recording']['cache_bytes'],0)
