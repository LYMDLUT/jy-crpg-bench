import importlib.util
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


SERVER_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIR))
SPEC = importlib.util.spec_from_file_location("qunxia_game_server", SERVER_DIR / "server.py")
game_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(game_server)


class BigMapSignalTests(unittest.TestCase):
    def setUp(self):
        self.original = dict(game_server.world)
        game_server.world.update(
            scenes=1,
            bigmap=False,
            checked_refs=False,
            dark=False,
        )

    def tearDown(self):
        game_server.world.clear()
        game_server.world.update(self.original)

    def test_reference_cannot_latch_before_a_full_black_boundary(self):
        reference = game_server.BIGMAP_REFS[0]
        interior = bytes((value + 32) % 256 for value in reference)

        game_server.note_bigmap(interior)
        self.assertTrue(game_server.world["checked_refs"])
        self.assertFalse(game_server.world["bigmap"])

        game_server.note_bigmap(reference)
        self.assertFalse(game_server.world["bigmap"])

        game_server.world["scenes"] = 2
        game_server.note_bigmap(reference)
        self.assertTrue(game_server.world["bigmap"])

    def test_transition_is_committed_before_bigmap_detection(self):
        reference = game_server.BIGMAP_REFS[0]
        interior = bytes((value + 32) % 256 for value in reference)
        game_server.note_bigmap(interior)
        game_server.world["dark"] = True

        game_server.note_move()
        game_server.note_bigmap(reference)

        self.assertEqual(game_server.world["scenes"], 2)
        self.assertTrue(game_server.world["bigmap"])


class InputContractTests(unittest.IsolatedAsyncioTestCase):
    class Request:
        def __init__(self, body, query=None):
            self.body = body
            self.query = query or {}
            self.headers = {}
            self.remote = "127.0.0.1"

        async def json(self):
            return self.body

    async def test_repeat_and_hold_are_bounded_not_clamped(self):
        action = AsyncMock(return_value="ok")
        with patch.object(game_server, "run_action", action):
            response = await game_server.api_key(self.Request({
                "key": "enter", "times": 1000000, "hold": 1000000,
            }))
        self.assertEqual(response.status, 400)
        action.assert_not_awaited()
        with patch.object(game_server, "run_action", action):
            await game_server.api_key(self.Request({
                "key": "enter", "times": 3, "hold": 20,
            }))
        steps = action.await_args.args[1]
        self.assertEqual(len(steps), 3 * 2 - 1)
        key_steps = [step for step in steps if len(step) > 2]
        self.assertTrue(all(step[1] == 20 for step in key_steps))

    async def test_sequence_honors_gap_and_stable_parameters(self):
        action = AsyncMock(return_value="ok")
        request = self.Request({"keys": ["kp3", "enter"], "gap": 17}, {"stable": "23"})
        with patch.object(game_server, "run_action", action):
            await game_server.api_keys(request)
        steps = action.await_args.args[1]
        self.assertEqual(steps[1], ("frames", 17))
        self.assertEqual(game_server.settle_options(request)["stable"], 23)

    async def test_sequence_requires_a_list(self):
        response = await game_server.api_keys(self.Request({"keys": "enter"}))
        self.assertEqual(response.status, 400)

    async def test_settle_budget_can_fit_reaction_and_stability(self):
        fake_lib = SimpleNamespace(
            core_fps=lambda: 60.0,
            fb_luma=lambda: 100,
            core_frame_hash=lambda: 2,
        )
        with (patch.object(game_server, "LIB", fake_lib),
              patch.object(game_server, "wait_core_frames", AsyncMock())):
            waited, changed = await game_server.settle(
                1, react=30, stable=5, maxframes=1)
        self.assertTrue(changed)
        self.assertEqual(waited, 6)

    async def test_benchmark_hides_snapshots_and_counts_in_action_looks(self):
        with patch.object(game_server.warden, "ON", True):
            for handler, body in ((game_server.api_slots, None),
                                  (game_server.api_save, {"name": "x"}),
                                  (game_server.api_load, {"name": "x"})):
                with self.assertRaises(game_server.web.HTTPNotFound):
                    await handler(self.Request(body))
            help_text = game_server.system_prompt("http://h", "en", benchmark=True)
            self.assertNotIn("/api/save", help_text)
            self.assertNotIn("/api/load", help_text)
            self.assertNotIn("/api/slots", help_text)
        self.assertIn("/api/save", game_server.system_prompt("http://h", "en"))
        self.assertNotIn("/api/save", game_server.system_prompt("http://h", "zh", benchmark=True))

    async def test_in_action_image_counts_as_a_read_in_benchmark(self):
        fake_lib = SimpleNamespace(
            core_frame_hash=lambda: 1, core_width=lambda: 320,
            core_height=lambda: 200, core_frame_serial=lambda: 7,
            core_ticks=lambda: 7, core_fps=lambda: 70.0)

        async def fake_settle(*_a, **_k):
            return 9, True

        lock = game_server.asyncio.Lock()
        with (patch.object(game_server, "LIB", fake_lib),
              patch.object(game_server, "api_lock", lock),
              patch.object(game_server.warden, "ON", True),
              patch.object(game_server.warden, "run", {"done": None, "deadline": None}),
              patch.object(game_server.warden, "note_action", lambda *a, **k: None),
              patch.object(game_server.warden, "note_read") as note_read,
              patch.object(game_server, "settle", fake_settle),
              patch.object(game_server, "snapshot", lambda _f: (b"png", 320, 200, "image/png")),
              patch.object(game_server, "note_move", lambda: None),
              patch.object(game_server, "note_screen", lambda: None),
              patch.object(game_server, "read_stats", lambda: None),
              patch.object(game_server, "log_action", lambda *a, **k: None),
              patch.object(game_server, "rec_add", lambda *a, **k: None)):
            response = await game_server.run_action(
                self.Request({}, {"image": "1"}), [("wait", 0)], "0ms", verb="WAIT")
        self.assertEqual(response.status, 200)
        note_read.assert_called_once()

    async def test_request_error_middleware_counts_from_unmeasured(self):
        async def failing(request):
            raise RuntimeError("boom")

        request = SimpleNamespace(method="GET", path="/api/screen")
        for on, expect in ((False, None), (True, 1), (True, 2)):
            with (patch.object(game_server.warden, "ON", on),
                  patch.object(game_server, "recording_blocked", False),
                  patch.object(game_server.traceback, "print_exc")):
                if expect in (None, 1):
                    game_server.warden.run["errors"] = None
                response = await game_server.json_errors(request, failing)
            self.assertEqual(response.status, 500)
            self.assertEqual(game_server.warden.run["errors"], expect)
            self.assertIn("boom", game_server.stats["last_error"])
        game_server.warden.run["errors"] = None


if __name__ == "__main__":
    unittest.main()
