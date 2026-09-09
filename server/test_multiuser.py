"""Real child processes plus HTTP/WebSocket routes in temporary user trees."""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from multiuser import BackendManager, UserStore, build_app


class MultiuserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="qunxia-gateway-")
        self.root = Path(self.temp.name)
        game = self.root / "template"
        game.mkdir()
        (game / "PLAY.BAT").write_text("fixture")
        self.store = UserStore(self.root / "users", game)
        self.user = self.store.create("Existing player")
        self.manager = BackendManager(self.store, "unused",
            server=Path(__file__).parent / "test_fixtures/gateway_probe_server.py",
            startup_timeout=3, shutdown_timeout=3)
        self.client = TestClient(TestServer(build_app(self.store, self.manager)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def wait_for(self, predicate):
        for _ in range(100):
            if predicate():
                return
            await asyncio.sleep(.02)
        self.fail("worker did not reach the expected state")

    async def test_lobby_does_not_start_any_game(self):
        response = await self.client.get('/')
        self.assertEqual(response.status, 200)
        self.assertIn('Existing player', await response.text())
        self.assertEqual(self.manager.backends, {})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    async def test_concurrent_open_reuses_one_worker_and_private_paths(self):
        a, b = await asyncio.gather(self.manager.ensure(self.user), self.manager.ensure(self.user))
        self.assertIs(a, b)
        identity = self.user["id"]
        value = await (await self.client.get(f"/u/{identity}/status")).json()
        self.assertEqual(value["pid"], a.process.pid)
        self.assertEqual(value["prefix"], f"/u/{identity}")
        self.assertEqual(value["saves"], str(self.store.root / identity / "saves"))
        self.assertEqual(value["recording"], str(self.store.root / identity / "saves/recording.jsonl"))
        self.assertEqual(value["health"], str(self.store.root / identity / "saves/.health"))
        self.assertEqual(value["diagnostic"], str(self.store.root / identity / "saves/.health/incidents"))
        self.assertEqual(value["listen_host"], "127.0.0.1")
        self.assertEqual(value["bench"], "0")

    async def test_workers_never_share_health_or_diagnostic_paths(self):
        """Worker-local watchdog files stay private despite shared parent env."""
        second = self.store.create("Second player")

        async def status(backend):
            async with self.manager.client.get(f"http://127.0.0.1:{backend.port}/status") as response:
                self.assertEqual(response.status, 200)
                return await response.json()

        # First exercise the normal environment with two workers, then repeat
        # with gateway-level paths that would have been shared before the fix.
        first, second_backend = await asyncio.gather(
            self.manager.ensure(self.user), self.manager.ensure(second))
        values = await asyncio.gather(status(first), status(second_backend))
        self.assertNotEqual(values[0]["health"], values[1]["health"])
        self.assertNotEqual(values[0]["diagnostic"], values[1]["diagnostic"])
        for user, value in zip((self.user, second), values):
            saves = self.store.paths(user["id"])[2]
            self.assertEqual(value["health"], str(saves / ".health"))
            self.assertEqual(value["diagnostic"], str(saves / ".health" / "incidents"))

        shared = self.root / "shared-health"
        self.manager.environment.update(
            QUNXIA_HEALTH_DIR=str(shared),
            QUNXIA_DIAGNOSTIC_DIR=str(shared / "incidents"),
        )
        third = self.store.create("Third player")
        fourth = self.store.create("Fourth player")
        third_backend, fourth_backend = await asyncio.gather(
            self.manager.ensure(third), self.manager.ensure(fourth))
        values = await asyncio.gather(status(third_backend), status(fourth_backend))
        for user, value in zip((third, fourth), values):
            saves = self.store.paths(user["id"])[2]
            self.assertEqual(value["health"], str(saves / ".health"))
            self.assertEqual(value["diagnostic"], str(saves / ".health" / "incidents"))
            self.assertNotEqual(value["health"], str(shared))
            self.assertNotEqual(value["diagnostic"], str(shared / "incidents"))
        self.assertNotEqual(values[0]["health"], values[1]["health"])
        self.assertNotEqual(values[0]["diagnostic"], values[1]["diagnostic"])

    async def test_relative_core_and_server_paths_survive_the_worker_chdir(self):
        core = self.root / "probe-core.so"
        core.write_text("fixture core")
        script = self.root / "worker" / "probe.py"
        script.parent.mkdir()
        fixture = Path(__file__).parent / "test_fixtures/gateway_probe_server.py"
        script.write_text("import os, pathlib, runpy\n"
                          "assert pathlib.Path(os.environ['QUNXIA_CORE']).is_file()\n"
                          f"runpy.run_path({str(fixture.resolve())!r}, run_name='__main__')\n")
        for relative_core, relative_server in ((True, False), (False, True), (True, True)):
            with self.subTest(core=relative_core, server=relative_server):
                await self.client.close()
                self.manager = BackendManager(self.store,
                    os.path.relpath(core) if relative_core else core,
                    server=os.path.relpath(script) if relative_server else script,
                    startup_timeout=3, shutdown_timeout=3)
                self.client = TestClient(TestServer(build_app(self.store, self.manager)))
                await self.client.start_server()
                backend = await self.manager.ensure(self.user)
                self.assertIsNone(backend.process.poll())
                self.assertEqual(Path(self.manager.core), core.resolve())
                self.assertEqual(self.manager.server, script.resolve())

    async def test_existing_ids_survive_restart_and_new_users_have_separate_game_trees(self):
        second = await (await self.client.post("/api/users", json={"name": "Second player"})).json()
        first_game = self.store.paths(self.user["id"])[1] / "PLAY.BAT"
        first_game.write_text("private progress")
        self.assertEqual((self.store.paths(second["id"])[1] / "PLAY.BAT").read_text(), "fixture")
        reloaded = UserStore(self.store.root)
        self.assertEqual(reloaded.get(self.user["id"]), self.user)
        self.assertEqual([u["name"] for u in reloaded.all()], ["Existing player", "Second player"])
        self.assertEqual((await (await self.client.get("/api/users")).json())["users"], 2)

    async def test_subpath_assets_streamed_recording_and_websocket_close(self):
        prefix = f'/u/{self.user["id"]}'
        response = await self.client.get(prefix, allow_redirects=False)
        self.assertEqual(response.headers["Location"], prefix + "/")
        for path in ("/", "/recording.js", "/api/help"):
            self.assertEqual(await (await self.client.get(prefix + path)).text(), path)
        response = await self.client.get(prefix + "/api/recording?format=jsonl")
        self.assertEqual(await response.read(), b"old recording bytes\n")
        ws = await self.client.ws_connect(prefix + "/ws")
        await ws.send_str("hello")
        self.assertEqual((await ws.receive(timeout=1)).data, "hello")
        await ws.send_str("close")
        self.assertEqual((await ws.receive(timeout=1)).type, WSMsgType.CLOSE)
        await ws.close()

    async def test_cancelled_start_reaps_only_its_child_and_releases_the_lease(self):
        self.manager.environment["PROBE_PHASE"] = "warming"
        task = asyncio.create_task(self.manager.ensure(self.user))
        await self.wait_for(lambda: bool(self.manager.backends))
        backend = self.manager.backends[self.user["id"]]
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNotNone(backend.process.poll())
        self.assertTrue(backend.log.closed)
        self.assertIsNone(backend.parent_pipe)
        self.assertFalse(backend.marker.exists())
        with (self.store.paths(self.user["id"])[0] / ".backend.lock").open("r") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)

    async def test_parent_pipe_eof_exits_the_worker_cleanly(self):
        backend = await self.manager.ensure(self.user)
        os.close(backend.parent_pipe)
        backend.parent_pipe = None
        await self.wait_for(lambda: backend.process.poll() is not None)
        self.assertEqual(backend.process.returncode, 0)
        self.assertTrue((self.store.paths(self.user["id"])[2] / "clean-exit").is_file())

    async def test_shutdown_closes_active_websockets_before_request_drain(self):
        ws = await self.client.ws_connect(f'/u/{self.user["id"]}/ws')
        await ws.send_str("still open")
        self.assertEqual((await ws.receive(timeout=1)).data, "still open")
        await asyncio.wait_for(self.client.server.app.shutdown(), timeout=3)
        self.assertEqual((await ws.receive(timeout=1)).type, WSMsgType.CLOSE)
        await ws.close()

    async def test_shutdown_interrupts_a_request_waiting_for_worker_warmup(self):
        self.manager.environment["PROBE_PHASE"] = "warming"
        self.manager.startup_timeout = 30
        request = asyncio.create_task(self.client.get(f'/u/{self.user["id"]}/'))
        await self.wait_for(lambda: bool(self.manager.backends))
        backend = self.manager.backends[self.user["id"]]
        await self.client.server.app.shutdown()
        response = await asyncio.wait_for(request, timeout=3)
        self.assertEqual(response.status, 503)
        self.assertIsNotNone(backend.process.poll())
        self.assertFalse(backend.marker.exists())

    async def test_stale_marker_with_a_live_foreign_pid_is_discarded_not_signalled(self):
        # A marker left by an unclean exit may name a PID that now belongs to
        # an unrelated process (here: this test). The free lease proves the old
        # worker is gone, so the session starts and the marker is rewritten.
        marker = self.store.paths(self.user["id"])[0] / "backend.json"
        marker.write_text(json.dumps({"pid": os.getpid(), "port": 1}))
        backend = await self.manager.ensure(self.user)
        self.assertEqual(json.loads(marker.read_text())["pid"], backend.process.pid)
        self.assertNotEqual(backend.process.pid, os.getpid())

    async def test_another_gateway_and_escaping_user_paths_are_refused(self):
        other = BackendManager(self.store, "unused")
        with self.assertRaisesRegex(RuntimeError, "another gateway"):
            await other.start()
        self.assertIsNone(self.store.get("../template"))
        identity = "x" * 24
        (self.store.root / identity).symlink_to(self.root / "template")
        self.assertIsNone(self.store.get(identity))


if __name__ == "__main__":
    unittest.main()
