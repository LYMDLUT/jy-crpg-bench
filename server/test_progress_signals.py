import importlib.util
import pathlib
import sys
import unittest


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


if __name__ == "__main__":
    unittest.main()
