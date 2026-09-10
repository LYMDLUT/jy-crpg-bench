import json
import pathlib
import random
import subprocess
import sys
import tempfile
import unittest

BENCH = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))

import check_random_run
from random_baseline import ACTIONS


def journal(keys, run="abc", agent="random-baseline"):
    marks = [{"n": i + 1, "t": i * 1.1, "do": f"KEY {k}", "keys": [[k, 0.142]]}
             for i, k in enumerate(keys)]
    return {"id": run, "agent": agent, "speed": 8.0, "marks": marks}


class SeededSequenceTests(unittest.TestCase):
    def test_the_sequence_is_the_scripts_own_draws(self):
        rng = random.Random(1996)
        want = []
        for _ in range(50):
            want.append(rng.choice(ACTIONS))
            rng.expovariate(1 / 1.1)
        self.assertEqual(check_random_run.intended(1996, 50, 1.1), want)

    def test_a_matching_journal_passes_and_a_swapped_key_fails(self):
        keys = check_random_run.intended(1996, 40, 1.1)
        with tempfile.TemporaryDirectory() as tmp:
            good = pathlib.Path(tmp) / "good.json"
            good.write_text(json.dumps(journal(keys)))
            out = subprocess.run([sys.executable, str(BENCH / "check_random_run.py"), str(good)],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn("40/40 keys agree", out.stdout)
            bad_keys = list(keys)
            bad_keys[7] = "kp1" if bad_keys[7] != "kp1" else "kp3"
            bad = pathlib.Path(tmp) / "bad.json"
            bad.write_text(json.dumps(journal(bad_keys)))
            out = subprocess.run([sys.executable, str(BENCH / "check_random_run.py"), str(bad)],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 1)
            self.assertIn("39/40 keys agree", out.stdout)

    def test_the_catalogue_histogram_is_compared(self):
        keys = check_random_run.intended(1996, 30, 1.1)
        with tempfile.TemporaryDirectory() as tmp:
            tl = pathlib.Path(tmp) / "tl.json"
            tl.write_text(json.dumps(journal(keys)))
            hist = {}
            for k in keys:
                hist[k] = hist.get(k, 0) + 1
            cat = pathlib.Path(tmp) / "catalog.json"
            cat.write_text(json.dumps([{"id": "abc", "keys": hist, "key_events": 30, "actions": 30}]))
            out = subprocess.run([sys.executable, str(BENCH / "check_random_run.py"), str(tl),
                                  "--catalog", str(cat)], capture_output=True, text=True)
            self.assertIn("catalogue histogram matches the journal", out.stdout)


if __name__ == "__main__":
    unittest.main()
