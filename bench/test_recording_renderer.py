import base64
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'server'))
from recording import Snapshot
from recording_store import RecordingStore
from render import render


@unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg required')
class DiskRendererTest(unittest.TestCase):
    def test_existing_mp4_and_timeline_from_streamed_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            store=RecordingStore(root/'run.jsonl',started=10)
            raw=struct.pack('<BHHBBHHH',1,2,2,2,2,1,1,1)+struct.pack('<H',0)+b'\x7f'*12
            store.append({'t':0,'d':base64.b64encode(zlib.compress(raw)).decode(),'k':1})
            store.append({'t':.1,'act':1,'label':'KEY right'})
            store.append({'t':.1,'key':'right','down':True})
            store.append({'t':.2,'key':'right','down':False})
            snapshot=Snapshot(**store.pin())
            try:
                out=root/'run.mp4'
                result=render({'events':snapshot,'duration':snapshot.duration},out,'test',timeline_extra={'id':'run'})
                self.assertIn(b'ftyp',out.read_bytes()[:40])
                timeline=json.loads(Path(result['timeline']).read_text())
                self.assertEqual(timeline['id'],'run')
                self.assertEqual(timeline['marks'],[{'n':1,'t':0.0,'do':'KEY right','keys':[['right',.1]]}])
            finally:
                snapshot.close();store.close()
