import base64
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from PIL import Image

from activity import ActivityStore
from activity_thumbnails import RecordedScreen
from import_activity import import_recording


def frame(color, key=True, width=2, height=1):
    header = struct.pack('<BHHBBHHH', int(key), width, height, 1, 1, width, height, width*height)
    payload = header + struct.pack(f'<{width*height}H', *range(width*height)) + bytes(color) * width*height
    return base64.b64encode(zlib.compress(payload)).decode()


def image_pixel(row):
    return Image.open(io.BytesIO(base64.b64decode(row['thumb'].split(',')[1]))).convert('RGB').getpixel((0,0))


class ThumbnailImportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.recording = Path(tmp.name)/'recording.jsonl'
        self.history = Path(tmp.name)/'activity.json'

    def run_import(self, events):
        self.recording.write_text('\n'.join(json.dumps(x) for x in [{'started':1700000000}, *events])+'\n')
        import_recording(self.recording,self.history)
        return ActivityStore(self.history).load()

    def test_frame_after_marker_with_same_timestamp_is_excluded(self):
        rows=self.run_import([{'t':1,'d':frame((250,0,0)),'k':1},
                              {'t':1,'act':'GET','who':'agent','on':'screen'},
                              {'t':1,'d':frame((0,0,250)),'k':1}])
        red,green,blue=image_pixel(rows[0])
        self.assertGreater(red,200)
        self.assertLess(blue,30)
        self.assertEqual(rows[0]['thumb_source'],'recording')
        self.assertEqual(rows[0]['thumb_at'],1700000001)

    def test_same_timestamp_actions_remain_distinct_and_reimport_is_stable(self):
        events=[{'t':1,'d':frame((250,0,0)),'k':1},
                {'t':1,'act':'GET','who':'agent','on':'screen'},
                {'t':1,'act':'GET','who':'agent','on':'screen'}]
        rows=self.run_import(events)
        self.assertEqual(len(rows),2)
        self.assertNotEqual(rows[0]['recording_offset'], rows[1]['recording_offset'])
        import_recording(self.recording,self.history)
        self.assertEqual(ActivityStore(self.history).load(),rows)

    def test_no_keyframe_false_keyframe_and_corrupt_delta_never_fabricate_picture(self):
        for frames in [[{'t':1,'d':frame((1,2,3),key=False)}],
                       [{'t':1,'d':frame((1,2,3),key=False),'k':1}],
                       [{'t':1,'d':frame((1,2,3)),'k':1},{'t':2,'d':'bad'}],
                       [{'t':1,'d':frame((1,2,3)),'k':1},{'t':2,'d':frame((1,2,3),key=False,width=3)}]]:
            with self.subTest(frames=frames):
                self.history.unlink(missing_ok=True)
                rows=self.run_import(frames+[{'t':3,'act':'GET'}])
                self.assertNotIn('thumb',rows[0])

    def test_valid_keyframe_handles_size_change(self):
        rows=self.run_import([{'t':1,'d':frame((250,0,0)),'k':1},
                              {'t':2,'d':frame((0,0,250),width=3),'k':1},
                              {'t':3,'act':'GET'}])
        self.assertGreater(image_pixel(rows[0])[2],200)

    def test_reimport_adds_missing_thumbnails_and_keeps_existing_original(self):
        rows=self.run_import([{'t':1,'d':frame((250,0,0)),'k':1},{'t':2,'act':'GET'}])
        rows[0].pop('thumb')
        ActivityStore(self.history).save(rows)
        import_recording(self.recording,self.history)
        rows=ActivityStore(self.history).load()
        self.assertIn('thumb',rows[0])
        original=rows[0]['thumb']
        rows[0].pop('thumb_source');rows[0].pop('thumb_at')
        ActivityStore(self.history).save(rows)
        import_recording(self.recording,self.history)
        row=ActivityStore(self.history).load()[0]
        self.assertEqual(row['thumb'],original)
        self.assertNotIn('thumb_source',row)

    def test_only_latest_forty_gets_receive_previews(self):
        events=[{'t':0,'d':frame((200,0,0)),'k':1}]
        events += [{'t':i,'act':'GET'} for i in range(1,51)]
        rows=self.run_import(events)
        self.assertEqual(sum('thumb' in r for r in rows),40)
        self.assertNotIn('thumb',rows[9])
        self.assertIn('thumb',rows[10])

    def test_oversized_geometry_is_rejected_before_allocation(self):
        payload=struct.pack('<BHHBBHHH',1,65535,65535,1,1,65535,65535,0)
        encoded=base64.b64encode(zlib.compress(payload)).decode()
        with self.assertRaises(ValueError):RecordedScreen().apply(encoded)


if __name__=='__main__':unittest.main()
