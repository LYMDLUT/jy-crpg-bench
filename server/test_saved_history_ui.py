"""Include the dependency-free browser-state regression suite in unittest."""
from pathlib import Path
import shutil
import subprocess
import unittest


class SavedHistoryUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed')
    def test_async_history_ui_regressions(self):
        result = subprocess.run(
            [shutil.which('node'), '--test', str(Path(__file__).with_suffix('.js'))],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
