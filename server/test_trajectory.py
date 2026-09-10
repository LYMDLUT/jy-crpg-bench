import json
import tempfile
import unittest
from pathlib import Path

from trajectory import analyze, summarize


class TrajectoryTests(unittest.TestCase):
    def test_action_observations_and_windows_measure_route_quality(self):
        events = []
        for number, (when, key, x, frontier, changed) in enumerate([
            (0.0, "right", 0, 0, True),
            (1.0, "right", 1, 1, True),
            (7.0, "left", 2, 2, False),
            (8.0, "left", 1, 1, True),
        ], 1):
            events.append({"t": when, "act": "KEY", "on": key})
            events.append({"t": when + .1, "trajectory": True, "action": number,
                           "x": x, "y": 4, "frontier": frontier,
                           "screen_changed": changed})
        result = summarize(events, window_size=2)
        self.assertEqual(result["status"], "measured")
        self.assertEqual(result["summary"]["distance"], 3)
        self.assertEqual(result["summary"]["position_samples"], 4)
        self.assertEqual(result["summary"]["frontier_regressions"], 1)
        self.assertEqual(result["summary"]["reverse_steps"], 1)
        self.assertEqual(result["summary"]["long_pauses"], 1)
        self.assertEqual(len(result["windows"]), 2)

    def test_legacy_recording_reports_action_metrics_without_fake_coordinates(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "recording.jsonl"
            path.write_text("\n".join([
                json.dumps({"version": 1, "started": 1}),
                json.dumps({"t": 0.0, "act": "KEY", "on": "right"}),
                json.dumps({"t": 2.0, "act": "KEY", "on": "left"}),
            ]) + "\n")
            result = analyze(path)
        self.assertEqual(result["status"], "position-unmeasured")
        self.assertEqual(result["summary"]["actions"], 2)
        self.assertEqual(result["summary"]["distance"], None)
        self.assertEqual(result["summary"]["reverse_steps"], 1)


if __name__ == "__main__":
    unittest.main()
