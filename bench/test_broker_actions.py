"""POST /session takes a decision budget.

A run under a decision budget ends after N decision calls; the minutes are
then the ceiling on how long the machine is held. The broker passes the budget
to the session process through QUNXIA_BENCH_ACTIONS and reports it back to the
caller, so a harness knows which budget the run is under.
"""
import pathlib
import sys
import unittest
from unittest import mock

import aiohttp.test_utils
from aiohttp import web

BENCH_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR))
import broker


class DecisionBudgetSessionTests(aiohttp.test_utils.AioHTTPTestCase):
    async def asyncSetUp(self):
        self.addCleanup(broker._results.clear)
        await super().asyncSetUp()

    def get_app(self):
        app = web.Application()
        app.add_routes([web.post("/session", broker.api_new)])
        app.on_startup.append(broker.open_http)
        app.on_cleanup.append(broker.close_http)
        return app

    async def test_the_budget_is_passed_down_and_reported(self):
        spawned = {"id": "abc123def456", "agent": "gpt-5", "token": "tok",
                   "ends_at": 1e9, "budget": 14400, "spawned": True,
                   "actions_budget": 1000}
        started = mock.AsyncMock(return_value=spawned)
        with mock.patch.object(broker, "start_session", new=started):
            response = await self.client.post(
                "/session", json={"agent": "gpt-5", "minutes": 240, "actions": 1000})
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body["actions_budget"], 1000)
        self.assertEqual(body["minutes"], 240)
        self.assertIn("1000 decision calls", body["message"])
        # positional: app, agent, budget seconds, publish, actions
        self.assertEqual(started.await_args.args[2:], (14400, True, 1000))

    async def test_no_budget_is_the_clock_as_before(self):
        spawned = {"id": "abc123def456", "agent": "gpt-5", "token": "tok",
                   "ends_at": 1e9, "budget": 1200, "spawned": True}
        started = mock.AsyncMock(return_value=spawned)
        with mock.patch.object(broker, "start_session", new=started):
            response = await self.client.post(
                "/session", json={"agent": "gpt-5", "minutes": 20})
        body = await response.json()
        self.assertIsNone(body["actions_budget"])
        self.assertIn("20 minutes", body["message"])
        self.assertNotIn("decision calls", body["message"])
        self.assertEqual(started.await_args.args[2:], (1200, True, 0))

    async def test_a_budget_out_of_range_is_refused(self):
        with mock.patch.object(broker, "start_session", new=mock.AsyncMock()) as started:
            for bad in (-1, broker.MAX_ACTIONS + 1):
                response = await self.client.post(
                    "/session", json={"agent": "gpt-5", "actions": bad})
                self.assertEqual(response.status, 400)
            response = await self.client.post(
                "/session", json={"agent": "gpt-5", "actions": "many"})
            self.assertEqual(response.status, 400)
            started.assert_not_awaited()


class SessionEnvTests(unittest.TestCase):
    def test_the_session_process_is_told_its_decision_budget(self):
        """The environment the worker starts under carries the budget."""
        seen = {}

        class Proc:
            def poll(self):
                return None

        def popen(argv, env=None, cwd=None):
            seen["env"] = env
            return Proc()

        async def go():
            with mock.patch.object(broker, "make_workdir", return_value=("g", "s")), \
                    mock.patch.object(broker.subprocess, "Popen", side_effect=popen), \
                    mock.patch.object(broker, "wait_healthy",
                                      new=mock.AsyncMock(return_value=False)), \
                    mock.patch.object(broker, "stop_worker"), \
                    mock.patch.object(broker, "archive_health"), \
                    mock.patch.object(broker.shutil, "rmtree"):
                try:
                    await broker._start_session({}, "gpt-5", 14400, True, 2500)
                except web.HTTPBadGateway:
                    pass
        import asyncio
        asyncio.run(go())
        self.assertEqual(seen["env"]["QUNXIA_BENCH_ACTIONS"], "2500")
        self.assertEqual(seen["env"]["QUNXIA_BENCH_BUDGET"], "14400")


if __name__ == "__main__":
    unittest.main()
