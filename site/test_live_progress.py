import importlib.util
import pathlib
import unittest


SITE_DIR = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("qunxia_site_build", SITE_DIR / "build.py")
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class LiveProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = BUILD.build(BUILD.EN, "test")

    def test_live_entries_carry_new_progress_fields(self):
        for field in (
            "level", "exp", "skills", "inventory_distinct", "picked_item",
            "key_events", "input_frames", "wait_calls",
        ):
            self.assertIn(f"{field}: s.{field} ?? null", self.html)

    def test_live_progress_cells_are_refreshed(self):
        for field in ("ladder", "hero", "exit", "scenes", "inputs"):
            self.assertIn(f'f === "{field}"', self.html)
        self.assertIn('data-live="${r.id}:ladder"', self.html)


if __name__ == "__main__":
    unittest.main()
