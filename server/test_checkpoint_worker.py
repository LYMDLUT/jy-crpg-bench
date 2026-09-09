"""Real worker restart and native progress restoration, using the probe core."""
import json
import shutil
import struct
import unittest

import test_worker_health as worker
from test_worker_health import request, stop_process, wait_for


@unittest.skipUnless(shutil.which("cc"), "C compiler required")
class CheckpointWorkerTests(unittest.TestCase):
    setUpClass = classmethod(worker.WorkerIntegrationTests.setUpClass.__func__)
    setUp = worker.WorkerIntegrationTests.setUp
    launch = worker.WorkerIntegrationTests.launch
    healthy = worker.WorkerIntegrationTests.healthy

    def checkpoint(self):
        return self.folder / "live.state"

    def launch_checkpoint(self, **extra):
        return self.launch(**dict({
            "QUNXIA_RESUME_STATE": str(self.checkpoint()),
            "QUNXIA_AUTOSAVE_SECONDS": "0.15",
            "QUNXIA_RESUME_WARMUP_FRAMES": "6",
            "QUNXIA_SNAPSHOT_EVERY": "0",
            "PROBE_STATEFUL": "1",
        }, **extra))

    def phase(self, phase):
        value = self.healthy()
        return value if value and value["checkpoint"]["state"] == phase else None

    def count(self, path=None):
        return struct.unpack_from("=i", (path or self.checkpoint()).read_bytes(), 4)[0]

    def seed(self, count):
        self.checkpoint().write_bytes(b"{" + bytes(3) + struct.pack("=i", count) + bytes(8))

    def test_restore_autosave_restart_and_shutdown_keep_native_progress(self):
        self.seed(7)
        first = self.launch_checkpoint()
        ready = wait_for(lambda: self.phase("ready"))
        self.assertTrue(ready["checkpoint"]["restored"])
        self.assertEqual(request(self.port, "/api/key", {"key": "enter"})[0], 200)
        wait_for(lambda: self.count() == 8)
        stop_process(first, timeout=5)
        self.assertEqual(first.returncode, 0)
        second = self.launch_checkpoint(QUNXIA_AUTOSAVE_SECONDS="0")
        wait_for(lambda: self.phase("ready"))
        self.assertEqual(request(self.port, "/api/key", {"key": "enter"})[0], 200)
        self.assertEqual(request(self.port, "/api/save", {"name": "witness"})[0], 200)
        self.assertEqual(self.count(self.folder / "slots/witness.state"), 9)
        stop_process(second, timeout=5)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(self.count(), 9)
        self.assertEqual(list(self.folder.glob("live.state.*.pending")), [])

    def test_failed_restore_preserves_file_and_refuses_actions(self):
        original = b"unreadable checkpoint"
        self.checkpoint().write_bytes(original)
        process = self.launch_checkpoint()
        wait_for(lambda: self.phase("failed"))
        code, body = request(self.port, "/api/key", {"key": "enter"})
        self.assertEqual(code, 503)
        self.assertEqual(json.loads(body)["error"], "session_not_ready")
        stop_process(process, timeout=5)
        self.assertEqual(self.checkpoint().read_bytes(), original)

    def test_input_is_blocked_during_warmup_and_exit_preserves_checkpoint(self):
        self.seed(7)
        original = self.checkpoint().read_bytes()
        process = self.launch_checkpoint(QUNXIA_RESUME_WARMUP_FRAMES="600")
        wait_for(lambda: self.phase("warming"))
        self.assertEqual(request(self.port, "/api/key", {"key": "enter"})[0], 503)
        stop_process(process, timeout=5)
        self.assertEqual(self.checkpoint().read_bytes(), original)

    def test_benchmark_ignores_even_invalid_autosave_configuration(self):
        self.seed(7)
        original = self.checkpoint().read_bytes()
        process = self.launch_checkpoint(QUNXIA_BENCH="1", QUNXIA_AUTOSAVE_SECONDS="invalid",
                                         QUNXIA_RESUME_WARMUP_FRAMES="invalid")
        ready = wait_for(self.healthy)
        self.assertEqual(ready["checkpoint"]["state"], "disabled")
        self.assertFalse(ready["checkpoint"]["enabled"])
        self.assertEqual(request(self.port, "/api/load", {"name": "live"})[0], 404)
        stop_process(process, timeout=5)
        self.assertEqual(self.checkpoint().read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
