"""The paper's reproducibility claim, exercised against the real core.

The golden in bench/golden/ is one regeneration of the committed start
state under the committed input script, by this driver.  These tests are
the claim:

* regenerating twice, in two fresh processes, gives the same deterministic
  game/picture projection; emulator-private timing bytes are diagnostic only;
* regenerating reaches the committed golden's destination, on the
  platform that produced it;
* the load lands on the same *game* however long the title screen had
  been up when it arrived - the start state is a well-defined origin,
  not a moving target.

Fresh-process and golden comparisons use `repro.DETERMINISTIC` rather than
the whole signature, and the reason is measured rather than assumed. The
emulator carries counters its own serialiser does not restore: at two
park lengths the machine image differs immediately after the load,
before a frame of the script has run, while the picture and the game's
own state are identical. Under the script the picture then diverges for
about a hundred frames - a key lands in a different frame - and
converges again. The image hash also depends on the local build, which
is not in the repository. So what is asserted is where a run ends up, on
screen and in the game's own numbers, and the image hash rides along in
the signature as a diagnostic.

Each case runs the driver in a subprocess: the core's lifecycle is one
per process - the host refuses a second initialization over a live core
and the libretro contract guarantees no second one - and a fresh process
is the stronger claim anyway.  Where the core, game, or start state is
absent the driver exits 3 and the case is skipped, as on a CI runner
that builds no game.
"""
import json
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import repro                                               # noqa: E402
GOLDEN = HERE / "golden" / f"repro-{platform.system().lower()}.json"


def regenerate(extra=0, env=None):
    """One regeneration in a fresh process; the signature, or an exit code."""
    proc = subprocess.run(
        [sys.executable, str(HERE / "repro.py"),
         *([f"--extra={extra}"] if extra else [])],
        cwd=str(ROOT), capture_output=True, text=True,
        env={**os.environ, **(env or {})})
    if proc.returncode == 0:
        return json.loads(proc.stdout)
    if proc.returncode == 3:
        return proc.returncode
    raise AssertionError(
        f"regeneration failed (exit {proc.returncode}):\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}")


class ReproTests(unittest.TestCase):
    def _signature(self, value):
        """Skip unless the driver actually ran: exit 3 means the runner has
        no core, game, or start state to regenerate with."""
        if isinstance(value, int):
            self.skipTest(f"the driver exits {value}: the core, game, or "
                          "start state is absent on this runner")
        return value

    def test_double_regeneration(self):
        a = self._signature(regenerate())
        b = self._signature(regenerate())
        self.assertEqual(self._destination(a), self._destination(b),
                         "two fresh regenerations differ in deterministic output")

    def _destination(self, signature):
        return {k: signature.get(k) for k in repro.DETERMINISTIC}

    def test_golden(self):
        if not GOLDEN.exists():
            self.skipTest("no committed golden on this platform")
        signature = self._signature(regenerate())
        self.assertEqual(self._destination(signature),
                         self._destination(json.loads(GOLDEN.read_text())),
                         "the regenerated run ends somewhere else than the golden")

    def test_load_is_invariant_to_park_length(self):
        # The live server loads seconds after the title parked; a run that
        # loads later must land in the same game.  (Loading mid-boot must
        # never be tried: the core pauses its emulation thread at the load
        # only outside the boot phase, so a mid-boot load lands wherever the
        # boot happens to be.)
        parked = self._signature(regenerate())
        longer = self._signature(regenerate(extra=600))
        self.assertEqual(parked["game"], longer["game"])
        self.assertEqual(parked["picture"], longer["picture"])
        # and the machine image is the thing that does not survive it
        self.assertNotEqual(parked["state_sha256"], longer["state_sha256"],
                            "the image now survives a longer park; tighten "
                            "these assertions back to it")


if __name__ == "__main__":
    main = unittest.main()
