"""Detect an execution stall without waiting for the core mutex or HTTP loop."""
from collections import deque
import faulthandler
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
        self.lock = threading.RLock()
        self.history = deque(maxlen=64)
        self.input = {}
        self.incident = None
        self.diagnostic_dir = Path(os.environ.get('QUNXIA_DIAGNOSTIC_DIR',
            str(self.directory / 'incidents' / f'{os.getpid()}-{time.time_ns()}')))
        self.stop_event = threading.Event()

    def pulse(self):
        with self.lock:
            self.loop_at = clock()

    def set_phase(self, phase):
        with self.lock:
            self.phase, self.phase_at = phase, clock()

    def set_input(self, **details):
        with self.lock:
            self.input = details

    def fail(self, reason, source='runtime', **details):
        # Freeze the first failure before key cleanup or another sampler can
        # overwrite its context. Disk I/O is left to the watchdog thread.
        with self.lock:
            if self.fault is None:
                self.fault = dict(failure(reason), source=source)
                self.incident = dict(self.snapshot(), input=dict(self.input),
                                     details=details, samples=list(self.history))

    def check(self):
        if self.fault:
            raise EnvironmentFailure(self.fault['reason'])

    def sample(self):
        with self.lock:
            return self._sample()

    def _sample(self):
        now, tick = clock(), int(self.ticks())  # atomic C load; no execution lock
        if tick != self.tick:
            self.tick, self.tick_at = tick, now
        if self.phase == 'starting':
            if now - self.started > 30:
                self.fail('startup_stalled', source='startup_watchdog')
        elif self.phase == 'finalizing':
            if now - self.phase_at > 300:
                self.fail('finalization_stalled', source='finalization_watchdog')
        else:
            if now - self.loop_at > self.timeout:
                self.fail('event_loop_stalled', source='event_loop_watchdog')
            elif not self.paused() and now - self.tick_at > self.timeout:
                self.fail('core_stalled', source='tick_watchdog')
        state = self.snapshot()
        self.history.append({k: v for k, v in state.items() if k != 'failure'})
        return state

    def snapshot(self):
        """Read status without advancing the watchdog's samples or timers."""
        with self.lock:
            now, tick = clock(), int(self.ticks())
            return {'pid': os.getpid(), 'at': now, 'phase': self.phase, 'phase_at': self.phase_at,
                'last_tick_at': self.tick_at, 'last_loop_at': self.loop_at,
                'core_ticks': tick, 'healthy': not self.fault and self.phase == 'running' and tick > 0 and not self.paused(),
                'failure': self.fault}

    def persist_incident(self):
        if self.incident is None:
            return
        write_json(self.diagnostic_dir / 'incident.json', self.incident)
        with (self.diagnostic_dir / 'threads.txt').open('w') as output:
            faulthandler.dump_traceback(file=output, all_threads=True)

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
                        self.persist_incident()
                        os._exit(75)
                except OSError:
                    os._exit(75)
        self.thread = threading.Thread(target=watch, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=1)
