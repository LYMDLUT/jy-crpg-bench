"""The one door from the container to the game.

The container's firewall lets out exactly one TCP destination: this proxy, on
the Host. It forwards a short list of game API paths to the session's play
address at the broker and answers everything else 404. Three things follow:

- the play token - the credential that would let a shell in the container
  drive the run from anywhere, or a later run drive this one - never enters
  the container; the container knows only ``http://<host>:<port>``;
- the broker's other routes (the catalogue, the live board, other sessions'
  spectator views) are not reachable even in principle, whatever the broker's
  own checks say;
- the record has a per-path count of what the agent asked for, from a process
  the agent could not touch.

It is small on purpose: aiohttp, one handler, an allowlist.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import re
from typing import Any

import aiohttp
from aiohttp import web

logger = logging.getLogger(__name__)

# What the benchmark profile of the MCP server uses, and the help page it
# reads at start. Save/load/reset are refused by the game server in a
# benchmark run anyway; keeping them off the list here means a shell in the
# container cannot even ask.
ALLOWED = (
    ("GET", re.compile(r"^/api/help$")),
    ("GET", re.compile(r"^/api/screen$")),
    ("GET", re.compile(r"^/api/keys$")),
    ("POST", re.compile(r"^/api/key$")),
    ("GET", re.compile(r"^/health$")),
)

# Headers that are the proxy's business, not the client's.
_DROP = {"host", "content-length", "transfer-encoding", "connection",
         "x-reset-token", "x-agent", "x-forwarded-host", "x-forwarded-proto",
         "origin", "referer", "cookie"}


class GameGateway:
    def __init__(self, upstream: str, host: str = "0.0.0.0", port: int = 0,
                 request_timeout: float = 300):
        self.upstream = upstream.rstrip("/")
        self.host = host
        self.port = port
        self.request_timeout = request_timeout
        self._runner: web.AppRunner | None = None
        self._http: aiohttp.ClientSession | None = None
        self.counts: collections.Counter = collections.Counter()
        self.refused: collections.Counter = collections.Counter()
        self.errors = 0

    def _allowed(self, method: str, path: str) -> bool:
        return any(m == method and rx.match(path) for m, rx in ALLOWED)

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        path = request.path
        if path == "/health" and request.method == "GET":
            # Answered here: it is the probe's proof that the gateway is up,
            # and it must not depend on the broker.
            self.counts["GET /health"] += 1
            return web.json_response({"ok": True, "gateway": True})
        if not self._allowed(request.method, path):
            self.refused[f"{request.method} {path}"] += 1
            return web.json_response(
                {"ok": False, "error": "not part of the game API",
                 "hint": "look and press are the only actions; the MCP server makes them"},
                status=404)
        self.counts[f"{request.method} {path}"] += 1
        assert self._http is not None
        url = self.upstream + path
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP}
        body = await request.read()
        try:
            async with self._http.request(
                    request.method, url, params=request.query, data=body, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.request_timeout)) as r:
                payload = await r.read()
                out_headers = {k: v for k, v in r.headers.items()
                               if k.lower() in ("content-type", "cache-control")}
                return web.Response(body=payload, status=r.status, headers=out_headers)
        except Exception as exc:
            self.errors += 1
            logger.warning("gateway upstream error on %s: %r", path, exc)
            return web.json_response({"ok": False, "error": f"game unreachable: {exc!r}"}, status=502)

    async def start(self) -> None:
        self._http = aiohttp.ClientSession()
        app = web.Application(client_max_size=1 << 20)
        app.router.add_route("*", "/{tail:.*}", self._handle)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        # The port actually bound, when 0 was asked for.
        for s in self._runner.sites:
            server = getattr(s, "_server", None)
            if server and server.sockets:
                self.port = server.sockets[0].getsockname()[1]
                break
        logger.info("game gateway on %s:%s -> %s", self.host, self.port, self.upstream)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        if self._http is not None:
            await self._http.close()
            self._http = None

    def stats(self) -> dict[str, Any]:
        return {"port": self.port, "requests": dict(self.counts),
                "refused": dict(self.refused), "upstream_errors": self.errors}
