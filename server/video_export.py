"""Cancellable, disk-backed action videos, using the screenshot history contract.

Each saved action becomes one frame. Encoding runs off the event loop and never
waits for recording time to pass, so watching or playing the game can continue.
"""
import asyncio
from collections import OrderedDict
import contextlib
from dataclasses import dataclass, field
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from aiohttp import web
from PIL import Image, ImageDraw, ImageFont

import activity_thumbnails
import history_frames
import history_index
from history_index import HistoryIndex

BEAT = .6
SPEEDS = (1, 2, 4, 8)
TERMINAL = ('ready', 'cancelled', 'error')
ARCHIVE = re.compile(r'\d{8}-\d{6}-[a-f0-9]{12}\.jsonl')
# Keep request ids suitable for use as opaque HTTP idempotency tokens.  This
# follows the HTTP ``token`` character set and bounds memory retained by the
# in-process request map.
REQUEST_ID = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]{1,128}\Z")
BAR = 64
BACKGROUND = (11, 11, 15)


class Aborted(Exception):
    """The export no longer has a consumer."""


class CachedFileResponse(web.FileResponse):
    """Do not evict a cached file while aiohttp is sending it."""

    def __init__(self, service, path, **kwargs):
        super().__init__(path, **kwargs)
        self.service, self.cache_path = service, path

    async def prepare(self, request):
        try:
            return await super().prepare(request)
        finally:
            with self.service.cache_lock:
                count = self.service.downloads.get(self.cache_path, 1)
                if count <= 1:
                    self.service.downloads.pop(self.cache_path, None)
                else:
                    self.service.downloads[self.cache_path] = count - 1


@functools.lru_cache(maxsize=1)
def caption_font():
    for name in ('/System/Library/Fonts/Hiragino Sans GB.ttc',
                 '/System/Library/Fonts/PingFang.ttc',
                 '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'):
        try:
            return ImageFont.truetype(name, 16)
        except OSError:
            pass
    return ImageFont.load_default()


def recorded_clock(step):
    """Original journal time, independent of the compressed video position."""
    when = step.get('recorded_t', step.get('_when', step['t']))
    seconds, milliseconds = divmod(math.floor(max(0, when) * 1000 + .5), 1000)
    return f'{seconds // 3600}:{seconds // 60 % 60:02}:{seconds % 60:02}.{milliseconds:03}'


