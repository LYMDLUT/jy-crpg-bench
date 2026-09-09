"""Disk history is complete, paged, pinned, and independent of the live tail."""
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest import mock
import zlib

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from history_frames import complete_frame
from history_index import HistoryIndex, INDEX_LOCK, normalize
from recording_store import RecordingStore
from saved_history import SavedHistory


def frame(when, color, key=True, marked=None):
    tiles = [0, 1] if key else [1]
    data = struct.pack('<BHHBBHHH', int(key), 2, 1, 1, 1, 2, 1, len(tiles))
    data += struct.pack('<' + 'H' * len(tiles), *tiles)
    data += bytes(color) * len(tiles)
    event = {'t': when, 'd': base64.b64encode(zlib.compress(data)).decode()}
    if marked is not None:
        event['k'] = int(marked)
    return event


class SavedHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'recording.jsonl'
        self.store = RecordingStore(self.path, started=100)
        self.service = SavedHistory(self.store)
        self.client = await self.client_for(self.service)

    async def client_for(self, service, enabled=True):
        app = web.Application()
        service.install(app, enabled=enabled)
        async def ping(request):
            return web.Response(text='alive')
        app.router.add_get('/ping', ping)
        client = TestClient(TestServer(app))
        await client.start_server()
        return client

    async def asyncTearDown(self):
        await self.client.close()
        self.store.close()
        self.temp.cleanup()

    def write(self, count=350):
        for number in range(count):
            self.store.append(frame(number * 2, (number % 256, number // 256, 7)))
            self.store.append({'t': number * 2 + .1, 'act': 'GET', 'who': 'agent', 'on': 'screen'})

    async def opened(self, recording=None):
        params = {} if recording is None else {'recording': recording}
        response = await self.client.get('/api/replay', params=params)
        self.assertIn(response.status, (200, 202))
        meta = await response.json()
        for _ in range(500):
            if not meta.get('indexing'):
                return meta
            await asyncio.sleep(.005)
            response = await self.client.get('/api/replay/' + meta['token'])
            self.assertIn(response.status, (200, 202), await response.text())
            meta = await response.json()
        self.fail('history indexing did not finish')

    async def picture(self, token, number):
        response = await self.client.get(f'/api/replay/{token}/frame?step={number}')
        self.assertEqual(response.status, 200, await response.text() if response.status != 200 else '')
        self.assertEqual(response.headers['X-Replay-Step'], str(number))
        self.assertEqual(response.headers['X-Replay-Source'], 'recording')
        image = Image.open(io.BytesIO(await response.read()))
        image.load()
        return image

    async def test_entire_history_is_paged_and_old_middle_latest_images_are_correct(self):
        self.write()
        original = self.path.read_bytes()
        meta = await self.opened()
        self.assertEqual(meta['steps'], 350)
        self.assertEqual(meta['events'], 700)
        token = meta['token']
        response = await self.client.get(f'/api/replay/{token}/steps?start=128&count=999999')
        page = await response.json()
        self.assertEqual(page['total'], 350)
        self.assertEqual(len(page['steps']), 128)
        self.assertEqual(page['steps'][0]['t'], 256.1)
        self.assertFalse(any(key.startswith('_') for key in page['steps'][0]))
        # Include a backward jump after the latest image.
        for number in (0, 175, 349, 12):
            picture = await self.picture(token, number)
            self.assertEqual(picture.getpixel((0, 0)), (number % 256, number // 256, 7))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertLess(len(json.dumps(meta)), 2000)

    async def test_service_restart_restores_all_steps_and_index_is_incremental(self):
        self.write(310)
        first = await self.opened()
        index_path = self.service.states[first['token']]['index'].path
        await self.client.close()
        self.service = SavedHistory(self.store)
        self.client = await self.client_for(self.service)
        with mock.patch('history_index.complete_frame', side_effect=AssertionError('rescanned old payload')):
            second = await self.opened()
        self.assertEqual(second['steps'], 310)
        self.assertEqual(self.service.states[second['token']]['index'].path, index_path)
        self.assertEqual((await self.picture(second['token'], 0)).getpixel((0, 0)), (0, 0, 7))

    async def test_recorded_time_preserves_fraction_and_backward_time_without_changing_frames(self):
        original_times = [250.375123456789, 240.123456789012]
        for event in [frame(250.25, (10, 20, 30)),
                      {'t': original_times[0], 'act': 'GET', 'who': 'agent'},
                      frame(300.75, (40, 50, 60)),
                      {'t': original_times[1], 'act': 'GET', 'who': 'agent'}]:
            self.store.append(event)
        original = self.path.read_bytes()
        meta = await self.opened()
        page = await (await self.client.get(f'/api/replay/{meta["token"]}/steps')).json()
        self.assertEqual([step['recorded_t'] for step in page['steps']], original_times)
        self.assertEqual([step['t'] for step in page['steps']], [.125, 50.5])
        self.assertEqual([step['cutoff'] for step in page['steps']], [.125, 50.5])
        self.assertEqual((await self.picture(meta['token'], 0)).getpixel((0, 0)), (10, 20, 30))
        self.assertEqual((await self.picture(meta['token'], 1)).getpixel((0, 0)), (40, 50, 60))
        self.assertEqual(self.path.read_bytes(), original)

    async def test_v2_cache_backfills_only_action_offsets_in_small_reads_once(self):
        times = [51.1234567890123, 49.2345678901234]
        self.store.append(frame(50, (1, 2, 3)))
        for when in times:
            self.store.append({'t': when, 'act': 'GET', 'who': 'agent', 'history': 1,
                               'detail': 'long action ' * 150})
            large_frame = frame(60, (4, 5, 6))
            large_frame['padding'] = 'x' * (128 << 10)
            self.store.append(large_frame)
        original = self.path.read_bytes()
        first = HistoryIndex(self.store.pin())
        try:
            first.build()
            path = first.path
            cached_frames = first.db.execute('SELECT * FROM frames ORDER BY off').fetchall()
            cached_marks = first.db.execute('SELECT off,t,kind FROM marks ORDER BY off').fetchall()
            cached_state = first.db.execute('SELECT * FROM state').fetchall()
            rows = first.db.execute('SELECT off,data FROM marks').fetchall()
            for offset, payload in rows:
                data = json.loads(payload)
                del data['recorded_t']
                first.db.execute('UPDATE marks SET data=? WHERE off=?', (json.dumps(data), offset))
        finally:
            first.close()

        second = HistoryIndex(self.store.pin())
        try:
            with mock.patch('history_index.complete_frame', side_effect=AssertionError('frame rescanned')), \
                 mock.patch.object(second.source, 'lines', side_effect=AssertionError('source rescanned')), \
                 mock.patch('history_index.os.pread', wraps=os.pread) as reads:
                second.build()
            self.assertEqual(second.path, path)
            self.assertTrue(path.name.startswith('v2-'))
            self.assertEqual([step['recorded_t'] for step in second.page(0, 2)], times)
            self.assertEqual(second.db.execute('SELECT * FROM frames ORDER BY off').fetchall(), cached_frames)
            self.assertEqual(second.db.execute('SELECT off,t,kind FROM marks ORDER BY off').fetchall(), cached_marks)
            self.assertEqual(second.db.execute('SELECT * FROM state').fetchall(), cached_state)
            action_bounds = [(offset, offset + original[offset:].index(b'\n') + 1)
                             for offset, _ in rows]
            self.assertGreater(reads.call_count, 2)
            for call in reads.call_args_list:
                descriptor, size, offset = call.args
                self.assertEqual(descriptor, second.source.fd)
                self.assertLessEqual(size, 512)
                self.assertLessEqual(offset + size, second.source.end)
                self.assertTrue(any(begin <= offset < end for begin, end in action_bounds))
            self.assertLess(sum(call.args[1] for call in reads.call_args_list), 8192)
        finally:
            second.close()

        third = HistoryIndex(self.store.pin())
        try:
            with mock.patch.object(third.source, 'lines', side_effect=AssertionError('source rescanned')), \
                 mock.patch('history_index.os.pread', side_effect=AssertionError('action read twice')):
                third.build()
            self.assertEqual(third.path, path)
            self.assertEqual([step['recorded_t'] for step in third.page(0, 2)], times)
        finally:
            third.close()
        self.assertEqual(self.path.read_bytes(), original)

    async def test_cancelled_v2_backfill_rolls_back_already_updated_batches(self):
        self.write(260)
        original = self.path.read_bytes()
        first = HistoryIndex(self.store.pin())
        try:
            first.build()
            rows = first.db.execute('SELECT off,data FROM marks').fetchall()
            for offset, payload in rows:
                data = json.loads(payload)
                del data['recorded_t']
                first.db.execute('UPDATE marks SET data=? WHERE off=?', (json.dumps(data), offset))
        finally:
            first.close()

        second = HistoryIndex(self.store.pin())
        read_time = second._recorded_time
        count = 0

        def cancel_during_second_batch(offset):
            nonlocal count
            count += 1
            if count == 258:
                second.cancelled.set()
            return read_time(offset)

        try:
            with mock.patch.object(second, '_recorded_time', side_effect=cancel_during_second_batch):
                second.build()
            self.assertEqual(count, 258)
            self.assertFalse(second.db.in_transaction)
            self.assertEqual(second.steps, 0)
            for (payload,) in second.db.execute('SELECT data FROM marks'):
                self.assertNotIn('recorded_t', json.loads(payload))
        finally:
            second.close()
        self.assertEqual(self.path.read_bytes(), original)

    async def test_cached_action_read_obeys_line_limit_and_pinned_end(self):
        self.store.append(frame(0, (1, 2, 3)))
        action_offset = self.store.committed_size
        self.store.append({'t': 1.123456789, 'act': 'GET', 'who': 'agent', 'detail': 'x' * 1024})
        index = HistoryIndex(self.store.pin())
        pinned_end = index.source.end
        self.store.append({'t': 2, 'act': 'GET', 'who': 'agent'})
        original = self.path.read_bytes()
        try:
            with mock.patch('history_index.MAX_LINE', 64), \
                 mock.patch('history_index.os.pread', wraps=os.pread) as reads:
                with self.assertRaisesRegex(ValueError, 'event is too large'):
                    index._recorded_time(action_offset)
            self.assertEqual(sum(call.args[1] for call in reads.call_args_list), 65)
            with mock.patch('history_index.os.pread', side_effect=AssertionError('read beyond pinned end')):
                with self.assertRaisesRegex(ValueError, 'incomplete trailing event'):
                    index._recorded_time(pinned_end)
        finally:
            index.close()
        self.assertEqual(self.path.read_bytes(), original)

    async def test_open_snapshot_survives_append_and_reset(self):
        self.write(4)
        old = await self.opened()
        self.store.append(frame(20, (255, 0, 0)))
        self.store.append({'t': 20.1, 'act': 'GET', 'who': 'agent'})
        self.assertEqual((await self.client.get(f'/api/replay/{old["token"]}')).status, 200)
        self.assertEqual(self.service.states[old['token']]['index'].steps, 4)
        archive = self.store.reset(200)
        self.store.append(frame(0, (0, 255, 0)))
        self.store.append({'t': .1, 'act': 'GET', 'who': 'agent'})
        self.assertTrue(archive.is_file())
        self.assertEqual((await self.picture(old['token'], 3)).getpixel((0, 0)), (3, 0, 7))
        new = await self.opened()
        self.assertEqual(new['steps'], 1)
        self.assertEqual((await self.picture(new['token'], 0)).getpixel((0, 0)), (0, 255, 0))

    async def test_archive_provider_pins_original_history_across_current_reset(self):
        self.write(3)
        last_timestamp = self.store.last_timestamp
        archive = self.store.reset(200)
        original = archive.read_bytes()
        self.store.append(frame(0, (255, 0, 0)))
        self.store.append({'t': .1, 'act': 'GET', 'who': 'agent'})

        def pin_recording(name):
            if name == 'current':
                return self.store.pin()
            self.assertEqual(name, archive.name)
            descriptor = os.open(archive, os.O_RDONLY)
            return {'path': archive, 'fd': descriptor,
                    'end': os.fstat(descriptor).st_size,
                    'last_timestamp': last_timestamp}

        provider = mock.Mock(side_effect=pin_recording)
        await self.client.close()
        self.service = SavedHistory(self.store, pin_provider=provider)
        self.client = await self.client_for(self.service)
        saved = await self.opened(archive.name)
        provider.assert_called_once_with(archive.name)
        self.assertEqual(saved['started'], 100)
        self.assertEqual(saved['steps'], 3)
        self.assertEqual(saved['events'], 6)

        self.store.reset(300)
        self.store.append(frame(0, (0, 0, 255)))
        self.store.append({'t': .1, 'act': 'GET', 'who': 'agent'})
        current = await self.opened()
        self.assertEqual(current['started'], 300)
        self.assertEqual(current['steps'], 1)
        self.assertEqual((await self.picture(current['token'], 0)).getpixel((0, 0)), (0, 0, 255))

        info = await (await self.client.get('/api/replay/' + saved['token'])).json()
        self.assertEqual(info, saved)
        page = await (await self.client.get(f'/api/replay/{saved["token"]}/steps')).json()
        self.assertEqual(page['total'], 3)
        self.assertEqual([step['t'] for step in page['steps']], [.1, 2.1, 4.1])
        for number in (2, 0):
            self.assertEqual((await self.picture(saved['token'], number)).getpixel((0, 0)), (number, 0, 7))
        self.assertEqual(provider.call_args_list, [mock.call(archive.name), mock.call('current')])

        reopened = await self.opened(archive.name)
        self.assertEqual(reopened['started'], 100)
        self.assertEqual(reopened['steps'], 3)
        self.assertEqual((await self.picture(reopened['token'], 1)).getpixel((0, 0)), (1, 0, 7))
        self.assertEqual(archive.read_bytes(), original)

    async def test_invalid_archive_names_are_rejected_before_calling_provider(self):
        provider = mock.Mock(side_effect=AssertionError('invalid name reached provider'))
        await self.client.close()
        self.service = SavedHistory(self.store, pin_provider=provider)
        self.client = await self.client_for(self.service)
        name = '20260909-120000-abcdef123456.jsonl'
        for invalid in ('', '../' + name, '/etc/passwd', 'recordings/' + name,
                        name + '/..', name + '\n', name + '\x00',
                        name.replace('abcdef', 'ABCDEF'), name.replace('abcdef', 'abcdeg'),
                        name.replace('123456', '12345'), name.replace('20260909', '２０２６０９０９')):
            with self.subTest(recording=invalid):
                response = await self.client.get('/api/replay', params={'recording': invalid})
                self.assertEqual(response.status, 404)
        provider.assert_not_called()
        self.assertFalse(self.service.states)

    async def test_missing_archive_from_provider_returns_not_found(self):
        provider = mock.Mock(side_effect=FileNotFoundError('archive has been removed'))
        await self.client.close()
        self.service = SavedHistory(self.store, pin_provider=provider)
        self.client = await self.client_for(self.service)
        name = '20260909-120000-abcdef123456.jsonl'
        response = await self.client.get('/api/replay', params={'recording': name})
        self.assertEqual(response.status, 404)
        provider.assert_called_once_with(name)
        self.assertFalse(self.service.states)

    async def test_get_never_includes_a_frame_after_its_marker_at_the_same_time(self):
        self.store.append(frame(0, (10, 20, 30)))
        self.store.append({'t': 1, 'act': 'GET', 'who': 'agent'})
        self.store.append(frame(1, (90, 80, 70)))
        meta = await self.opened()
        self.assertEqual((await self.picture(meta['token'], 0)).getpixel((0, 0)), (10, 20, 30))

    async def test_legacy_and_numbered_keys_settle_but_explicit_after_does_not(self):
        for event in [frame(0, (1, 1, 1)),
                      {'t': .1, 'key': 'enter', 'down': True, 'who': 'agent'},
                      frame(.4, (2, 2, 2)),
                      {'t': 1, 'act': 'KEY', 'who': 'agent', 'on': 'up'},
                      {'t': 1.01, 'key': 'up', 'down': True, 'who': 'agent'},
                      frame(1.8, (3, 3, 3)),
                      {'t': 2.1, 'act': 9, 'label': 'KEY down', 'who': 'agent'},
                      frame(2.2, (4, 4, 4)),
                      {'t': 2.5, 'act': 'KEY', 'who': 'agent', 'phase': 'after'},
                      frame(2.7, (5, 5, 5))]:
            self.store.append(event)
        meta = await self.opened()
        self.assertEqual(meta['steps'], 3)
        # The phase=after mark collapses with the previous equal-cutoff step.
        for number, color in enumerate((2, 3, 4)):
            self.assertEqual((await self.picture(meta['token'], number)).getpixel((0, 0)), (color,) * 3)

    async def test_rich_markers_keep_web_and_failures_without_changing_legacy_web_filter(self):
        for event in [frame(0, (1, 2, 3)),
                      {'t': .1, 'act': 'GET', 'who': 'web'},
                      {'t': .2, 'act': 'KEY', 'who': 'web', 'history': 1, 'ok': False, 'phase': 'after'},
                      {'t': .2, 'act': 'GET', 'who': 'agent', 'history': 1}]:
            self.store.append(event)
        meta = await self.opened()
        self.assertEqual(meta['steps'], 2)
        page = await (await self.client.get(f'/api/replay/{meta["token"]}/steps')).json()
        self.assertEqual(page['steps'][0]['who'], 'web')
        self.assertFalse(page['steps'][0]['ok'])

    async def test_raw_keys_at_the_first_action_timestamp_are_not_double_counted(self):
        for event in [frame(0, (1, 2, 3)),
                      {'t': 1, 'key': 'enter', 'down': True, 'who': 'agent'},
                      {'t': 1, 'act': 'KEY', 'who': 'agent', 'on': 'enter'},
                      frame(1.5, (4, 5, 6))]:
            self.store.append(event)
        meta = await self.opened()
        self.assertEqual(meta['steps'], 1)

    async def test_failed_key_uses_the_picture_before_the_marker(self):
        for event in [frame(0, (255, 0, 0)),
                      {'t': 1, 'act': 'KEY', 'who': 'web', 'on': 'up',
                       'detail': 'busy', 'ok': False, 'history': 1},
                      # Millisecond-rounded times may be equal; neither this
                      # later frame nor another actor's result belongs to the
                      # rejected input.
                      frame(1, (0, 255, 0)), frame(1.5, (0, 0, 255))]:
            self.store.append(event)
        meta = await self.opened()
        page = await (await self.client.get(f'/api/replay/{meta["token"]}/steps')).json()
        self.assertFalse(page['steps'][0]['ok'])
        self.assertEqual(page['steps'][0]['detail'], 'busy')
        self.assertEqual(page['steps'][0]['cutoff'], 1)
        self.assertEqual((await self.picture(meta['token'], 0)).getpixel((0, 0)), (255, 0, 0))

    async def test_unknown_legacy_result_is_not_reported_as_a_failed_action(self):
        for result in (None, '', 0, 'unknown'):
            _, mark = normalize({'act': 'KEY', 'who': 'agent', 'ok': result})
            self.assertIsNone(mark['ok'])

    async def test_version_two_rebuilds_unknown_results_without_touching_old_index_or_source(self):
        for event in [frame(0, (255, 0, 0)),
                      {'t': 1, 'act': 'KEY', 'who': 'agent', 'ok': None, 'history': 1},
                      frame(1.5, (0, 0, 255))]:
            self.store.append(event)
        source = self.path.read_bytes()

        def old_normalize(event):
            result = normalize(event)
            if result and 'ok' in result[1]:
                result[1]['ok'] = bool(event['ok'])
            return result

        with mock.patch('history_index.SCHEMA', 1), mock.patch('history_index.normalize', old_normalize):
            first = await self.opened()
        old_index = self.service.states[first['token']]['index']
        old_path = old_index.path
        self.assertIs(old_index.step(0)['ok'], False)
        await self.client.delete('/api/replay/' + first['token'])
        old_bytes = old_path.read_bytes()

        second = await self.opened()
        new_index = self.service.states[second['token']]['index']
        self.assertNotEqual(new_index.path, old_path)
        self.assertTrue(new_index.path.name.startswith('v2-'))
        self.assertIsNone(new_index.step(0)['ok'])
        self.assertEqual((await self.picture(second['token'], 0)).getpixel((0, 0)), (0, 0, 255))
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.assertEqual(self.path.read_bytes(), source)

    async def test_false_key_marker_is_not_an_anchor_and_unmarked_whole_frame_is(self):
        self.store.append(frame(0, (10, 10, 10), marked=False))
        partial = frame(1, (20, 20, 20), key=False, marked=True)
        self.assertFalse(complete_frame(partial))
        self.store.append(partial)
        self.store.append({'t': 1.1, 'act': 'GET', 'who': 'agent'})
        meta = await self.opened()
        image = await self.picture(meta['token'], 0)
        self.assertEqual(image.getpixel((0, 0)), (10, 10, 10))
        self.assertEqual(image.getpixel((1, 0)), (20, 20, 20))

    async def test_damaged_frame_returns_clear_error_and_preserves_source(self):
        self.store.append(frame(0, (1, 2, 3)))
        self.store.append({'t': 1, 'd': 'broken', 'k': 1})
        self.store.append({'t': 1.1, 'act': 'GET', 'who': 'agent'})
        original = self.path.read_bytes()
        meta = await self.opened()
        response = await self.client.get(f'/api/replay/{meta["token"]}/frame?step=0')
        self.assertEqual(response.status, 422)
        self.assertIn('damaged frame', await response.text())
        self.assertEqual(self.path.read_bytes(), original)

    async def test_malformed_line_does_not_hide_later_intact_pictures_or_change_bytes(self):
        self.store.append(frame(0, (1, 2, 3)))
        os.write(self.store.fd, b'not-json\n')
        self.store.append({'t': 1, 'act': 'GET', 'who': 'agent'})
        self.store.append(frame(2, (4, 5, 6)))
        self.store.append({'t': 2.1, 'act': 'GET', 'who': 'agent'})
        original = self.path.read_bytes()
        meta = await self.opened()
        self.assertEqual(meta['steps'], 2)
        self.assertEqual(meta['damaged_lines'], 1)
        self.assertEqual((await self.client.get(f'/api/replay/{meta["token"]}/frame?step=0')).status, 422)
        self.assertEqual((await self.picture(meta['token'], 1)).getpixel((0, 0)), (4, 5, 6))
        self.assertEqual(self.path.read_bytes(), original)

    async def test_uncommitted_tail_is_not_part_of_the_snapshot(self):
        self.write(2)
        original_end = self.store.committed_size
        os.write(self.store.fd, b'{"t":999,"d":"incomplete')
        meta = await self.opened()
        self.assertEqual(meta['steps'], 2)
        self.assertEqual(self.service.states[meta['token']]['index'].source.end, original_end)
        self.assertEqual((await self.picture(meta['token'], 1)).getpixel((0, 0)), (1, 0, 7))

    async def test_reader_cap_refuses_instead_of_evicting_and_close_releases_descriptors(self):
        self.write(2)
        first = await self.opened()
        first_index = self.service.states[first['token']]['index']
        others = [await self.opened() for _ in range(self.service.MAX_OPEN - 1)]
        self.assertEqual(len(self.service.states), self.service.MAX_OPEN)
        # A reader past the cap is refused; the readers already open keep playing.
        self.assertEqual((await self.client.get('/api/replay')).status, 429)
        self.assertIn((await self.client.get('/api/replay/' + first['token'])).status, (200, 202))
        self.assertFalse(first_index.closed)
        second_fd = self.service.states[others[0]['token']]['index'].source.fd
        await self.client.delete('/api/replay/' + others[0]['token'])
        with self.assertRaises(OSError):
            os.fstat(second_fd)
        self.assertEqual(len(self.service.states), self.service.MAX_OPEN - 1)
        # An idle reader expires and releases its handle.
        self.service.states[others[1]['token']]['used'] = time.monotonic() - self.service.TTL - 1
        self.assertEqual((await self.client.get('/api/replay/' + others[1]['token'])).status, 410)
        self.assertNotIn(others[1]['token'], self.service.states)

    async def test_cancelling_an_indexing_reader_does_not_block_the_event_loop(self):
        self.write(2)
        INDEX_LOCK.acquire()
        try:
            response = await self.client.get('/api/replay')
            self.assertEqual(response.status, 202)
            meta = await response.json()
            state = self.service.states[meta['token']]
            await asyncio.sleep(.02)
            self.assertEqual(await (await self.client.get('/ping')).text(), 'alive')
            await self.client.delete('/api/replay/' + meta['token'])
            self.assertTrue(state['index'].closed)
            self.assertTrue(state['task'].done())
        finally:
            INDEX_LOCK.release()

    async def test_shutdown_waits_for_worker_before_closing_snapshot(self):
        self.write(2)
        INDEX_LOCK.acquire()
        try:
            response = await self.client.get('/api/replay')
            meta = await response.json()
            state = self.service.states[meta['token']]
            descriptor = state['index'].source.fd
            await asyncio.sleep(.02)
            await self.client.close()
            self.assertTrue(state['task'].done())
            self.assertTrue(state['index'].closed)
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        finally:
            INDEX_LOCK.release()

    async def test_invalid_paths_ranges_and_disabled_benchmark_have_no_access(self):
        self.write(2)
        for path in ('../recording.jsonl', '/etc/passwd', '20260909-120000-abcdef123456.jsonl'):
            self.assertEqual((await self.client.get('/api/replay', params={'recording': path})).status, 404)
        meta = await self.opened()
        for endpoint in ('steps?start=bad', 'frame?step=-1', 'frame?step=999', 'frame?step=nan'):
            self.assertEqual((await self.client.get(f'/api/replay/{meta["token"]}/{endpoint}')).status, 400)
        provider = mock.Mock(side_effect=AssertionError('disabled history reached provider'))
        disabled = await self.client_for(SavedHistory(self.store, pin_provider=provider), enabled=False)
        try:
            self.assertEqual((await disabled.get('/api/replay')).status, 404)
            response = await disabled.get('/api/replay', params={'recording': '20260909-120000-abcdef123456.jsonl'})
            self.assertEqual(response.status, 404)
            for endpoint in ('anything', 'anything/steps', 'anything/frame'):
                self.assertEqual((await disabled.get('/api/replay/' + endpoint)).status, 404)
            self.assertEqual((await disabled.delete('/api/replay/anything')).status, 404)
            provider.assert_not_called()
        finally:
            await disabled.close()

    async def test_longer_index_does_not_contaminate_an_older_pinned_reader(self):
        self.write(3)
        old = HistoryIndex(self.store.pin())
        self.store.append(frame(10, (10, 10, 10)))
        self.store.append({'t': 10.1, 'act': 'GET', 'who': 'agent'})
        newer = HistoryIndex(self.store.pin())
        try:
            await asyncio.to_thread(newer.build)
            await asyncio.to_thread(old.build)
            self.assertEqual(old.steps, 3)
            self.assertEqual(old.summary['events'], 6)
            self.assertEqual(newer.steps, 4)
        finally:
            old.close()
            newer.close()


if __name__ == '__main__':
    unittest.main()
