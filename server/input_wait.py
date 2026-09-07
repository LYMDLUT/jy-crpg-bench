"""Progress-aware frame waits with one fixed deadline per input action."""
import asyncio
from collections import deque
from contextvars import ContextVar

from health import clock, EnvironmentFailure

current_budget = ContextVar('input_budget', default=None)


class InputBudget:
    def __init__(self, frames, fps, health=None, wall_seconds=0,
                 check_runtime=lambda: None, clock_fn=clock, sleep=asyncio.sleep):
        self.clock, self.sleep = clock_fn, sleep
        self.health, self.check_runtime = health, check_runtime
        self.fps = max(1.0, fps)
        self.stall_seconds = health.timeout if health else 15.0
        self.started = self.clock()
        # Allow a transient pause up to the existing no-progress watchdog,
        # or sustained execution down to 1/5 nominal speed. Neither progress
        # nor a new key/release/gap/settle phase extends this action deadline.
        self.deadline = self.started + wall_seconds + max(
            self.stall_seconds + .5, frames / self.fps * 5 + .5)
        self.context = {}
        self.step_index = self.action_seq = None
        self.stages = deque(maxlen=64)
        self.completed_stages = []
        self.stage_at = self.started

    def stage(self, stage, **details):
        now = self.clock()
        if self.context:
            self.stages.append(dict(self.context, stage_elapsed=now - self.stage_at))
            self.completed_stages = list(self.stages)
        self.stage_at = now
        self.step_index = details.pop('step_index', self.step_index)
        self.context = dict(stage=stage, step_index=self.step_index,
                            action_seq=self.action_seq, **details)
        self.publish()

    def publish(self):
        if self.health:
            self.health.set_input(action_started=self.started,
                                  action_deadline=self.deadline, stage_started=self.stage_at,
                                  completed_stages=self.completed_stages, **self.context)

    def fail(self, reason, **details):
        if self.health:
            self.health.fail(reason, source='input_wait',
                             action_elapsed=self.clock() - self.started, **details)
        raise EnvironmentFailure(reason)

    def check(self):
        # Storage pauses and the benchmark's absolute budget take precedence;
        # reaching a frame target after either boundary is not success.
        self.check_runtime()
        if self.health:
            self.health.check()
        if self.clock() >= self.deadline:
            self.fail('input_frame_timeout')

    async def wait(self, frames, ticks):
        start = last = int(ticks())
        target = start + max(1, int(frames))
        wait_at = progressed_at = self.clock()
        self.context.update(start_tick=start, target_tick=target, wait_started=wait_at)
        self.publish()
        while True:
            # Record actual progress even when waking after the deadline.
            now, actual = self.clock(), int(ticks())
            self.context.update(actual_tick=actual, wait_elapsed=now - wait_at)
            self.publish()
            self.check()
            if actual != last:
                last, progressed_at = actual, now
            if actual >= target:
                return
            if now - progressed_at >= self.stall_seconds:
                self.fail('core_stalled', actual_tick=actual, target_tick=target,
                          no_progress_seconds=now - progressed_at)
            await self.sleep(min(.01, .5 / self.fps))

    async def wait_seconds(self, seconds):
        end = self.clock() + seconds
        while True:
            self.check()
            remaining = end - self.clock()
            if remaining <= 0:
                return
            await self.sleep(min(.1, remaining))
