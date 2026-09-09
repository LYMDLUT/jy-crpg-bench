"""Sequential export pictures retain the random-access history contract."""
import base64
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zlib

from PIL import Image

from activity_thumbnails import RecordedScreen
from history_frames import iter_frames, render_frame
from history_index import HistoryIndex


def frame(when, color, key=False):
    tiles = [0, 1] if key else [1]
    raw = struct.pack('<BHHBBHHH', int(key), 2, 1, 1, 1, 2, 1, len(tiles))
    raw += struct.pack('<' + 'H' * len(tiles), *tiles)
    raw += bytes(color) * len(tiles)
    return {'t': when, 'd': base64.b64encode(zlib.compress(raw)).decode()}


def action(when, act='GET', **fields):
    return dict(t=when, act=act, who='agent', history=1, **fields)


class HistoryFrameStreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def make_index(self, events):
        path = Path(self.tmp.name) / 'recording.jsonl'
        data = json.dumps({'version': 1, 'started': 100}).encode() + b'\n'
        self.offsets, self.ends = [], []
        for event in events:
            self.offsets.append(len(data))
            data += event if isinstance(event, bytes) else json.dumps(event).encode() + b'\n'
            self.ends.append(len(data))
        path.write_bytes(data)
        index = HistoryIndex(dict(path=path, fd=os.open(path, os.O_RDONLY), end=len(data)))
        self.addCleanup(index.close)
        index.build()
        return index

    def assert_matches(self, index, steps=None):
        compared = []
        for step, image, when, end in iter_frames(index, steps):
            expected, expected_when = render_frame(index, step)
            with Image.open(io.BytesIO(expected)) as reference:
                self.assertEqual(image.size, reference.size)
                self.assertEqual(image.tobytes(), reference.tobytes())
            self.assertEqual(when, expected_when)
            self.assertIn(end, self.ends)
            self.assertLessEqual(end, step.get('_end', index.source.end))
            compared.append((step, image.copy(), when, end))
        return compared

    def test_default_iterator_preserves_every_private_step_field_and_picture(self):
        index = self.make_index([
            frame(10, (1, 2, 3), True),
            {'t': 10.1, 'key': 'enter', 'down': True, 'who': 'agent'},
            frame(10.4, (4, 5, 6)), action(11, 'KEY', on='up'),
            frame(11.8, (7, 8, 9)),
            {'t': 12.1, 'act': 9, 'label': 'KEY down', 'who': 'agent'},
            frame(12.2, (10, 11, 12)), action(12.5, 'KEY', phase='after'),
            action(12.5, 'KEY', ok=False, detail='busy'),
            frame(12.5, (13, 14, 15)), action(12.5), action(12.6),
        ])
        actual = self.assert_matches(index)
        self.assertEqual(len(actual), index.steps)
        for number, (step, _, _, _) in enumerate(actual):
            self.assertEqual(step, index.step(number))
            self.assertIn('_offset', step)
            self.assertIn('_cutoff', step)
        self.assertTrue(any(row[0].get('ok') is False for row in actual))

    def test_equal_timestamps_and_submillisecond_cutoffs_obey_byte_boundaries(self):
        index = self.make_index([
            frame(10, (1, 1, 1), True), action(11),
            frame(11, (2, 2, 2)), action(11),
            frame(10.5, (3, 3, 3)), action(11, 'KEY', ok=False),
            frame(11, (4, 4, 4)), action(11, 'KEY', phase='after'),
            frame(11.0004, (5, 5, 5)), action(11.0004),
            frame(11.0004, (6, 6, 6)), action(11.0004),
        ])
        actual = self.assert_matches(index)
        self.assertEqual([image.getpixel((1, 0))[0] for _, image, _, _ in actual],
                         [1, 2, 3, 4, 5, 6])
        self.assertEqual([end for _, _, _, end in actual], self.ends[::2])
        self.assertEqual(actual[-1][0]['cutoff'], 1)
        self.assertEqual(actual[-1][0]['_cutoff'], 11.0004)

    def test_time_and_offset_rewinds_reconstruct_instead_of_reusing_future_pixels(self):
        index = self.make_index([
            frame(0, (1, 1, 1), True), frame(1, (2, 2, 2)),
            frame(2, (3, 3, 3)), frame(2, (4, 4, 4)), action(3),
        ])
        bounds = [(2, index.source.end), (1, index.source.end),
                  (2, self.offsets[3]), (2, self.offsets[2]),
                  (2, index.source.end)]
        steps = [dict(cutoff=t, _cutoff=t, _end=end, custom=n)
                 for n, (t, end) in enumerate(bounds)]
        actual = self.assert_matches(index, iter(steps))
        self.assertEqual([image.getpixel((1, 0))[0] for _, image, _, _ in actual],
                         [4, 2, 3, 2, 4])
        for step, row in zip(steps, actual):
            self.assertIs(step, row[0])

    def test_nonmonotonic_source_times_use_the_global_anchor_clock(self):
        index = self.make_index([
            frame(10, (1, 1, 1), True), action(11),
            {'t': 40, 'who': 'web'}, frame(12, (2, 2, 2), True),
            frame(1, (3, 3, 3)), action(2),
            frame(41, (4, 4, 4)), action(4),
        ])
        actual = self.assert_matches(index)
        self.assertEqual([when for _, _, when, _ in actual], [10, 40, 41])
        self.assertEqual([image.getpixel((1, 0))[0] for _, image, _, _ in actual], [1, 3, 4])

    def test_each_delta_is_decoded_once_for_dense_action_history(self):
        events = [frame(0, (1, 1, 1), True), action(.01)]
        for n in range(1, 81):
            events.extend((frame(n, (n, 0, 0)), action(n + .01)))
        index = self.make_index(events)
        apply = RecordedScreen.apply
        calls = []

        def counted(screen, encoded):
            calls.append(encoded)
            return apply(screen, encoded)

        with mock.patch.object(RecordedScreen, 'apply', counted), \
             mock.patch.object(index.source, 'lines', wraps=index.source.lines) as reads:
            streamed = [(step, image.tobytes()) for step, image, _, _ in iter_frames(index)]
        self.assertEqual(len(calls), 81)
        self.assertEqual(reads.call_count, 1)
        calls.clear()
        with mock.patch.object(RecordedScreen, 'apply', counted):
            for step, pixels in streamed:
                data, _ = render_frame(index, step)
                with Image.open(io.BytesIO(data)) as image:
                    self.assertEqual(image.tobytes(), pixels)
        self.assertEqual(len(calls), 81 * 82 // 2)

    def test_a_nearer_complete_frame_skips_idle_deltas_and_prior_damage(self):
        events = [frame(0, (1, 1, 1), True), action(.1)]
        events += [frame(n, (n % 256, 0, 0)) for n in range(1, 201)]
        events += [b'not-json\n', {'t': 201, 'd': 'broken'},
                   frame(202, (9, 8, 7), True), action(202.1)]
        index = self.make_index(events)
        apply = RecordedScreen.apply
        calls = []

        def counted(screen, encoded):
            calls.append(encoded)
            return apply(screen, encoded)

        with mock.patch.object(RecordedScreen, 'apply', counted):
            actual = [(step, image.copy(), when, end)
                      for step, image, when, end in iter_frames(index)]
        self.assertEqual(len(calls), 2)
        self.assertEqual(actual[-1][1].getpixel((1, 0)), (9, 8, 7))
        self.assertEqual(actual[-1][3], self.ends[-2])
        self.assert_matches(index)

    def test_unchanged_actions_share_the_last_frame_end(self):
        index = self.make_index([
            frame(0, (1, 1, 1), True), action(.1), action(.2),
            {'t': .3, 'key': 'up', 'down': False}, action(.4),
            frame(.5, (2, 2, 2)), action(.6),
        ])
        actual = self.assert_matches(index)
        self.assertEqual([end for _, _, _, end in actual],
                         [self.ends[0]] * 3 + [self.ends[5]])

    def test_repeated_cutoffs_do_not_reparse_the_pending_future_frame(self):
        index = self.make_index([
            frame(0, (1, 1, 1), True), frame(2, (2, 2, 2)), action(3),
        ])
        steps = [dict(cutoff=1) for _ in range(40)]
        with mock.patch('history_frames.json.loads', wraps=json.loads) as loads:
            self.assertEqual(len(list(iter_frames(index, steps))), 40)
        self.assertEqual(loads.call_count, 2)

    def test_damaged_requested_window_has_the_same_error_as_individual_render(self):
        for damaged, message in [(b'not-json\n', 'damaged recording'),
                                 ({'t': 1, 'd': 'broken'}, 'damaged frame')]:
            with self.subTest(damaged=damaged):
                # Each source needs its own inode for the disposable index.
                folder = Path(self.tmp.name) / 'recording.jsonl'
                folder.unlink(missing_ok=True)
                index = self.make_index([
                    frame(0, (1, 1, 1), True), action(.1), damaged, action(2),
                ])
                rows = iter_frames(index)
                next(rows)
                with self.assertRaisesRegex(ValueError, message):
                    next(rows)
                with self.assertRaisesRegex(ValueError, message):
                    render_frame(index, index.step(1))
                index.close()

    def test_empty_and_cancelled_iterators_do_not_decode(self):
        index = self.make_index([frame(0, (1, 1, 1), True)])
        self.assertEqual(list(iter_frames(index)), [])
        index.cancelled.set()
        with mock.patch.object(RecordedScreen, 'apply', side_effect=AssertionError('decoded')):
            self.assertEqual(list(iter_frames(index, [dict(cutoff=0)])), [])

    def test_cancellation_during_a_window_stops_before_yielding_partial_image(self):
        index = self.make_index([
            frame(0, (1, 1, 1), True), frame(1, (2, 2, 2)), action(2),
        ])
        apply = RecordedScreen.apply

        def cancelled(screen, encoded):
            apply(screen, encoded)
            index.cancelled.set()

        with mock.patch.object(RecordedScreen, 'apply', cancelled):
            self.assertEqual(list(iter_frames(index)), [])


if __name__ == '__main__':
    unittest.main()