def captioned(picture, step, number, total, speed, size=None):
    """Keep the whole picture on resolution changes, with a bounded caption."""
    if size is None:
        size = (max(320, picture.width * 2), picture.height * 2 + BAR)
    width, height = size
    canvas = Image.new('RGB', size, BACKGROUND)
    available = (width, height - BAR)
    scale = min(available[0] / picture.width, available[1] / picture.height)
    shown = picture.resize((max(1, round(picture.width * scale)),
                            max(1, round(picture.height * scale))), Image.Resampling.NEAREST)
    canvas.paste(shown, ((width - shown.width) // 2, (available[1] - shown.height) // 2))
    draw, font = ImageDraw.Draw(canvas), caption_font()
    draw.rectangle((0, height - BAR, width, height), fill=(18, 18, 24))

    def line(text, y, color):
        text = str(text).replace('\n', ' ')[:200]
        # Crop labels before drawing; arbitrarily long actor names or details
        # cannot overlap the progress line or create an unbounded glyph cache.
        while text and draw.textlength(text, font=font) > width - 24:
            text = text[:-1]
        draw.text((12, y), text, font=font, fill=color)

    result = ' [failed]' if step.get('ok') is False else ''
    label = f"{step.get('who') or 'web'}  {step['act']} {step.get('on', '')}{result}"
    line(label, height - BAR + 5, (143, 203, 247) if not result else (247, 143, 143))
    # Put source time first so narrow recordings cannot crop it behind counters.
    line(f'Original {recorded_clock(step)}   {number + 1} / {total}   {speed}x',
         height - BAR + 33, (158, 158, 174))
    return canvas


@dataclass
class Job:
    recording: str
    speed: int
    index: HistoryIndex
    source_key: tuple
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    request_id: str | None = None
    state: str = 'queued'
    completed: int = 0
    total: int = 0
    seconds: float = 0
    cached: bool = False
    error: str = ''
    path: Path | None = None
    created: float = field(default_factory=time.monotonic)
    finished: float | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    process: subprocess.Popen | None = None

    def update(self, **values):
        with self.lock:
            if self.state in TERMINAL:
                return
            if values.get('state') == 'ready' and self.stop.is_set():
                values.update(state='cancelled', error='')
            for key, value in values.items():
                setattr(self, key, value)
            if self.state in TERMINAL:
                self.finished = time.monotonic()

    def cancel(self):
        with self.lock:
            if self.state in TERMINAL:
                return
            self.stop.set()
            self.index.cancelled.set()
            if self.state == 'queued':
                self.state, self.finished = 'cancelled', time.monotonic()
                self.index.close()
            # Interrupt a blocked pipe write as well as the between-frame loop.
            if self.process is not None:
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass

    def public(self):
        with self.lock:
            completed, total = self.completed, self.total
            if self.state == 'indexing':
                completed, total = self.index.scanned, self.index.total
            return dict(id=self.id, state=self.state, recording=self.recording,
                        speed=self.speed, completed=completed, total=total,
                        seconds=self.seconds, cached=self.cached, error=self.error,
                        download=f'api/video/{self.id}/file' if self.state == 'ready' else None)


def renderer_signature():
    """Any change in frame selection, decoding or captions invalidates old MP4s."""
    digest = hashlib.sha256()
    for module in (__file__, history_frames.__file__, history_index.__file__, activity_thumbnails.__file__):
        digest.update(Path(module).read_bytes())
    return digest.hexdigest()


def cache_identity(index, speed, renderer):
    stat = os.fstat(index.source.fd)
    marks = hashlib.sha256()
    for (data,) in index.db.execute('SELECT data FROM steps ORDER BY seq'):
        if index.cancelled.is_set():
            raise Aborted()
        marks.update(data.encode())
        marks.update(b'\n')
    last = index.step(index.steps - 1)
    try:
        _, _, _, frame_end = next(history_frames.iter_frames(index, [last]))
    except StopIteration:
        raise Aborted() if index.cancelled.is_set() else ValueError('no recorded picture for this action')
    identity = dict(device=stat.st_dev, inode=stat.st_ino, header=index.source.header,
                    steps=index.steps, marks=marks.hexdigest(), frame_end=frame_end,
                    speed=speed, renderer=renderer)
    # Appending idle frames beyond an already settled last action cannot affect
    # its MP4. Inside that final interval, additional frames still may matter.
    if index.source.duration < last.get('_cutoff', last['cutoff'] + index.base):
        identity['unfinished_tail'] = index.source.end
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return key, identity


def encode(index, job, path):
    executable = shutil.which('ffmpeg')
    if executable is None:
        raise RuntimeError('ffmpeg is required for video export')
    count, size, process = 0, None, None
    # stderr is a disk file, so a noisy encoder cannot deadlock a full pipe or
    # leave an unbounded error string in memory.
    with tempfile.TemporaryFile() as errors:
        try:
            for step, picture, _, _ in history_frames.iter_frames(index):
                if job.stop.is_set():
                    raise Aborted()
                canvas = captioned(picture, step, count, index.steps, job.speed, size)
                if process is None:
                    size = canvas.size
                    with job.lock:
                        if job.stop.is_set():
                            raise Aborted()
                        process = subprocess.Popen([
                            executable, '-hide_banner', '-loglevel', 'error', '-y',
                            '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                            '-s', f'{size[0]}x{size[1]}', '-r', f'{job.speed * 5}/3',
                            '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-threads', '2',
                            '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
                            '-movflags', '+faststart', str(path)],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
                        job.process = process
                process.stdin.write(canvas.tobytes())
                count += 1
                job.update(completed=count)
            if job.stop.is_set():
                raise Aborted()
            if process is None or count != index.steps:
                raise ValueError('not every saved action has a recorded picture')
            job.update(state='finalizing')
            process.stdin.close()
            while True:
                if job.stop.is_set():
                    raise Aborted()
                try:
                    process.wait(timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode:
                errors.seek(0)
                raise RuntimeError('ffmpeg failed: ' + errors.read(1024).decode('utf-8', 'replace').strip())
            return count, count * BEAT / job.speed
        except (BrokenPipeError, OSError) as error:
            if job.stop.is_set():
                raise Aborted() from error
            errors.seek(0)
            reason = errors.read(1024).decode('utf-8', 'replace').strip()
            raise RuntimeError('video encoder failed: ' + (reason or str(error))) from error
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if process.stdin and not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass
            with job.lock:
                job.process = None


class VideoExports:
    MAX_PENDING = 4
    MAX_JOBS = 64
    TTL = 86400
    CACHE_BYTES = 2 << 30
    CACHE_TTL = 30 * 86400

    def __init__(self, store, pin_provider=None):
        self.store, self.pin_provider = store, pin_provider
        self.jobs = OrderedDict()
        self.request_jobs = {}
        self.task = None
        self.wake = asyncio.Event()
        self.closed = False
        self.renderer = renderer_signature()
        self.cache = Path(store.path).parent / '.video-cache'
        self.cache_lock = threading.Lock()
        self.downloads = {}

    def _trim_cache(self, keep=None, startup=False):
        """Bound disposable files, retaining the latest result even if oversized.

        A recording directory has one writer/service. Only our generated names
        are eligible; source recordings and active partials are never removed.
        """
        with self.cache_lock:
            if not self.cache.is_dir():
                return
            active = {job.id for job in list(self.jobs.values()) if job.state not in TERMINAL}
            pairs = {}
            for path in self.cache.iterdir():
                if path.is_symlink() or not path.is_file():
                    continue
                partial = re.fullmatch(r'([a-f0-9]{32})\.partial\.(mp4|json)', path.name)
                if startup and partial and partial[1] not in active:
                    with contextlib.suppress(OSError):
                        path.unlink()
                if re.fullmatch(r'[a-f0-9]{64}\.(mp4|json)', path.name):
                    pairs.setdefault(path.stem, []).append(path)
            entries = []
            for key, paths in pairs.items():
                try:
                    size = sum(path.stat().st_size for path in paths)
                    touched = max(path.stat().st_mtime for path in paths)
                except OSError:
                    continue
                entries.append((touched, size, self.cache / (key + '.mp4'), paths))
            entries.sort(reverse=True)
            if keep is None and entries:
                keep = next((video for _, _, video, _ in entries if video.is_file()), None)
            protected = set(self.downloads)
            if keep is not None:
                protected.add(keep)
            total = sum(size for _, size, _, _ in entries)
            for touched, size, video, paths in reversed(entries):
                if video in protected:
                    continue
                if total <= self.CACHE_BYTES and time.time() - touched <= self.CACHE_TTL:
                    continue
                for path in paths:
                    with contextlib.suppress(OSError):
                        path.unlink()
                if not any(path.exists() for path in paths):
                    total -= size

    def _reap(self):
        now = time.monotonic()
        for token, job in list(self.jobs.items()):
            if job.state in TERMINAL and now - (job.finished or job.created) > self.TTL:
                self.jobs.pop(token)
        for token, job in list(self.jobs.items()):
            if len(self.jobs) < self.MAX_JOBS:
                break
            if job.state in TERMINAL:
                self.jobs.pop(token)
        for request_id, job in list(self.request_jobs.items()):
            if self.jobs.get(job.id) is not job:
                self.request_jobs.pop(request_id, None)

    def _lookup(self, request):
        job = self.jobs.get(request.match_info['id'])
        if job is None:
            raise web.HTTPNotFound(reason='video job expired; start a new export')
        return job

    async def create(self, request):
        if self.closed:
            raise web.HTTPServiceUnavailable(reason='video service is closing')
        try:
            body = await request.json()
            recording, speed = body.get('recording', 'current'), body.get('speed', 1)
            header_request_id = request.headers.get('X-Video-Request-Id')
            request_id = (body['requestId'] if 'requestId' in body else header_request_id)
            if ('requestId' in body and header_request_id is not None
                    and request_id != header_request_id):
                raise ValueError()
            request_id_supplied = 'requestId' in body or header_request_id is not None
            if (type(speed) is not int or speed not in SPEEDS or not isinstance(recording, str)
                    or (recording != 'current' and not ARCHIVE.fullmatch(recording))):
                raise ValueError()
            if request_id_supplied and (not isinstance(request_id, str)
                                        or REQUEST_ID.fullmatch(request_id) is None):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise web.HTTPBadRequest(reason='invalid video export request')
        if recording != 'current' and self.pin_provider is None:
            raise web.HTTPNotFound(reason='recording not found')
        self._reap()
        if request_id is not None:
            previous = self.request_jobs.get(request_id)
            if (previous is not None and previous.recording == recording
                    and previous.speed == speed and not previous.stop.is_set()
                    and previous.state not in ('cancelled', 'error')
                    and (previous.state != 'ready'
                         or (previous.path is not None and previous.path.is_file()))):
                meta = previous.public()
                if previous.state == 'ready':
                    meta['cached'] = True
                    with contextlib.suppress(OSError):
                        os.utime(previous.path, None)
                return web.json_response(meta, status=200 if previous.state == 'ready' else 202)
            if previous is not None and self.request_jobs.get(request_id) is previous:
                self.request_jobs.pop(request_id, None)
        try:
            pin = self.pin_provider(recording) if self.pin_provider else self.store.pin()
            index = HistoryIndex(pin)
        except (ValueError, TypeError, KeyError, OSError) as error:
            raise web.HTTPUnprocessableEntity(reason='recording cannot be opened: ' + str(error))
        stat = os.fstat(index.source.fd)
        source_key = (stat.st_dev, stat.st_ino, index.source.end,
                      json.dumps(index.source.header, sort_keys=True), speed)
        for job in self.jobs.values():
            if (request_id is None and job.source_key == source_key and not job.stop.is_set()
                    and job.state not in ('cancelled', 'error')):
                if job.state != 'ready' or (job.path and job.path.is_file()):
                    index.close()
                    meta = job.public()
                    if job.state == 'ready':
                        meta['cached'] = True
                        with contextlib.suppress(OSError):
                            os.utime(job.path, None)
                    return web.json_response(meta, status=200 if job.state == 'ready' else 202)
        if sum(job.state not in TERMINAL for job in self.jobs.values()) >= self.MAX_PENDING:
            index.close()
            raise web.HTTPTooManyRequests(reason='video export queue is full')
        job = Job(recording, speed, index, source_key, request_id=request_id)
        index.cancelled = job.stop
        self.jobs[job.id] = job
        if request_id is not None:
            self.request_jobs[request_id] = job
        self.wake.set()
        return web.json_response(job.public(), status=202)

    async def info(self, request):
        return web.json_response(self._lookup(request).public())

    async def cancel(self, request):
        job = self._lookup(request)
        job.cancel()
        return web.json_response(job.public())

    async def download(self, request):
        job = self._lookup(request)
        with self.cache_lock:
            if job.state != 'ready' or job.path is None or not job.path.is_file():
                raise web.HTTPConflict(reason='video is not ready')
            response = CachedFileResponse(self, job.path, headers={
                'Content-Type': 'video/mp4',
                'Content-Disposition': f'attachment; filename="qunxia-{job.speed}x-{job.id[:8]}.mp4"',
            })
            self.downloads[job.path] = self.downloads.get(job.path, 0) + 1
            with contextlib.suppress(OSError):
                os.utime(job.path, None)
            return response

    async def _worker(self):
        while not self.closed:
            job = next((job for job in self.jobs.values() if job.state == 'queued'), None)
            if job is None:
                self.wake.clear()
                await self.wake.wait()
                continue
            job.update(state='indexing')
            await asyncio.to_thread(self.render, job)

    def render(self, job):
        index, partial, temp_meta = job.index, None, None
        try:
            if job.stop.is_set():
                raise Aborted()
            index.build()
            if job.stop.is_set():
                raise Aborted()
            if not index.steps:
                raise ValueError('this recording has no saved actions to export')
            key, identity = cache_identity(index, job.speed, self.renderer)
            self.cache.mkdir(exist_ok=True)
            target, metadata = self.cache / (key + '.mp4'), self.cache / (key + '.json')
            if job.stop.is_set():
                raise Aborted()
            try:
                saved = json.loads(metadata.read_text())
                if (saved.get('identity') == identity and target.stat().st_size == saved.get('bytes')
                        and saved.get('frames') == index.steps and saved.get('seconds') == index.steps * BEAT / job.speed):
                    os.utime(target, None)
                    self._trim_cache(keep=target)
                    job.update(state='ready', completed=index.steps, total=index.steps,
                               seconds=saved['seconds'], path=target, cached=True)
                    return
            except (OSError, ValueError, AttributeError):
                pass
            job.update(state='encoding', completed=0, total=index.steps,
                       seconds=index.steps * BEAT / job.speed)
            partial = self.cache / (job.id + '.partial.mp4')
            count, seconds = encode(index, job, partial)
            if job.stop.is_set():
                raise Aborted()
            os.replace(partial, target)
            saved = dict(identity=identity, frames=count, seconds=seconds, bytes=target.stat().st_size)
            temp_meta = self.cache / (job.id + '.partial.json')
            temp_meta.write_text(json.dumps(saved, ensure_ascii=False) + '\n')
            os.replace(temp_meta, metadata)
            self._trim_cache(keep=target)
            job.update(state='ready', completed=count, total=count, seconds=seconds, path=target)
        except Aborted:
            job.update(state='cancelled', error='')
        except Exception as error:
            job.update(state='cancelled' if job.stop.is_set() else 'error',
                       error='' if job.stop.is_set() else str(error)[:300])
        finally:
            index.close()
            for path in (partial, temp_meta):
                if path is not None:
                    with contextlib.suppress(OSError):
                        path.unlink(missing_ok=True)

    async def startup(self, app):
        await asyncio.to_thread(self._trim_cache, startup=True)
        self.task = asyncio.create_task(self._worker())

    async def cleanup(self, app):
        self.closed = True
        for job in self.jobs.values():
            job.cancel()
        self.wake.set()
        if self.task:
            try:
                await asyncio.shield(self.task)
            except asyncio.CancelledError:
                await self.task
                raise

    def install(self, app, enabled=True):
        if not enabled:
            return
        app.add_routes([
            web.post('/api/video', self.create),
            web.get('/api/video/{id}', self.info),
            web.delete('/api/video/{id}', self.cancel),
            web.get('/api/video/{id}/file', self.download),
        ])
        app.on_startup.append(self.startup)
        app.on_cleanup.append(self.cleanup)
