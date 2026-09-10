import unittest

from long_horizon import score_long_horizon


class LongHorizonScoreTests(unittest.TestCase):
    def test_short_metrics_are_frozen_and_medium_gates_show_the_journey(self):
        report = score_long_horizon([
            {"at": 0, "milestones": ["acted"], "measured_tiers": ["short"]},
            {"at": 1800, "milestones": ["inn"], "measured_tiers": ["medium"]},
            {"at": 2400, "milestones": ["acted", "inn", "nanxian", "compass"],
             "measured_tiers": ["short", "medium"],
             "locations": ["home", "inn", "nanxian"],
             "level": 1, "team_size": 1, "key_items": ["compass"]},
        ])
        self.assertTrue(report["short_metrics_unchanged"])
        self.assertEqual(report["tiers"]["short"]["status"], "frozen_external_metric")
        self.assertEqual(report["tiers"]["medium"]["score"], 75.0)
        self.assertEqual(report["tiers"]["long"]["status"], "unmeasured")

    def test_long_run_without_books_still_has_a_measured_trajectory(self):
        report = score_long_horizon([
            {"at": 0, "milestones": ["inn", "nanxian", "compass"],
             "measured_tiers": ["medium", "long"],
             "locations": ["home", "inn", "nanxian"], "story_nodes": ["opening"],
             "level": 1, "team_size": 1, "key_items": ["compass"], "books": []},
            {"at": 7200, "milestones": ["inn", "nanxian", "compass",
                                           "second_location", "battle_won", "skill_gain"],
             "measured_tiers": ["medium", "long"],
             "locations": ["home", "inn", "nanxian", "kunlun", "wudang"],
             "story_nodes": ["opening", "tianlong", "yitian"],
             "level": 4, "team_size": 3, "key_items": ["compass", "jade_seal"], "books": []},
        ])
        self.assertGreater(report["score"], 0)
        self.assertEqual(report["components"]["book_collection"]["measured"], True)
        self.assertEqual(report["components"]["book_collection"]["value"], 0.0)
        self.assertEqual(report["tiers"]["long"]["score"], 40.0)
        self.assertEqual(report["score"], 35.542)

    def test_missing_optional_dimensions_are_unmeasured_not_zero(self):
        report = score_long_horizon([
            {"at": 0, "milestones": ["acted"], "measured_tiers": ["short"]},
        ])
        self.assertIsNone(report["components"]["exploration"]["score"])
        self.assertIsNone(report["components"]["reliability"]["score"])
        self.assertIsNone(report["score"])
        self.assertEqual(report["maximum_measured"], 0)
        self.assertEqual(report["coverage"], 0.0)

    def test_checkpoint_time_must_be_ordered(self):
        with self.assertRaises(ValueError):
            score_long_horizon([{"at": 2}, {"at": 1}])


if __name__ == "__main__":
    unittest.main()
