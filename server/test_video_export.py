"""Fast action MP4s share history semantics, without stopping the emulator."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from history_index import INDEX_LOCK
from recording_store import RecordingStore
from test_saved_history import frame
from video_export import VideoExports, captioned, recorded_clock


class VideoExportTests(unittest.IsolatedAsyncioTestCase):
    def test_caption_preserves_original_time_and_milliseconds_over_a_day(self):
        step = {'act': 'GET', 't': 1.234, 'recorded_t': 90061.234}
        self.assertEqual(recorded_clock(step), '25:01:01.234')
        self.assertEqual(recorded_clock({'t': 0, 'recorded_t': 3599.9996}), '1:00:00.000')
        draw = mock.Mock()
        draw.textlength.side_effect = lambda text, **kwargs: len(text) * 8
        with mock.patch('video_export.ImageDraw.Draw', return_value=draw):
            captioned(Image.new('RGB', (2, 1)), step, 12345, 99999, 4)
        displayed = [call.args[1] for call in draw.text.call_args_list]
        self.assertTrue(any(text.startswith('Original 25:01:01.234') for text in displayed))

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'recording.jsonl'
        self.store = RecordingStore(self.path, started=100)
        self.service = VideoExports(self.store)
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

    def write(self, count=4):
        for number in range(count):
            self.store.append(frame(number * 2, (number, 30, 80)))
            self.store.append({'t': number * 2 + .1, 'act': 'GET', 'who': 'agent'})

    async def create(self, speed=4, recording='current'):
        response = await self.client.post('/api/video', json=dict(speed=speed, recording=recording))
        self.assertIn(response.status, (200, 202), await response.text())
        return await response.json()

    async def done(self, meta):
        for _ in range(1000):
            if meta['state'] in ('ready', 'cancelled', 'error'):
                return meta
            await asyncio.sleep(.005)
            response = await self.client.get('/api/video/' + meta['id'])
            self.assertEqual(response.status, 200)
            meta = await response.json()
        self.fail('export did not finish')

    async def restart(self):
        await self.client.close()
        self.service = VideoExports(self.store)
        self.client = await self.client_for(self.service)

    @staticmethod
    def fake_encode(index, job, path):
        Path(path).write_bytes(b'small test video')
        return index.steps, index.steps * .6 / job.speed

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg and ffprobe required')
    async def test_small_real_mp4_has_one_frame_per_rich_action_and_fixed_duration(self):
        events = [frame(0, (10, 20, 30)),
                  {'t': 1, 'act': 'GET', 'who': 'agent', 'history': 1},
                  {'t': 1, 'act': 'KEY', 'who': 'web', 'on': 'up', 'ok': False, 'history': 1},
                  frame(1, (20, 30, 40)),
                  {'t': 2, 'act': 7, 'label': 'KEY down', 'who': 'agent', 'history': 1},
                  frame(2.5, (30, 40, 50)),
                  {'t': 3, 'act': 'KEY', 'phase': 'after', 'who': 'web', 'history': 1},
                  frame(9000, (40, 50, 60))]
        for event in events:
            self.store.append(event)
        original = self.path.read_bytes()
        started = time.monotonic()
        result = await self.done(await self.create())
        elapsed = time.monotonic() - started
        self.assertEqual(result['state'], 'ready', result)
        self.assertEqual(result['completed'], 4)
        self.assertEqual(result['total'], 4)
        self.assertAlmostEqual(result['seconds'], .6)
        download = await self.client.get('/' + result['download'])
        self.assertEqual(download.status, 200)
        self.assertEqual(download.content_type, 'video/mp4')
        self.assertIn('attachment;', download.headers['Content-Disposition'])
        output = self.service.jobs[result['id']].path
        self.assertEqual(await download.read(), output.read_bytes())
        probe = json.loads(subprocess.check_output([
            shutil.which('ffprobe'), '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=nb_frames,duration,width,height', '-of', 'json', str(output)]))['streams'][0]
        self.assertEqual(int(probe['nb_frames']), 4)
        self.assertAlmostEqual(float(probe['duration']), .6, places=3)
        self.assertEqual(probe['width'] % 2, 0)
        self.assertEqual(probe['height'] % 2, 0)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertLess(elapsed, 5, 'four frames must not wait for 9000 seconds of recording time')
        print(f'\nsmall MP4 witness: 4 frames, 0.6s video, {elapsed:.3f}s export, {output.stat().st_size} bytes')

    async def test_restart_cache_survives_idle_append_and_isolated_from_new_actions(self):
        self.write()
        with mock.patch('video_export.encode', side_effect=self.fake_encode) as render:
            first = await self.done(await self.create())
            self.assertEqual(first['state'], 'ready', first)
            path = self.service.jobs[first['id']].path
            await self.restart()
            # A later idle picture cannot change any earlier GET result.
            self.store.append(frame(5000, (8, 8, 8)))
            second = await self.done(await self.create())
            self.assertEqual(second['state'], 'ready', second)
            self.assertTrue(second['cached'])
            self.assertEqual(self.service.jobs[second['id']].path, path)
            self.assertEqual(render.call_count, 1)
            self.store.append({'t': 5001, 'act': 'GET', 'who': 'agent'})
            third = await self.done(await self.create())
            self.assertEqual(third['state'], 'ready', third)
            self.assertFalse(third['cached'])
            self.assertEqual(third['total'], 5)
            self.assertEqual(render.call_count, 2)
            again = await self.create()
            self.assertEqual(again['id'], third['id'])
            self.assertTrue(again['cached'])

    async def test_request_id_is_idempotent_across_append_and_distinguishes_tokens(self):
        self.write()
        with mock.patch('video_export.encode', side_effect=self.fake_encode):
            first = await self.client.post('/api/video', json={
                'speed': 4, 'requestId': 'export-1',
            })
            self.assertEqual(first.status, 202)
            first = await first.json()
            duplicate = await self.client.post('/api/video', json={
                'speed': 4, 'requestId': 'export-1',
            })
            self.assertEqual(duplicate.status, 202)
            duplicate = await duplicate.json()
            self.assertEqual(duplicate['id'], first['id'])
            self.assertEqual(len(self.service.jobs), 1)
            second = await self.done(first)
            self.assertEqual(second['state'], 'ready', second)
            same = await self.client.post('/api/video', json={
                'speed': 4, 'requestId': 'export-1',
            })
            self.assertEqual(same.status, 200)
            same = await same.json()
            self.assertEqual(same['id'], first['id'])
            self.assertEqual(len(self.service.jobs), 1)

            self.store.append(frame(5000, (8, 8, 8)))
            after_append = await self.client.post('/api/video', json={
                'speed': 4, 'requestId': 'export-1',
            })
            self.assertEqual(after_append.status, 200)
            self.assertEqual((await after_append.json())['id'], first['id'])

            other = await self.client.post('/api/video', json={
                'speed': 4, 'requestId': 'export-2',
            })
            self.assertEqual(other.status, 202)
            self.assertNotEqual((await other.json())['id'], first['id'])
            self.assertEqual(len(self.service.jobs), 2)

    async def test_request_id_header_and_validation(self):
        self.write()
        with mock.patch('video_export.encode', side_effect=self.fake_encode):
            first = await self.client.post('/api/video', json={'speed': 1},
                                           headers={'X-Video-Request-Id': 'header-token'})
            self.assertEqual(first.status, 202)
            first = await first.json()
            same = await self.client.post('/api/video', json={'speed': 1},
                                          headers={'X-Video-Request-Id': 'header-token'})
            self.assertEqual(same.status, 202)
            self.assertEqual((await same.json())['id'], first['id'])
        for request_id in ('', 'contains space', '../path', 'x' * 129, None, 7):
            body = {'requestId': request_id}
            response = await self.client.post('/api/video', json=body)
            self.assertEqual(response.status, 400, body)
        response = await self.client.post(
            '/api/video', json={'requestId': 'body-token'},
            headers={'X-Video-Request-Id': 'header-token'})
        self.assertEqual(response.status, 400)

    async def test_unfinished_settle_and_renderer_changes_invalidate_cache(self):
        self.store.append(frame(0, (1, 2, 3)))
        self.store.append({'t': 1, 'act': 'KEY', 'who': 'agent'})
        with mock.patch('video_export.encode', side_effect=self.fake_encode) as render:
            first = await self.done(await self.create())
            first_path = self.service.jobs[first['id']].path
            # Same final step, but its settling window is still receiving frames.
            self.store.append(frame(1.5, (5, 6, 7)))
            second = await self.done(await self.create())
            self.assertFalse(second['cached'])
            self.assertNotEqual(self.service.jobs[second['id']].path, first_path)
            self.assertEqual(render.call_count, 2)
            await self.restart()
            self.service.renderer = 'new-renderer-version'
            third = await self.done(await self.create())
            self.assertFalse(third['cached'])
            self.assertEqual(render.call_count, 3)

    async def test_cancelled_queued_job_closes_pin_and_retry_never_reuses_it(self):
        self.write()
        entered, release = threading.Event(), threading.Event()

        def blocked(index, job, path):
            entered.set()
            release.wait(3)
            return self.fake_encode(index, job, path)

        with mock.patch('video_export.encode', side_effect=blocked):
            first = await self.create(speed=1)
            for _ in range(200):
                if entered.is_set():
                    break
                await asyncio.sleep(.005)
            try:
                queued = await self.create(speed=2)
                self.assertEqual(queued['state'], 'queued')
                index = self.service.jobs[queued['id']].index
                response = await self.client.delete('/api/video/' + queued['id'])
                self.assertEqual((await response.json())['state'], 'cancelled')
                self.assertTrue(index.closed)
                with self.assertRaises(OSError):
                    os.fstat(index.source.fd)
                retried = await self.create(speed=2)
                self.assertNotEqual(retried['id'], queued['id'])
                self.assertEqual(retried['state'], 'queued')
            finally:
                release.set()
            self.assertEqual((await self.done(first))['state'], 'ready')
            self.assertEqual((await self.done(retried))['state'], 'ready')

    async def test_indexing_cancel_is_responsive_and_does_not_block_other_routes(self):
        self.write()
        INDEX_LOCK.acquire()
        try:
            meta = await self.create()
            for _ in range(20):
                if self.service.jobs[meta['id']].state == 'indexing':
                    break
                await asyncio.sleep(.005)
            start = time.monotonic()
            self.assertEqual((await self.client.get('/ping')).status, 200)
            response = await self.client.get('/api/video/' + meta['id'])
            self.assertEqual((await response.json())['state'], 'indexing')
            await self.client.delete('/api/video/' + meta['id'])
            self.assertEqual((await self.done(meta))['state'], 'cancelled')
            self.assertLess(time.monotonic() - start, .5)
        finally:
            INDEX_LOCK.release()

    async def test_cancel_interrupts_a_blocked_encoder_pipe_and_reaps_process(self):
        self.write()
        writing, killed = threading.Event(), threading.Event()

        class Input:
            closed = False

            def write(self, data):
                writing.set()
                if not killed.wait(2):
                    raise AssertionError('cancel did not interrupt encoder pipe')
                raise BrokenPipeError()

            def close(self):
                self.closed = True

        class Process:
            stdin = Input()
            returncode = None
            waited = False

            def kill(self):
                self.returncode = -9
                killed.set()

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.waited = True
                return self.returncode

        process = Process()
        with mock.patch('video_export.shutil.which', return_value='/fake/ffmpeg'), \
                mock.patch('video_export.subprocess.Popen', return_value=process):
            meta = await self.create()
            for _ in range(200):
                if writing.is_set():
                    break
                await asyncio.sleep(.005)
            self.assertTrue(writing.is_set())
            start = time.monotonic()
            await self.client.delete('/api/video/' + meta['id'])
            cancelled = await self.done(meta)
            self.assertEqual(cancelled['state'], 'cancelled', cancelled)
            self.assertLess(time.monotonic() - start, .5)
            self.assertTrue(process.waited)
            self.assertTrue(process.stdin.closed)
            self.assertIsNone(self.service.jobs[meta['id']].process)
            self.assertEqual(list(self.service.cache.glob('*')), [])

    async def test_incomplete_or_corrupt_cache_metadata_is_rebuilt(self):
        self.write()
        with mock.patch('video_export.encode', side_effect=self.fake_encode) as render:
            first = await self.done(await self.create())
            path = self.service.jobs[first['id']].path
            path.write_bytes(b'truncated')
            await self.restart()
            second = await self.done(await self.create())
            self.assertEqual(second['state'], 'ready', second)
            self.assertFalse(second['cached'])
            path.with_suffix('.json').write_text('{broken')
            await self.restart()
            third = await self.done(await self.create())
            self.assertFalse(third['cached'])
            self.assertEqual(render.call_count, 3)

    async def test_cache_budget_keeps_latest_oversized_video_and_rebuilds_evicted_job(self):
        self.write()
        self.service.CACHE_BYTES = 1
        with mock.patch('video_export.encode', side_effect=self.fake_encode) as render:
            first = await self.done(await self.create(speed=1))
            first_path = self.service.jobs[first['id']].path
            self.assertTrue(first_path.is_file())
            second = await self.done(await self.create(speed=2))
            second_path = self.service.jobs[second['id']].path
            self.assertTrue(second_path.is_file())
            self.assertGreater(second_path.stat().st_size, self.service.CACHE_BYTES)
            self.assertFalse(first_path.exists())
            self.assertFalse(first_path.with_suffix('.json').exists())
            third = await self.done(await self.create(speed=1))
            self.assertEqual(third['state'], 'ready', third)
            self.assertNotEqual(third['id'], first['id'])
            self.assertFalse(third['cached'])
            self.assertFalse(second_path.exists())
            self.assertEqual(render.call_count, 3)
            self.assertEqual(len(list(self.service.cache.glob('*.mp4'))), 1)

    async def test_cache_age_and_download_protection(self):
        self.service.cache.mkdir()
        paths = []
        for number, letter in enumerate(('a', 'b', 'c')):
            path = self.service.cache / (letter * 64 + '.mp4')
            path.write_bytes(b'video')
            path.with_suffix('.json').write_text('{}')
            touched = time.time() - self.service.CACHE_TTL - 10 + number
            os.utime(path, (touched, touched))
            os.utime(path.with_suffix('.json'), (touched, touched))
            paths.append(path)
        self.service.downloads[paths[0]] = 1
        self.service._trim_cache()
        self.assertTrue(paths[0].is_file(), 'active download must survive eviction')
        self.assertFalse(paths[1].exists())
        self.assertTrue(paths[2].is_file(), 'latest video remains available')
        self.service.downloads.clear()
        self.service._trim_cache()
        self.assertFalse(paths[0].exists())
        self.assertTrue(paths[2].is_file())

    async def test_startup_removes_only_stale_generated_partials(self):
        self.service.cache.mkdir()
        stale = self.service.cache / ('a' * 32 + '.partial.mp4')
        active = self.service.cache / ('b' * 32 + '.partial.json')
        unrelated = self.service.cache / 'my-backup.partial.mp4'
        for path in (stale, active, unrelated):
            path.write_bytes(b'preserve or reclaim')
        self.service.jobs['active-test'] = SimpleNamespace(id='b' * 32, state='encoding')
        try:
            self.service._trim_cache(startup=True)
            self.assertFalse(stale.exists())
            self.assertTrue(active.is_file())
            self.assertTrue(unrelated.is_file())
        finally:
            self.service.jobs.pop('active-test')
        await self.restart()
        self.assertFalse(active.exists())
        self.assertTrue(unrelated.is_file())

    async def test_queue_bound_and_completed_handle_reaping(self):
        self.write()
        INDEX_LOCK.acquire()
        try:
            jobs = [await self.create(speed=speed) for speed in (1, 2, 4, 8)]
            self.store.append(frame(20, (1, 2, 3)))
            rejected = await self.client.post('/api/video', json={'speed': 1})
            self.assertEqual(rejected.status, 429)
            await self.client.delete('/api/video/' + jobs[-1]['id'])
            retry = await self.create(speed=8)
            self.assertNotEqual(retry['id'], jobs[-1]['id'])
            self.assertLessEqual(sum(job.state not in ('ready', 'cancelled', 'error')
                                     for job in self.service.jobs.values()), self.service.MAX_PENDING)
        finally:
            for job in self.service.jobs.values():
                job.cancel()
            INDEX_LOCK.release()
        await self.done(jobs[0])
        self.service.MAX_JOBS = 2
        self.service._reap()
        self.assertLess(len(self.service.jobs), 2)
        self.service.TTL = -1
        self.service._reap()
        self.assertEqual(len(self.service.jobs), 0)

    async def test_fixed_pin_survives_reset_and_supports_archived_provider(self):
        self.write()
        INDEX_LOCK.acquire()
        try:
            before = await self.create()
            archive = self.store.reset(200)
            self.store.append(frame(0, (200, 0, 0)))
            self.store.append({'t': 1, 'act': 'GET', 'who': 'agent'})
        finally:
            INDEX_LOCK.release()
        with mock.patch('video_export.encode', side_effect=self.fake_encode):
            old = await self.done(before)
            self.assertEqual(old['total'], 4)
            new = await self.done(await self.create())
            self.assertEqual(new['total'], 1)
            self.assertNotEqual(self.service.jobs[old['id']].path, self.service.jobs[new['id']].path)
            await self.restart()

            def pin_provider(name):
                if name == 'current':
                    return self.store.pin()
                self.assertEqual(name, archive.name)
                return dict(path=archive, fd=os.open(archive, os.O_RDONLY),
                            end=archive.stat().st_size, last_timestamp=6.1)

            self.service.pin_provider = pin_provider
            restored = await self.done(await self.create(recording=archive.name))
            self.assertEqual(restored['state'], 'ready', restored)
            self.assertEqual(restored['total'], 4)
            self.assertTrue(restored['cached'])

    async def test_errors_do_not_publish_partial_videos_and_retry_is_new_job(self):
        self.write()

        def failed(index, job, path):
            Path(path).write_bytes(b'incomplete')
            raise ValueError('damaged picture')

        with mock.patch('video_export.encode', side_effect=failed):
            first = await self.done(await self.create())
            self.assertEqual(first['state'], 'error')
            self.assertIn('damaged picture', first['error'])
            self.assertEqual(list(self.service.cache.glob('*')), [])
            self.assertEqual((await self.client.get('/api/video/' + first['id'] + '/file')).status, 409)
            second = await self.done(await self.create())
            self.assertNotEqual(first['id'], second['id'])
            self.assertTrue(self.service.jobs[second['id']].index.closed)

    async def test_cleanup_waits_for_worker_and_cancels_all_pins(self):
        self.write()
        INDEX_LOCK.acquire()
        try:
            first = await self.create(speed=1)
            second = await self.create(speed=2)
            await self.client.close()
            self.assertTrue(self.service.task.done())
            for token in (first['id'], second['id']):
                job = self.service.jobs[token]
                self.assertEqual(job.state, 'cancelled')
                self.assertTrue(job.index.closed)
        finally:
            INDEX_LOCK.release()

    async def test_validation_and_disabled_service(self):
        for body in ({'speed': True}, {'speed': .5}, {'speed': 3}, {'recording': '../secret'},
                     {'recording': None}, [], None):
            response = await self.client.post('/api/video', json=body)
            self.assertEqual(response.status, 400, body)
        missing = await self.client.post('/api/video', json={'recording': '20260909-121212-aaaaaaaaaaaa.jsonl'})
        self.assertEqual(missing.status, 404)
        self.assertEqual((await self.client.get('/api/video/missing')).status, 404)
        await self.client.close()
        self.client = await self.client_for(VideoExports(self.store), enabled=False)
        self.assertEqual((await self.client.post('/api/video', json={})).status, 404)


if __name__ == '__main__':
    unittest.main()
