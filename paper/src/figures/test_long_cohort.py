"""Run from any directory: python3 -B figures/test_long_cohort.py."""
import copy
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import field
import long_cohort
from emit_long import minute_text

COUNTED = {'2ade73b3f2bb', '7a7f8fa37e88', '8aa37740e5e8', 'a5c748b12df1',
           'bd77396a227d', 'd8bcd235fd6d', 'd92f27b88228'}


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.rows = field.long_attempts()
        self.manifest = json.loads(long_cohort.MANIFEST.read_text())

    def entry(self, sid):
        return next(e for e in self.manifest['attempts'] if e['id'] == sid)

    def test_counted_ids(self):
        self.assertEqual(len(self.rows), 40)
        counted = field.load_long()
        self.assertEqual({r['id'] for r in counted}, COUNTED)
        self.assertTrue(all(r['actions'] > 2 for r in counted))
        self.assertNotIn(field.HACK_SESSION, {r['id'] for r in counted})
        self.assertTrue(all(14280 <= long_cohort.last_key_seconds(r) <= 14400 for r in counted))

    def test_unlisted_attempt_is_refused(self):
        self.manifest['attempts'].pop()
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_duplicate_id_is_refused(self):
        self.manifest['attempts'].append(copy.deepcopy(self.manifest['attempts'][0]))
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_tiny_attempt_cannot_count(self):
        self.entry('82794b81135e')['status'] = 'selected'
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_protocol_violation_cannot_count(self):
        self.entry(field.HACK_SESSION)['status'] = 'selected'
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_every_session_at_the_budget_counts(self):
        self.entry('d92f27b88228')['status'] = 'stopped_early'
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_late_key_cannot_count(self):
        self.entry('16831128b3cf')['status'] = 'selected'
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_window_change_is_refused(self):
        self.manifest['last_key_window_seconds'] = 720
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_glm_and_flash_are_separate_models(self):
        counted = {r['id']: r for r in field.load_long()}
        self.assertEqual(counted['d8bcd235fd6d']['agent'], 'glm-5.3')
        self.assertEqual(counted['d92f27b88228']['agent'], 'glm-5.3-flash')
        self.assertEqual(len({r['agent'] for r in counted.values()}), 7)

    def test_session_ids_are_comments_only(self):
        table = (Path(__file__).resolve().parent.parent / 'tables' / 'long.tex').read_text()
        ids = re.findall(r'^% counted-session: ([0-9a-f]{12})$', table, re.M)
        visible = '\n'.join(l for l in table.splitlines() if not l.startswith('%'))
        self.assertEqual(set(ids), COUNTED)
        self.assertEqual(len(ids), len(COUNTED))
        self.assertIsNone(re.search(r'[0-9a-f]{12}', visible))

    def test_validation_does_not_modify_rows(self):
        before = copy.deepcopy(self.rows)
        long_cohort.validate(self.rows, self.manifest)
        self.assertEqual(before, self.rows)

    def test_small_time_does_not_round_to_zero(self):
        self.assertEqual(minute_text(None), '--')
        self.assertEqual(minute_text(0), '$<1$')
        self.assertEqual(minute_text(0.4), '$<1$')
        self.assertEqual(minute_text(238.391), '238.4')


if __name__ == '__main__':
    unittest.main()
