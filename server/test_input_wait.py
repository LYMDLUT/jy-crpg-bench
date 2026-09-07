import asyncio
import tempfile
import unittest
from unittest.mock import patch

from health import Health, EnvironmentFailure
from input_wait import InputBudget, current_budget


class FakeClock:
    def __init__(self, rate=60, pause=0, jump=0):
        self.now, self.rate, self.pause, self.jump = 0.0, rate, pause, jump

    def clock(self):
        return self.now

    def ticks(self):
        return int(max(0, self.now - self.pause) * self.rate)

    async def sleep(self, seconds):
        self.now += self.jump or seconds


class InputWaitTests(unittest.IsolatedAsyncioTestCase):
    def budget(self, fake, frames=132, **kwargs):
        return InputBudget(frames, 60, clock_fn=fake.clock, sleep=fake.sleep, **kwargs)

    async def test_normal_slow_and_transient_pause_keep_original_target(self):
        for rate, pause in ((60, 0), (16, 0), (16, 2), (60, 10)):
            with self.subTest(rate=rate, pause=pause):
                fake = FakeClock(rate, pause)
                budget = self.budget(fake)
                await budget.wait(10, fake.ticks)
                self.assertEqual(budget.context['target_tick'], 10)
                self.assertEqual(fake.ticks(), 10)
                self.assertLess(fake.now, budget.deadline)

    async def test_stall_after_nominal_progress_is_a_core_stall(self):
        class LateStall(FakeClock):
            stop = 0.0

            def ticks(self):
                return int(min(self.now, self.stop) * self.rate)

        for frames, stop in ((12, .1), (1000, 3.0)):
            with self.subTest(frames=frames, stop=stop):
                fake = LateStall(60)
                fake.stop = stop
                budget = self.budget(fake, frames=frames)
                with self.assertRaisesRegex(EnvironmentFailure, 'core_stalled'):
                    await budget.wait(frames, fake.ticks)
                self.assertLess(fake.now, budget.deadline)

    async def test_zero_ticks_are_a_stall_but_drip_feed_hits_fixed_action_cap(self):
        for rate, reason in ((0, 'core_stalled'), (.1, 'input_frame_timeout')):
            fake = FakeClock(rate)
            budget = self.budget(fake)
            with self.assertRaisesRegex(EnvironmentFailure, reason):
                await budget.wait(10, fake.ticks)
            self.assertLess(fake.now, budget.deadline + .05)

    async def test_hold_release_gap_and_settle_share_one_deadline(self):
        fake = FakeClock(1)
        budget = self.budget(fake)
        deadline = budget.deadline
        for stage, frames in (('hold', 10), ('release', 2), ('gap', 2)):
            budget.stage(stage, step_index=0)
            await budget.wait(frames, fake.ticks)
            self.assertEqual(budget.deadline, deadline)
        budget.stage('settle')
        # 14 s of drip-fed progress so far; four more ticks would end at 18 s,
        # past the 17.7 s deadline this budget was given.
        with self.assertRaisesRegex(EnvironmentFailure, 'input_frame_timeout'):
            await budget.wait(4, fake.ticks)
        self.assertLess(fake.now, deadline + .05)

    async def test_target_reached_after_deadline_is_not_success(self):
        fake = FakeClock(jump=20)
        with self.assertRaisesRegex(EnvironmentFailure, 'input_frame_timeout'):
            await self.budget(fake).wait(1, fake.ticks)

    async def test_runtime_expiry_precedes_reached_target_and_frame_timeout(self):
        fake = FakeClock(jump=20)
        def check():
            if fake.now >= 1:
                raise TimeoutError('run ended')
        with self.assertRaisesRegex(TimeoutError, 'run ended'):
            await self.budget(fake, check_runtime=check).wait(1, fake.ticks)

    async def test_explicit_wait_checks_deadline_even_after_late_wakeup(self):
        fake = FakeClock(jump=20)
        with self.assertRaisesRegex(EnvironmentFailure, 'input_frame_timeout'):
            await self.budget(fake).wait_seconds(.1)

    async def test_failure_captures_target_actual_key_and_source(self):
        fake = FakeClock(.1)
        with tempfile.TemporaryDirectory() as root:
            health = Health(fake.ticks, lambda: False, root)
            budget = self.budget(fake, health=health)
            budget.stage('hold', key='kp7', step_index=2)
            with self.assertRaises(EnvironmentFailure):
                await budget.wait(10, fake.ticks)
            health.set_input()
            self.assertEqual(health.fault['source'], 'input_wait')
            self.assertEqual(health.incident['input']['key'], 'kp7')
            self.assertEqual(health.incident['input']['step_index'], 2)
            self.assertEqual(health.incident['input']['target_tick'], 10)
            self.assertEqual(health.incident['input']['actual_tick'], 1)


with patch('ctypes.CDLL'):
    import server


class KeyCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_late_hold_releases_once_and_does_not_start_next_key(self):
        fake = FakeClock(jump=20)
        budget = InputBudget(144, 60, clock_fn=fake.clock, sleep=fake.sleep)
        events = []
        class Core:
            core_ticks = staticmethod(fake.ticks)
            def core_key_before_deadline(self, code, down, deadline):
                events.append((code, down))
                return True
            def core_key(self, code, down):
                events.append((code, down))
        token = current_budget.set(budget)
        try:
            with patch.object(server, 'LIB', Core()), patch.object(server, 'key_event'):
                with self.assertRaisesRegex(EnvironmentFailure, 'input_frame_timeout'):
                    await server.tap(13, 10, 'enter')
                    await server.tap(27, 10, 'escape')
            self.assertEqual(events, [(13, True), (13, False)])
        finally:
            current_budget.reset(token)

    async def test_cancellation_releases_rest_key(self):
        from unittest.mock import Mock
        core = Mock()
        async def cancel(_frames):
            raise asyncio.CancelledError
        with patch.object(server, 'LIB', core), patch.object(server, 'key_event'), patch.object(server, 'wait_core_frames', cancel):
            with self.assertRaises(asyncio.CancelledError):
                await server.tap(13, 10, 'enter')
        self.assertEqual(core.core_key.call_args_list, [((13, True),), ((13, False),)])
