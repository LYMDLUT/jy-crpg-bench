"""Run from any directory: python3 -B figures/test_long_cohort.py."""
import contextlib
import copy
import io
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import field
import long_cohort
import emit_long
from emit_long import minute_text

KIMI = "16831128b3cf"


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.rows = field.long_attempts()
        self.manifest = json.loads(long_cohort.MANIFEST.read_text())

    def entry(self, sid):
        return next(e for e in self.manifest['attempts'] if e['id'] == sid)

    def row(self, sid):
        return next(r for r in self.rows if r['id'] == sid)

    def test_selected_ids_and_unchanged_raw_archive(self):
        self.assertEqual(len(self.rows), 40)
        selected = field.load_long()
        self.assertEqual({r['id'] for r in selected}, {
            '2ade73b3f2bb', '7a7f8fa37e88', '8aa37740e5e8',
            'a5c748b12df1', 'bd77396a227d', 'd8bcd235fd6d', 'd92f27b88228', KIMI})
        self.assertTrue(all(r['actions'] > 2 for r in selected))
        self.assertNotIn(field.HACK_SESSION, {r['id'] for r in selected})
        for row in selected:
            self.assertTrue(14280 <= long_cohort.last_key_seconds(row) <= 14400
                            or long_cohort.verified_client_completion(row, self.entry(row['id'])))

    def test_unreviewed_attempt_fails(self):
        self.manifest['attempts'].pop()
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_duplicate_id_fails(self):
        self.manifest['attempts'].append(copy.deepcopy(self.manifest['attempts'][0]))
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_tiny_attempt_cannot_be_selected(self):
        self.entry('82794b81135e')['status'] = 'selected'
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_protocol_violation_cannot_be_selected(self):
        self.entry(field.HACK_SESSION)['status'] = 'selected'
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_every_session_at_the_budget_counts(self):
        self.entry('d92f27b88228')['status'] = 'stopped_early'
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_kimi_deadline_evidence_and_real_time_are_preserved(self):
        entry = self.entry(KIMI)
        row = self.row(KIMI)
        self.assertEqual(entry['status'], 'selected')
        self.assertTrue(long_cohort.verified_client_completion(row, entry))
        self.assertEqual(row['actions'], 1183)
        self.assertAlmostEqual(long_cohort.last_key_seconds(row) / 60, 179.770682, places=5)
        self.assertEqual(field.rungs_reached(row), 1)
        self.assertFalse(field.on_map(row))

    def test_window_change_is_refused(self):
        self.manifest['last_key_window_seconds'] = 720
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_small_time_does_not_round_to_zero(self):
        self.assertEqual(minute_text(None), '--')
        self.assertEqual(minute_text(0), '$<1$')
        self.assertEqual(minute_text(0.4), '$<1$')
        self.assertEqual(minute_text(238.391), '238.4')

    def test_glm_and_flash_are_separate_models(self):
        selected = {r['id']: r for r in field.load_long()}
        self.assertEqual(selected['d8bcd235fd6d']['agent'], 'glm-5.3')
        self.assertEqual(selected['d92f27b88228']['agent'], 'glm-5.3-flash')
        self.assertEqual(len({r['agent'] for r in selected.values()}), 8)
        self.assertEqual(field.ALIASES['glm5.3flashhigh'], 'glm-5.3-flash')
        self.assertEqual(field.ALIASES['glm5.3-flash-high'], 'glm-5.3-flash')

    def test_session_ids_are_comments_and_kimi_is_an_ordinary_row(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            emit_long.main()
        table = output.getvalue()
        visible = '\n'.join(line for line in table.splitlines() if not line.startswith('%'))
        self.assertNotIn('Session &', visible)
        self.assertNotRegex(visible, r'[0-9a-f]{12}')
        counted = re.findall(r'^% counted-session: ([0-9a-f]{12})$', table, re.M)
        self.assertEqual(set(counted), {r['id'] for r in field.load_long()})
        self.assertEqual(len(counted), len(set(counted)))
        self.assertNotIn('review-session:', table)
        self.assertNotIn('Pending review', visible)
        self.assertNotIn('dagger', visible)
        self.assertEqual(visible.count('\\midrule'), 1)
        self.assertEqual(visible.count('\\texttt{kimi-k3}'), 1)
        self.assertIn('\\texttt{kimi-k3} & 179.8 & 1183 & -- & 2.0 & -- & -- & -- & -- & 1', visible)

    def test_catalogue_time_label_alone_cannot_admit_kimi(self):
        self.entry(KIMI).pop('client_completion')
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_other_short_kimi_remains_outside(self):
        other = self.entry('a9b408f53ec8')
        self.assertEqual(other['status'], 'stopped_early')
        other['status'] = 'selected'
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_unreviewed_or_incomplete_evidence_fails(self):
        original = copy.deepcopy(self.entry(KIMI)['client_completion'])
        for key, value in (('reviewed', False), ('session_id', 'wrong'),
                           ('budget_seconds', 3600), ('activity_until_expiry', False),
                           ('human_intervention_observed', True), ('http_status', 200),
                           ('source', ''), ('reference', ''), ('response', [])):
            with self.subTest(key=key):
                self.entry(KIMI)['client_completion'] = copy.deepcopy(original)
                self.entry(KIMI)['client_completion'][key] = value
                with self.assertRaises(ValueError):
                    long_cohort.validate(self.rows, self.manifest)

    def test_mismatched_terminal_response_fails(self):
        original = copy.deepcopy(self.entry(KIMI)['client_completion'])
        for key, value in (('agent', 'other'), ('actions', 1), ('reason', 'idle'),
                           ('why', 'partial budget'), ('ended', False), ('error', 'failure')):
            with self.subTest(key=key):
                self.entry(KIMI)['client_completion'] = copy.deepcopy(original)
                self.entry(KIMI)['client_completion']['response'][key] = value
                with self.assertRaises(ValueError):
                    long_cohort.validate(self.rows, self.manifest)

    def test_evidence_cannot_override_protocol_config_or_startup_exclusions(self):
        for sid in (field.HACK_SESSION, '32a1d38bbfce', '82794b81135e', '913be91591d6'):
            with self.subTest(sid=sid):
                manifest = copy.deepcopy(self.manifest)
                entry = next(e for e in manifest['attempts'] if e['id'] == sid)
                row = self.row(sid)
                evidence = copy.deepcopy(self.entry(KIMI)['client_completion'])
                evidence['session_id'] = sid
                evidence['response']['agent'] = row['declared']
                evidence['response']['actions'] = row['actions']
                entry['client_completion'] = evidence
                self.assertTrue(long_cohort.verified_client_completion(row, entry))
                long_cohort.validate(self.rows, manifest)
                entry['status'] = 'selected'
                with self.assertRaises(ValueError):
                    long_cohort.validate(self.rows, manifest)

    def test_verified_completion_cannot_be_silently_excluded(self):
        self.entry(KIMI)['status'] = 'stopped_early'
        with self.assertRaises(ValueError):
            long_cohort.validate(self.rows, self.manifest)

    def test_validation_does_not_modify_original_rows(self):
        before = copy.deepcopy(self.rows)
        long_cohort.validate(self.rows, self.manifest)
        self.assertEqual(self.rows, before)


if __name__ == '__main__':
    unittest.main()
