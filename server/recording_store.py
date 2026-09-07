"""Append-only JSONL recording. Successful append means write + fsync finished."""
from collections import deque
import json
import fcntl
import math
import os
from pathlib import Path
import threading
import time
import uuid


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class RecordingStore:
    MAX_PENDING = 4 << 20

    def __init__(self, path, started=None):
        self.fd = self.lease_fd = None
        try:
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.lock = threading.RLock()
            self.lease_fd = os.open(self.path.with_suffix(self.path.suffix + '.lock'),
                                    os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(self.lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(self.lease_fd)
                self.lease_fd = None
                raise RuntimeError('another process owns this recording directory')
            self.pending = deque()
            self.pending_bytes = 0
            self.error = ''
            self.directory_pending = False
            self.fd = None
            self.pending_start = None
            self.last_timestamp = 0.0
            self.started = time.time() if started is None else started
            fallback_started = self.started
            if self.path.exists():
                try:
                    with self.path.open('rb') as stream:
                        header = json.loads(stream.readline(64 << 10))
                        self.started = float(header['started'])
                        if not math.isfinite(self.started):
                            raise ValueError('recording origin is not finite')
                        size = os.fstat(stream.fileno()).st_size
                        # A timestamp is all startup needs from old content. Keep
                        # at most one bounded tail, never a replay cache.
                        header_end = stream.tell()
                        start = max(header_end, size - self.MAX_PENDING)
                        stream.seek(start)
                        if start > header_end:
                            stream.readline()
                        for line in stream:
                            try:
                                event = json.loads(line)
                                when = float(event.get('t', 0))
                                if math.isfinite(when) and when >= 0:
                                    self.last_timestamp = max(self.last_timestamp, when)
                            except (ValueError, TypeError, UnicodeError, AttributeError):
                                continue
                except (OSError, ValueError, KeyError, TypeError):
                    # Never clear an unreadable recording. Archive its exact bytes
                    # before opening a new journal so it remains recoverable.
                    self.started = fallback_started
                    self.archive()
            if not self.path.exists():
                self._new_file()
            self.fd = os.open(self.path, os.O_RDWR | os.O_APPEND)
            size = os.fstat(self.fd).st_size
            if size and os.pread(self.fd, 1, size - 1) != b'\n':
                # A crash mid-append leaves a torn final line. Closing it with
                # a newline would hand every reader one unparseable line until
                # the next reset, so drop it back to the last complete line.
                # The header parsed above, so a file with no newline at all is
                # a complete header that only lacks its terminator.
                end = self._last_line_end(size)
                if end:
                    os.ftruncate(self.fd, end)
                else:
                    os.write(self.fd, b'\n')
                os.fsync(self.fd)
            self.committed_size = os.fstat(self.fd).st_size
        except BaseException:
            for descriptor in (self.fd, self.lease_fd):
                if descriptor is not None:
                    os.close(descriptor)
            self.fd = self.lease_fd = None
            raise

    def _last_line_end(self, size):
        """Offset just past the last newline in the file, or 0 if none."""
        pos = size
        while pos > 0:
            start = max(0, pos - (64 << 10))
            chunk = os.pread(self.fd, pos - start, start)
            index = chunk.rfind(b'\n')
            if index >= 0:
                return start + index + 1
            pos = start
        return 0

    def _prepare_file(self, started):
        data = (json.dumps({'version': 1, 'started': started}) + '\n').encode()
        tmp = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with tmp.open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            return tmp
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _new_file(self):
        tmp = self._prepare_file(self.started)
        try:
            os.replace(tmp, self.path)
            sync_directory(self.path.parent)
        finally:
            tmp.unlink(missing_ok=True)

    def _write(self, data):
        if self.pending_start is None:
            self.pending_start = os.fstat(self.fd).st_size
        start = self.pending_start
        try:
            if os.fstat(self.fd).st_size != start:
                os.ftruncate(self.fd, start)
            view = memoryview(data)
            while view:
                written = os.write(self.fd, view)
                if written <= 0:
                    raise OSError('recording write made no progress')
                view = view[written:]
            os.fsync(self.fd)
            self.committed_size = start + len(data)
            self.pending_start = None
        except OSError:
            # Only the uncommitted suffix belongs to this attempt. Keep its
            # bytes in pending and remove a partial append before retrying.
            os.ftruncate(self.fd, start)
            raise

    def append(self, event):
        if not isinstance(event, dict):
            raise ValueError('recording event must be an object')
        when = float(event.get('t', -1))
        if not math.isfinite(when) or when < 0:
            raise ValueError('recording event time must be finite and non-negative')
        data = (json.dumps(event, separators=(',', ':'), ensure_ascii=False) + '\n').encode()
        with self.lock:
            if self.pending_bytes + len(data) > self.MAX_PENDING:
                raise BufferError('recording storage is blocked; input must wait')
            self.pending.append(data)
            self.pending_bytes += len(data)
            return self.flush()

    def flush(self):
        with self.lock:
            if self.directory_pending:
                try:
                    sync_directory(self.path.parent)
                    self.directory_pending = False
                except OSError as error:
                    self.error = str(error)
                    return False
            while self.pending:
                try:
                    self._write(self.pending[0])
                except OSError as error:
                    self.error = str(error)
                    return False
                data = self.pending.popleft()
                self.pending_bytes -= len(data)
                self.last_timestamp = max(self.last_timestamp, float(json.loads(data).get('t', 0)))
            self.error = ''
            return True

    def archive(self, unlink=True):
        with self.lock:
            if self.pending and not self.flush():
                raise OSError('cannot archive while recording writes are pending: ' + self.error)
            folder = self.path.parent / 'recordings'
            folder.mkdir(exist_ok=True)
            sync_directory(self.path.parent)
            target = folder / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:12] + '.jsonl')
            if self.path.exists():
                # Link first, then remove the active name. A failed operation
                # always leaves at least one durable name for the old content.
                os.link(self.path, target)
                sync_directory(folder)
                if unlink:
                    self.path.unlink()
                    sync_directory(self.path.parent)
            if unlink and self.fd is not None:
                os.close(self.fd)
                self.fd = None
            return target

    def reset(self, started):
        with self.lock:
            tmp = self._prepare_file(started)
            new_fd = None
            try:
                archived = self.archive(unlink=False)
                new_fd = os.open(tmp, os.O_RDWR | os.O_APPEND)
                os.replace(tmp, self.path)
                # Once replace succeeds, the descriptor and metadata must
                # follow the active inode even if directory fsync fails.
                old_fd, self.fd = self.fd, new_fd
                new_fd = None
                if old_fd is not None:
                    os.close(old_fd)
                self.committed_size = os.fstat(self.fd).st_size
                self.started, self.last_timestamp = started, 0.0
                self.directory_pending = True
                if not self.flush():
                    raise OSError(self.error)
                return archived
            finally:
                if new_fd is not None:
                    os.close(new_fd)
                tmp.unlink(missing_ok=True)

    def pin(self):
        """Pin only acknowledged bytes, even if a reset follows immediately."""
        with self.lock:
            return {'path': self.path, 'fd': os.dup(self.fd), 'end': self.committed_size, 'last_timestamp': self.last_timestamp}

    def close(self):
        with self.lock:
            if self.fd is not None:
                if not self.flush():
                    raise OSError(self.error)
                os.close(self.fd)
                self.fd = None
            if self.lease_fd is not None:
                os.close(self.lease_fd)
                self.lease_fd = None
