"""Checkpoint lifecycle tests; every path belongs to a temporary session."""
import asyncio
import pathlib
import tempfile
import threading
import unittest
from unittest import mock

with mock.patch("ctypes.CDLL", return_value=mock.MagicMock()):
    import server


class CheckpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="qunxia-checkpoint-")
        self.addCleanup(temporary.cleanup)
        self.path = pathlib.Path(temporary.name) / "live.state"
        self.path.write_bytes(b"previous checkpoint")
        self.lib = mock.Mock()
        self.lib.core_width.return_value = self.lib.core_height.return_value = 1
        self.lib.core_load_state.return_value = True
        self.paused = False
        self.wait = mock.AsyncMock()

        def save(path):
            self.assertTrue(self.paused)
            self.assertEqual(self.path.read_bytes(), b"previous checkpoint")
            pathlib.Path(path.decode()).write_bytes(b"new checkpoint")
            return True

        self.lib.core_save_state.side_effect = save

        async def pause():
            self.paused = True

        def resume():
            self.paused = False

        patches = [
            mock.patch.object(server, "RESUME_STATE", str(self.path)),
            mock.patch.object(server, "AUTOSAVE_SECONDS", 0),
            mock.patch.object(server, "RESUME_WARMUP_FRAMES", 1500),
            mock.patch.object(server.warden, "ON", False),
            mock.patch.object(server, "api_lock", asyncio.Lock()),
            mock.patch.object(server, "LIB", self.lib),
            mock.patch.object(server, "wait_core_frames", self.wait),
            mock.patch.object(server, "pause_emulator", pause),
            mock.patch.object(server, "resume_emulator", resume),
            mock.patch.object(server, "send_keyframe", mock.AsyncMock()),
            mock.patch.dict(server.checkpoint, enabled=True, state="ready", restored=False,
                            saves=0, last_saved=None, error=None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def assert_preserved(self):
        self.assertEqual(self.path.read_bytes(), b"previous checkpoint")
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertFalse(self.paused)
        self.assertFalse(server.api_lock.locked())

    async def test_success_commits_only_after_execution_resumes(self):
        self.assertTrue(await server.save_checkpoint())
        self.assertEqual(self.path.read_bytes(), b"new checkpoint")
        self.assertEqual(self.wait.await_args_list, [mock.call(2), mock.call(2)])
        self.assertFalse(self.paused)
        self.assertEqual(server.checkpoint["saves"], 1)

    async def test_failed_save_preserves_old_checkpoint(self):
        self.lib.core_save_state.side_effect = lambda _path: False
        with self.assertRaises(RuntimeError):
            await server.save_checkpoint()
        self.assert_preserved()

    async def test_stalled_frames_before_or_after_save_preserve_old_checkpoint(self):
        for sequence in ([RuntimeError("stalled")], [None, RuntimeError("stalled")]):
            with self.subTest(waits=len(sequence)):
                self.wait.side_effect = sequence
                with self.assertRaisesRegex(RuntimeError, "stalled"):
                    await server.save_checkpoint()
                self.assert_preserved()

    async def test_cancelled_native_save_finishes_before_unpausing_and_discards_stage(self):
        started, release = threading.Event(), threading.Event()

        def save(path):
            started.set()
            release.wait(2)
            pathlib.Path(path.decode()).write_bytes(b"cancelled checkpoint")
            return True

        self.lib.core_save_state.side_effect = save
        task = asyncio.create_task(server.save_checkpoint())
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            task.cancel()
            await asyncio.sleep(.01)
            self.assertTrue(self.paused)
            self.assertFalse(task.done())
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assert_preserved()

    async def test_restore_waits_for_warmup_then_checks_execution(self):
        await server.resume_and_autosave()
        self.assertEqual(self.wait.await_args_list, [mock.call(1500), mock.call(2)])
        self.lib.core_load_state.assert_called_once_with(str(self.path).encode())
        server.send_keyframe.assert_awaited_once()
        self.assertEqual(server.checkpoint["state"], "ready")
        self.assertTrue(server.checkpoint["restored"])
        self.assert_preserved()

    async def test_failed_restore_blocks_input_and_never_autosaves(self):
        self.lib.core_load_state.return_value = False
        await server.resume_and_autosave()
        self.assertEqual(server.checkpoint["state"], "failed")
        self.assertFalse(await server.save_checkpoint())
        handler = mock.AsyncMock()
        response = await server.json_errors(
            mock.Mock(method="POST", path="/api/key"), handler)
        self.assertEqual(response.status, 503)
        handler.assert_not_awaited()
        self.assert_preserved()

    async def test_benchmark_never_reads_or_saves_a_checkpoint(self):
        with mock.patch.object(server.warden, "ON", True):
            await server.resume_and_autosave()
            self.assertFalse(await server.save_checkpoint())
        self.lib.core_load_state.assert_not_called()
        self.lib.core_save_state.assert_not_called()
        self.assert_preserved()


if __name__ == "__main__":
    unittest.main()
