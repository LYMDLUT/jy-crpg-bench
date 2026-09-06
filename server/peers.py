"""Bounded per-viewer sends; a slow socket cannot stop the shared pump."""
import asyncio
import contextlib


class Peer:
    """One bounded queue per viewer. Encoding never waits for a socket."""
    def __init__(self, ws, timeout, on_drop):
        self.ws, self.timeout, self.on_drop = ws, timeout, on_drop
        self.queue = asyncio.Queue(maxsize=8)
        self.bytes = 0
        self.closed = False
        self.close_task = None
        self.task = asyncio.create_task(self.send())

    def put(self, data, text=False):
        size = len(data.encode()) if text else len(data)
        if self.closed:
            return
        if self.queue.full() or self.bytes + size > 2 << 20:
            self.drop()
            return
        self.bytes += size
        self.queue.put_nowait((data, text, size))

    def drop(self):
        if not self.closed:
            self.closed = True
            self.on_drop(self.ws)
            self.task.cancel()
            self.close_task = asyncio.create_task(self.close_socket())

    async def close_socket(self):
        while not self.queue.empty():
            self.queue.get_nowait()
        self.bytes = 0
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await asyncio.wait_for(self.ws.close(code=1013, message=b"reconnect for a full frame"), 1)

    async def send(self):
        try:
            while True:
                data, text, size = await self.queue.get()
                try:
                    await asyncio.wait_for(self.ws.send_str(data) if text else self.ws.send_bytes(data),
                                           timeout=self.timeout)
                finally:
                    self.bytes = max(0, self.bytes - size)
        except (Exception, asyncio.CancelledError):
            pass
        finally:
            if not self.closed:
                self.closed = True
                self.on_drop(self.ws)
            if self.close_task is None:
                self.close_task = asyncio.create_task(self.close_socket())
            await self.close_task
