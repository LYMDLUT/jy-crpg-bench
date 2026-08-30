import importlib.util
import pathlib
import unittest
from unittest import mock


HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("qunxia_mcp", HERE / "server.py")
game = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(game)


class MCPToolTest(unittest.TestCase):
    def test_press_uses_reliable_default_hold(self):
        with mock.patch.object(game, "_act", return_value=[]) as act:
            game.press("right")
        act.assert_called_once_with(
            "/key", {"key": "right", "hold": game.DEFAULT_TAP_FRAMES},
            note="right", stable=None,
        )
        self.assertEqual(game.DEFAULT_TAP_FRAMES, 10)

    def test_press_rejects_non_positive_repeat(self):
        with self.assertRaisesRegex(ValueError, "times"):
            game.press("right", times=0)

    def test_move_rejects_unbounded_batch(self):
        with self.assertRaisesRegex(ValueError, "steps"):
            game.move("right", steps=101)

    def test_actions_request_atomic_image(self):
        with mock.patch.object(game, "_call", return_value={"ok": True}) as call:
            game.interact()
        self.assertIn("image=1", call.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
