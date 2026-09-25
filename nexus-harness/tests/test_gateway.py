"""The gateway forwards the game API and nothing else, and hides the token."""
import pathlib
import sys
import unittest

import aiohttp
from aiohttp import web

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from jy_crpg_nexus.gateway import GameGateway  # noqa: E402


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # A stand-in for the broker's play address: records what arrives.
        self.seen = []

        async def upstream(request):
            self.seen.append((request.method, request.path, dict(request.headers),
                              await request.text()))
            if request.path.endswith("/api/screen"):
                return web.json_response({"ok": True, "width": 320, "height": 200})
            if request.path.endswith("/api/key"):
                return web.json_response({"ok": True, "pressed": "enter"})
            return web.json_response({"ok": True, "path": request.path})

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", upstream)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = list(self.runner.sites)[0]._server.sockets[0].getsockname()[1]
        self.token_url = f"http://127.0.0.1:{port}/s/abc/t/SECRETTOKEN"
        self.gw = GameGateway(upstream=self.token_url, host="127.0.0.1")
        await self.gw.start()
        self.http = aiohttp.ClientSession()

    async def asyncTearDown(self):
        await self.http.close()
        await self.gw.stop()
        await self.runner.cleanup()

    def url(self, path):
        return f"http://127.0.0.1:{self.gw.port}{path}"

    async def test_forwards_look_and_press_to_the_token_address(self):
        async with self.http.get(self.url("/api/screen?scale=1")) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual((await r.json())["width"], 320)
        async with self.http.post(self.url("/api/key?image=0"), json={"key": "enter"},
                                  headers={"X-Agent": "spoof"}) as r:
            self.assertEqual(r.status, 200)
        methods = [(m, p) for m, p, _, _ in self.seen]
        self.assertEqual(methods, [("GET", "/s/abc/t/SECRETTOKEN/api/screen"),
                                   ("POST", "/s/abc/t/SECRETTOKEN/api/key")])
        # the agent's own X-Agent is dropped: the broker stamps the session's name
        self.assertNotIn("X-Agent", self.seen[1][2])
        self.assertEqual(self.seen[1][3], '{"key": "enter"}')

    async def test_refuses_everything_else(self):
        for method, path in (("POST", "/api/reset"), ("POST", "/api/save"),
                             ("GET", "/api/history"), ("GET", "/status"),
                             ("GET", "/api/catalog"), ("POST", "/session"),
                             ("GET", "/s/abc/t/SECRETTOKEN/api/screen"),
                             ("POST", "/api/screen"), ("GET", "/api/key")):
            async with self.http.request(method, self.url(path)) as r:
                self.assertEqual(r.status, 404, (method, path))
        self.assertEqual(self.seen, [])
        self.assertEqual(sum(self.gw.refused.values()), 9)

    async def test_health_is_answered_locally(self):
        async with self.http.get(self.url("/health")) as r:
            self.assertEqual(r.status, 200)
            self.assertTrue((await r.json())["gateway"])
        self.assertEqual(self.seen, [])

    async def test_stats_count_by_path(self):
        await (await self.http.get(self.url("/api/screen"))).release()
        await (await self.http.get(self.url("/api/screen"))).release()
        await (await self.http.get(self.url("/nope"))).release()
        s = self.gw.stats()
        self.assertEqual(s["requests"]["GET /api/screen"], 2)
        self.assertEqual(s["refused"]["GET /nope"], 1)
        self.assertEqual(s["port"], self.gw.port)

    async def test_upstream_down_is_502_not_a_crash(self):
        await self.runner.cleanup()
        async with self.http.get(self.url("/api/screen")) as r:
            self.assertEqual(r.status, 502)
        self.assertEqual(self.gw.errors, 1)


if __name__ == "__main__":
    unittest.main()
