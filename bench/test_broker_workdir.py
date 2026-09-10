import pathlib
import sys
import tempfile
import unittest

BENCH_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR))

import broker


class SaveSlotResetTests(unittest.TestCase):
    def test_every_slot_is_the_new_game_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = pathlib.Path(tmp)
            for name, body in (("RANGER", b"base"), ("ALLSIN", b"scenes"), ("ALLDEF", b"events")):
                (game / f"{name}.GRP").write_bytes(body)
                (game / f"{name}.IDX").write_bytes(body + b"-idx")
            for prefix in "RSD":
                for slot in (1, 2, 3):
                    (game / f"{prefix}{slot}.GRP").write_bytes(b"someone's progress")
                    (game / f"{prefix}{slot}.IDX").write_bytes(b"stale")
            (game / "PLAY.BAT").write_bytes(b"@echo")
            broker.reset_save_slots(game)
            for source, prefix in broker.SLOT_SOURCES:
                for slot in (1, 2, 3):
                    self.assertEqual((game / f"{prefix}{slot}.GRP").read_bytes(),
                                     (game / f"{source}.GRP").read_bytes())
                    self.assertEqual((game / f"{prefix}{slot}.IDX").read_bytes(),
                                     (game / f"{source}.IDX").read_bytes())
            self.assertEqual((game / "PLAY.BAT").read_bytes(), b"@echo")

    def test_a_missing_source_leaves_that_slot_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = pathlib.Path(tmp)
            (game / "RANGER.GRP").write_bytes(b"base")
            (game / "R2.GRP").write_bytes(b"old")
            (game / "S2.GRP").write_bytes(b"scene progress")
            broker.reset_save_slots(game)
            self.assertEqual((game / "R2.GRP").read_bytes(), b"base")
            self.assertEqual((game / "S2.GRP").read_bytes(), b"scene progress")


if __name__ == "__main__":
    unittest.main()
