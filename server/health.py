"""Detect an execution stall without waiting for the core mutex or HTTP loop."""
import json
import os
from pathlib import Path
import threading
import time


def clock():
    # Older Python/macOS monotonic() epochs differ between processes.
    return time.clock_gettime(time.CLOCK_MONOTONIC) if hasattr(time, 'clock_gettime') else time.monotonic()


def read_json(path):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value))
    os.replace(tmp, path)


def failure(reason):
    return {'ok': False, 'ended': True, 'valid': False, 'error': 'environment_failure',
            'reason': reason, 'retryable': False}


class EnvironmentFailure(RuntimeError):
    pass


class Health:
    def __init__(self, ticks, paused, directory):
        self.ticks, self.paused = ticks, paused
        self.directory = Path(directory)
        self.timeout = float(os.environ.get('QUNXIA_STALL_SECONDS', '15'))
        self.started = self.loop_at = self.tick_at = clock()
        self.tick = int(ticks())
        self.phase, self.phase_at = 'starting', self.started
        self.fault = None
        self.stop_event = threading.Event()

    def pulse(self):
        self.loop_at = clock()

    def set_phase(self, phase):
        self.phase, self.phase_at = phase, clock()

    def fail(self, reason):
        self.fault = self.fault or failure(reason)

    def check(self):
        if self.fault:
            raise EnvironmentFailure(self.fault['reason'])

    def sample(self):
        now, tick = clock(), int(self.ticks())  # atomic C load; no execution lock
        if tick != self.tick:
            self.tick, self.tick_at = tick, now
        if self.phase == 'starting':
            if now - self.started > 30:
                self.fail('startup_stalled')
        elif self.phase == 'finalizing':
            if now - self.phase_at > 300:
                self.fail('finalization_stalled')
        else:
            if now - self.loop_at > self.timeout:
                self.fail('event_loop_stalled')
            elif not self.paused() and now - self.tick_at > self.timeout:
                self.fail('core_stalled')
        return {'pid': os.getpid(), 'at': now, 'phase': self.phase, 'phase_at': self.phase_at,
                'core_ticks': tick, 'healthy': not self.fault and self.phase == 'running' and tick > 0 and not self.paused(),
                'failure': self.fault}

    def start(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / 'failure.json').unlink(missing_ok=True)
        def watch():
            while not self.stop_event.wait(.25):
                try:
                    state = self.sample()
                    write_json(self.directory / 'heartbeat.json', state)
                    if self.fault:
                        write_json(self.directory / 'failure.json', self.fault)
                        os._exit(75)
                except OSError:
                    os._exit(75)
        self.thread = threading.Thread(target=watch, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=1)
