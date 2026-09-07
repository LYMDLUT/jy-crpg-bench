import asyncio
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

import warden
with patch('ctypes.CDLL'):
    import server
from input_wait import InputBudget, current_budget


class DeadlineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old = deepcopy(warden.run)
        self.addCleanup(lambda: (warden.run.clear(), warden.run.update(self.old)))
        warden.run.update(playable=None, deadline=None, done=None, result=None)

    async def test_wall_clock_jumps_and_credit_do_not_move_deadline(self):
        with patch.object(warden, 'clock', return_value=100), patch.object(warden.time, 'time', return_value=1000):
            warden.playable_now()
        deadline = 100 + warden.BUDGET
        self.assertEqual(warden.run['deadline'], deadline)
        warden.run['credit'] = 10000
        for wall in (-100000, 100000000):
            with patch.object(warden, 'clock', return_value=deadline-.01), patch.object(warden.time, 'time', return_value=wall):
                warden.check_time()
                self.assertIsNone(warden.run['done'])
        with patch.object(warden, 'clock', return_value=deadline):
            warden.check_time()
        self.assertEqual(warden.run['done'], 'time')
        self.assertEqual(warden.run['deadline'], deadline)

    async def test_budget_expiry_in_hold_releases_and_blocks_next_key(self):
        now = [0.0]
        events = []
        async def sleep(_seconds):
            now[0] = 1.1
        class Core:
            def core_ticks(self): return int(now[0] * 60)
            def core_key_before_deadline(self, code, down, deadline):
                events.append((code, down, deadline))
                return True
            def core_key(self, code, down): events.append((code, down, None))
        warden.run.update(playable=1, deadline=1, last_clock=0)
        budget = InputBudget(144, 60, check_runtime=server.check_input_runtime,
                             clock_fn=lambda: now[0], sleep=sleep)
        token = current_budget.set(budget)
        try:
            with patch.object(warden, 'ON', True), patch.object(warden, 'clock', lambda: now[0]), patch.object(server, 'LIB', Core()), patch.object(server, 'key_event'):
                with self.assertRaises(server.web.HTTPGone):
                    await server.tap(13, 10, 'enter')
                    await server.tap(27, 10, 'escape')
                with self.assertRaises(server.web.HTTPGone):
                    server.send_key_down(27)
            self.assertEqual(events, [(13, True, 1), (13, False, None)])
            self.assertEqual(warden.run['done'], 'time')
        finally:
            current_budget.reset(token)

    async def test_pre_marked_time_still_validates_finalization(self):
        warden.run.update(playable=1, deadline=1, done='time')
        health = Mock()
        async def fail(_frames):
            raise RuntimeError('validation failure')
        with patch.object(warden, 'write_result') as write:
            await warden.warden({}, health, asyncio.Lock(), fail)
        write.assert_not_called()
        health.fail.assert_called_once_with('finalization_wait_failed', source='finalization', exception_type='RuntimeError')
