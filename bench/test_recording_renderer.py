import base64
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'server'))
from recording import Snapshot
from recording_store import RecordingStore
import render as renderer
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
                self.assertIsNotNone(result['poster'])
                self.assertTrue(Path(result['poster']).read_bytes().startswith(b'\xff\xd8'))
                timeline=json.loads(Path(result['timeline']).read_text())
                self.assertEqual(timeline['id'],'run')
                self.assertEqual(timeline['marks'],[{'n':1,'t':0.0,'do':'KEY right','keys':[['right',.1]]}])
            finally:
                snapshot.close();store.close()


class RendererMarkerCompatibilityTest(unittest.TestCase):
    def rendered_annotations(self, events):
        """Exercise the actual streamed render loop, without running ffmpeg."""
        labels = []
        original_draw = renderer.ImageDraw.Draw

        def draw(image):
            result = original_draw(image)
            original_text = result.text

            def text(position, value, *args, **kwargs):
                labels.append(value)
                return original_text(position, value, *args, **kwargs)

            result.text = text
            return result

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RecordingStore(root / 'run.jsonl', started=10)
            raw = struct.pack('<BHHBBHHH', 1, 2, 2, 2, 2, 1, 1, 1) + struct.pack('<H', 0) + b'\x7f' * 12
            store.append({'t': 0, 'd': base64.b64encode(zlib.compress(raw)).decode(), 'k': 1})
            for event in events:
                store.append(event)
            original = store.path.read_bytes()
            snapshot = Snapshot(**store.pin())
            try:
                with mock.patch.object(renderer.subprocess, 'Popen') as process, \
                     mock.patch.object(renderer.subprocess, 'run'), \
                     mock.patch.object(renderer.ImageDraw, 'Draw', side_effect=draw):
                    process.return_value.wait.return_value = 0
                    result = render({'events': snapshot, 'duration': .8}, root / 'fake.mp4', speed=1)
                    self.assertTrue(process.return_value.stdin.write.called)
                self.assertEqual(store.path.read_bytes(), original)
                return json.loads(Path(result['timeline']).read_text())['marks'], labels
            finally:
                snapshot.close()
                store.close()

    def test_string_actions_have_viewer_ordinals_and_descriptive_labels(self):
        marks, labels = self.rendered_annotations([
            {'t': .1, 'act': 'KEY', 'who': 'agent', 'on': 'right', 'history': 1},
            {'t': .1, 'key': 'right', 'down': True},
            {'t': .2, 'key': 'right', 'down': False},
            {'t': .3, 'act': 'GET', 'who': 'agent', 'on': 'screen', 'history': 1},
            {'t': .4, 'act': 'WAIT', 'who': 'agent', 'on': '1500ms', 'history': 1},
        ])
        self.assertEqual(marks, [
            {'n': 1, 't': 0.0, 'do': 'KEY right', 'keys': [['right', .1]]},
            {'n': 2, 't': .2, 'do': 'GET screen', 'keys': []},
            {'n': 3, 't': .3, 'do': 'WAIT 1500ms', 'keys': []},
        ])
        self.assertEqual({value for value in labels if value.startswith('#')}, {'#1', '#2', '#3'})

    def test_numbered_benchmark_actions_and_labels_are_unchanged(self):
        marks, labels = self.rendered_annotations([
            {'t': .1, 'act': 7, 'label': 'KEY right'},
            {'t': .1, 'key': 'right', 'down': True},
            {'t': .2, 'key': 'right', 'down': False},
            {'t': .3, 'act': 9, 'label': 'WAIT 1000ms'},
        ])
        self.assertEqual(marks, [
            {'n': 7, 't': 0.0, 'do': 'KEY right', 'keys': [['right', .1]]},
            {'n': 9, 't': .2, 'do': 'WAIT 1000ms', 'keys': []},
        ])
        self.assertEqual({value for value in labels if value.startswith('#')}, {'#7', '#9'})
