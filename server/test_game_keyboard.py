from pathlib import Path
import shutil
import subprocess
import unittest
class GameKeyboardTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed')
    def test_ui_keys_never_reach_game(self):
        run=subprocess.run([shutil.which('node'),'--test',str(Path(__file__).with_suffix('.js'))],capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
