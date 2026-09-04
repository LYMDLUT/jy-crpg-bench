import importlib.util
import pathlib
import sys
import unittest
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
        )

    def tearDown(self):
        game_server.world.clear()
        game_server.world.update(self.original)

    def test_reference_cannot_latch_before_a_scene_transition(self):
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


class InputLimitTests(unittest.IsolatedAsyncioTestCase):
    class Request:
        def __init__(self, body):
            self.body = body

        async def json(self):
            return self.body

    async def test_sequence_length_is_bounded(self):
        response = await game_server.api_keys(self.Request({
            "keys": ["enter"] * (game_server.MAX_KEYS_PER_ACTION + 1),
        }))
        self.assertEqual(response.status, 400)

    async def test_repeat_and_hold_are_clamped_before_execution(self):
        action = AsyncMock(return_value="ok")
        with patch.object(game_server, "run_action", action):
            await game_server.api_key(self.Request({
                "key": "enter", "times": 1000000, "hold": 1000000,
            }))
        steps = action.await_args.args[1]
        self.assertEqual(len(steps), game_server.MAX_KEYS_PER_ACTION * 2 - 1)
        key_steps = [step for step in steps if len(step) > 2]
        self.assertEqual(len(key_steps), game_server.MAX_KEYS_PER_ACTION)
        self.assertTrue(all(step[1] == game_server.MAX_HOLD_FRAMES for step in key_steps))


if __name__ == "__main__":
    unittest.main()
