"""Paged screenshots of every saved action, independent of the live log tail."""
import asyncio
from collections import OrderedDict
import contextlib
import secrets
import re
import time

from aiohttp import web

from history_frames import render_frame
from history_index import HistoryIndex


async def finish(function, *args):
    """Wait for file users even when a client disconnects or a task is cancelled."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await task
        raise


class SavedHistory:
    MAX_OPEN = 2
    TTL = 300

    def __init__(self, store, pin_provider=None):
        self.store = store
        self.pin_provider = pin_provider
        self.states = OrderedDict()
        self.lock = asyncio.Lock()
        self.reaper = None
        self.closed = False

    async def _close(self, state):
        state['index'].cancelled.set()
        try:
            with contextlib.suppress(Exception):
                await asyncio.shield(state['task'])
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await state['task']
            raise
        finally:
            state['index'].close()

    async def _expire(self):
        now = time.monotonic()
        for token, state in list(self.states.items()):
            if now - state['used'] > self.TTL:
                del self.states[token]
                await self._close(state)

    async def _get(self, token):
        await self._expire()
        state = self.states.get(token)
        if state is None:
            raise web.HTTPGone(reason='history expired; reopen the recording')
        state['used'] = time.monotonic()
        self.states.move_to_end(token)
        return state

    @staticmethod
    def metadata(token, state):
        index, task = state['index'], state['task']
        if not task.done():
            return {'token': token, 'indexing': True, 'scanned': index.scanned, 'total': index.total}
        error = task.exception()
        if error:
            raise web.HTTPUnprocessableEntity(reason='saved recording cannot be indexed: ' + str(error))
        return dict(token=token, indexing=False, steps=index.steps,
                    started=index.source.header.get('started'),
                    duration=max(0.0, index.source.duration-index.base),
                    beat=.6, speeds=[.5, 1, 2, 4, 8], **index.summary)

    async def open(self, request):
        # No user-supplied filesystem paths, including archived filenames.
        recording = request.query.get('recording', 'current')
        if recording != 'current' and (self.pin_provider is None or not re.fullmatch(r'[0-9]{8}-[0-9]{6}-[a-f0-9]{12}\.jsonl', recording)):
            raise web.HTTPNotFound()
        async with self.lock:
            if self.closed:
                raise web.HTTPServiceUnavailable(reason='history service is closing')
            await self._expire()
            while len(self.states) >= self.MAX_OPEN:
                _, state = self.states.popitem(last=False)
                await self._close(state)
            try:
                pin = self.pin_provider(recording) if self.pin_provider else self.store.pin()
                index = HistoryIndex(pin)
            except FileNotFoundError:
                raise web.HTTPNotFound()
            except (ValueError, TypeError, KeyError, OSError) as error:
                raise web.HTTPUnprocessableEntity(reason='saved recording cannot be opened: ' + str(error))
            token = secrets.token_urlsafe(18)
            state = {'index': index, 'used': time.monotonic(),
                     'task': asyncio.create_task(asyncio.to_thread(index.build))}
            self.states[token] = state
            meta = self.metadata(token, state)
            return web.json_response(meta, status=202 if meta['indexing'] else 200)

    async def info(self, request):
        async with self.lock:
            token = request.match_info['token']
            meta = self.metadata(token, await self._get(token))
            return web.json_response(meta, status=202 if meta['indexing'] else 200)

    async def steps(self, request):
        async with self.lock:
            token = request.match_info['token']
            state = await self._get(token)
            meta = self.metadata(token, state)
            if meta['indexing']:
                return web.json_response(meta, status=202)
            try:
                start = max(0, int(request.query.get('start', '0')))
                count = min(128, max(1, int(request.query.get('count', '128'))))
            except ValueError:
                raise web.HTTPBadRequest(reason='invalid step range')
            index = state['index']
            return web.json_response({'start': start, 'steps': index.page(start, count), 'total': index.steps})

    async def frame(self, request):
        async with self.lock:
            token = request.match_info['token']
            state = await self._get(token)
            meta = self.metadata(token, state)
            if meta['indexing']:
                return web.json_response(meta, status=202)
            try:
                number = int(request.query.get('step', '0'))
                step = state['index'].step(number)
            except ValueError:
                raise web.HTTPBadRequest(reason='invalid step')
            try:
                data, when = await finish(render_frame, state['index'], step)
            except (ValueError, OSError) as error:
                raise web.HTTPUnprocessableEntity(reason=str(error))
            return web.Response(body=data, content_type='image/png', headers={
                'Cache-Control': 'no-store', 'X-Replay-Step': str(number),
                'X-Replay-Time': str(step['t']), 'X-Replay-Frame-Time': str(when),
                'X-Replay-Source': 'recording',
            })

    async def close(self, request):
        async with self.lock:
            state = self.states.pop(request.match_info['token'], None)
            if state:
                await self._close(state)
            return web.json_response({'ok': True})

    async def _reap(self):
        while True:
            await asyncio.sleep(min(30, self.TTL))
            async with self.lock:
                await self._expire()

    async def startup(self, app):
        self.reaper = asyncio.create_task(self._reap())

    async def cleanup(self, app):
        self.closed = True
        if self.reaper:
            self.reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.reaper
        async with self.lock:
            for state in self.states.values():
                await self._close(state)
            self.states.clear()

    def install(self, app, enabled=True):
        if not enabled:
            return
        app.add_routes([
            web.get('/api/replay', self.open),
            web.get('/api/replay/{token}', self.info),
            web.get('/api/replay/{token}/steps', self.steps),
            web.get('/api/replay/{token}/frame', self.frame),
            web.delete('/api/replay/{token}', self.close),
        ])
        app.on_startup.append(self.startup)
        app.on_cleanup.append(self.cleanup)
