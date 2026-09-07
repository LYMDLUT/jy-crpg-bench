import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from health import Health


class DiagnosticsTests(unittest.TestCase):
    def test_first_fault_freezes_bounded_context_and_survives_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            with patch.dict('os.environ', {'QUNXIA_DIAGNOSTIC_DIR': str(root / 'retained')}):
                health = Health(lambda: 42, lambda: False, root / 'scratch')
            health.set_phase('running')
            for _ in range(100):
                health.sample()
            health.set_input(stage='hold', key='kp7', target_tick=52)
            health.fail('input_frame_timeout', source='input_wait', actual_tick=45)
            health.set_input(stage='release')
            health.fail('core_stalled', source='tick_watchdog')
            health.persist_incident()
            record = json.loads((root / 'retained/incident.json').read_text())
            self.assertEqual(record['failure']['reason'], 'input_frame_timeout')
            self.assertEqual(record['failure']['source'], 'input_wait')
            self.assertEqual(record['input']['stage'], 'hold')
            self.assertEqual(record['details']['actual_tick'], 45)
            self.assertEqual(len(record['samples']), 64)
            self.assertTrue((root / 'retained/threads.txt').read_text())

    def test_http_snapshot_does_not_advance_watchdog(self):
        with tempfile.TemporaryDirectory() as root:
            tick = [0]
            health = Health(lambda: tick[0], lambda: False, root)
            tick[0] = 10
            self.assertEqual(health.snapshot()['core_ticks'], 10)
            self.assertEqual(health.tick, 0)
            self.assertEqual(len(health.history), 0)
            health.sample()
            self.assertEqual(health.tick, 10)
