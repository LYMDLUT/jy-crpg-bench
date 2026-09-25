"""The decision budget and the harness-closed run.

A wall clock hands a fast model far more decisions than a slow one. With
QUNXIA_BENCH_ACTIONS the run ends after that many decision calls, and the
clock only bounds how long the machine is held. A harness that counts tokens
where the model is called can close the run itself through /api/end, so a
spent token budget is recorded as such and not as a stall.
"""
import asyncio
from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

import aiohttp.test_utils
from aiohttp import web

import warden
with patch('ctypes.CDLL'):
    import server


class ActionBudgetTests(unittest.TestCase):
    def setUp(self):
        self.old = deepcopy(warden.run)
        self.addCleanup(lambda: (warden.run.clear(), warden.run.update(self.old)))
        warden.run.update(playable=None, deadline=None, done=None, result=None,
                          actions=0, first=None, last=None, gaps=[], keys={},
                          key_events=0, input_frames=0, wait_calls=0, end_detail="")

    def test_no_budget_means_clock_only(self):
        with patch.object(warden, 'ACTIONS', 0):
            warden.playable_now()
            for _ in range(50):
                warden.note_action(['up'])
            self.assertIsNone(warden.run['done'])
            self.assertIsNone(warden.actions_left())
            self.assertEqual(warden.metrics()['budget_kind'], 'time')
            self.assertIsNone(warden.metrics()['actions_budget'])

    def test_last_allowed_decision_executes_then_the_run_ends(self):
        with patch.object(warden, 'ACTIONS', 3):
            warden.playable_now()
            warden.note_action(['up'])
            self.assertEqual(warden.actions_left(), 2)
            warden.note_action([])            # a wait is a decision too
            self.assertIsNone(warden.run['done'])
            warden.note_action(['enter'])     # the third and last
            self.assertEqual(warden.run['done'], 'actions')
            self.assertEqual(warden.actions_left(), 0)
            self.assertEqual(warden.run['actions'], 3)
            m = warden.metrics()
            self.assertEqual(m['reason'], 'actions')
            self.assertEqual(m['budget_kind'], 'actions')
            self.assertEqual(m['actions_budget'], 3)
            self.assertIn('3 decisions', warden.why_text())

    def test_timing_reports_the_decision_budget_while_live(self):
        with patch.object(warden, 'ACTIONS', 10), patch.object(warden, 'ON', True):
            warden.playable_now()
            warden.note_action(['up'])
            t = warden.timing()
            self.assertEqual(t['actions_budget'], 10)
            self.assertEqual(t['actions_left'], 9)

    def test_the_clock_still_ends_a_run_under_a_decision_budget(self):
        with patch.object(warden, 'ACTIONS', 1000):
            with patch.object(warden, 'clock', return_value=100):
                warden.playable_now()
            with patch.object(warden, 'clock', return_value=100 + warden.BUDGET):
                warden.check_time()
            self.assertEqual(warden.run['done'], 'time')


class EndRunTests(unittest.TestCase):
    def setUp(self):
        self.old = deepcopy(warden.run)
        self.addCleanup(lambda: (warden.run.clear(), warden.run.update(self.old)))
        warden.run.update(playable=None, deadline=None, done=None, result=None,
                          actions=0, end_detail="")

    def test_not_before_playable(self):
        self.assertFalse(warden.end_run('tokens'))
        self.assertIsNone(warden.run['done'])

    def test_tokens_and_client_exit_are_recorded_with_detail(self):
        warden.playable_now()
        self.assertTrue(warden.end_run('tokens', 'prompt+completion 1000000 >= 1000000'))
        self.assertEqual(warden.run['done'], 'tokens')
        self.assertIn('token budget', warden.why_text())
        self.assertIn('1000000', warden.why_text())
        self.assertEqual(warden.metrics()['end_detail'], 'prompt+completion 1000000 >= 1000000')
        # a second close does nothing
        self.assertFalse(warden.end_run('client_exit'))
        self.assertEqual(warden.run['done'], 'tokens')

    def test_unknown_reason_is_refused(self):
        warden.playable_now()
        with self.assertRaises(ValueError):
            warden.end_run('bored')
        self.assertIsNone(warden.run['done'])

    def test_detail_is_bounded(self):
        warden.playable_now()
        warden.end_run('client_exit', 'x' * 1000)
        self.assertEqual(len(warden.run['end_detail']), 200)


class ApiEndTests(aiohttp.test_utils.AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        app.add_routes([web.post("/api/end", server.api_end)])
        return app

    def setUp(self):
        super().setUp()
        self.old = deepcopy(warden.run)
        self.addCleanup(lambda: (warden.run.clear(), warden.run.update(self.old)))
        warden.run.update(playable=None, deadline=None, done=None, result=None,
                          actions=0, end_detail="")

    async def test_without_the_operator_token_the_route_does_not_exist(self):
        with patch.dict(os.environ, {"QUNXIA_RESET_TOKEN": "secret"}), \
                patch.object(warden, 'ON', True):
            warden.playable_now()
            r = await self.client.post("/api/end", json={"reason": "tokens"})
            self.assertEqual(r.status, 404)
            r = await self.client.post("/api/end", json={"reason": "tokens"},
                                       headers={"X-Reset-Token": "wrong"})
            self.assertEqual(r.status, 404)
            self.assertIsNone(warden.run['done'])

    async def test_the_operator_closes_the_run(self):
        with patch.dict(os.environ, {"QUNXIA_RESET_TOKEN": "secret"}), \
                patch.object(warden, 'ON', True):
            warden.playable_now()
            warden.note_action(['up'])
            r = await self.client.post("/api/end",
                                       json={"reason": "tokens", "detail": "spent"},
                                       headers={"X-Reset-Token": "secret"})
            self.assertEqual(r.status, 200)
            body = await r.json()
            self.assertEqual(body, {"ok": True, "ended": True, "reason": "tokens", "actions": 1})
            self.assertEqual(warden.run['done'], 'tokens')

    async def test_a_bad_reason_is_a_400(self):
        with patch.dict(os.environ, {"QUNXIA_RESET_TOKEN": "secret"}), \
                patch.object(warden, 'ON', True):
            warden.playable_now()
            r = await self.client.post("/api/end", json={"reason": "bored"},
                                       headers={"X-Reset-Token": "secret"})
            self.assertEqual(r.status, 400)
            self.assertIsNone(warden.run['done'])

    async def test_not_a_benchmark_run(self):
        with patch.dict(os.environ, {"QUNXIA_RESET_TOKEN": "secret"}), \
                patch.object(warden, 'ON', False):
            r = await self.client.post("/api/end", json={"reason": "tokens"},
                                       headers={"X-Reset-Token": "secret"})
            self.assertEqual(r.status, 400)


if __name__ == "__main__":
    unittest.main()
