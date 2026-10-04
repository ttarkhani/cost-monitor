"""
Offline tests for the SYNTHETIC demo dataset (backend/demo_data.py).

The important one: the REAL detector (backend.alerts.detect_anomalies,
unmodified) run over the demo data must flag exactly the injected events
-- no false positives, no misses.

Run: ./venv/bin/python test_demo_data.py
"""
import unittest
from datetime import date, timedelta

from backend.alerts import detect_anomalies
from backend.demo_data import (DAYS, SYNTHETIC, demo_ground_truth,
                               generate_demo_snapshots)

END_DATES = [date(2026, 10, 3), date(2027, 2, 28), date(2028, 3, 1), date(2030, 12, 31)]


class DemoDataTests(unittest.TestCase):

    def test_marked_synthetic(self):
        self.assertIs(SYNTHETIC, True)

    def test_deterministic(self):
        end = END_DATES[0]
        self.assertEqual(generate_demo_snapshots(end), generate_demo_snapshots(end))

    def test_anchored_to_end_date_and_shape(self):
        for end in END_DATES:
            snaps = generate_demo_snapshots(end)
            self.assertEqual(snaps[-1]['date'], end.isoformat())
            self.assertEqual(snaps[0]['date'], (end - timedelta(days=DAYS - 1)).isoformat())
            self.assertEqual([s['date'] for s in snaps], sorted(s['date'] for s in snaps))
            services = {name for s in snaps for name in s['services']}
            self.assertEqual(len(services), 4)
            for s in snaps:
                self.assertAlmostEqual(s['total_cost'], sum(s['services'].values()), places=2)

    def test_gap_is_present(self):
        for end in END_DATES:
            dates = {s['date'] for s in generate_demo_snapshots(end)}
            gap = next(e for e in demo_ground_truth(end) if e['type'] == 'ingestion_gap')
            self.assertEqual(len(gap['missing_dates']), 2)
            for d in gap['missing_dates']:
                self.assertNotIn(d, dates)

    def test_detector_matches_ground_truth_exactly(self):
        for end in END_DATES:
            with self.subTest(end=end):
                snaps = generate_demo_snapshots(end)
                truth = demo_ground_truth(end)
                expected = {f for event in truth for f in event['expected_flags']}
                actual = {(a['level'], a['service'], a['date']) for a in detect_anomalies(snaps)}
                self.assertEqual(actual - expected, set(), 'false positives')
                self.assertEqual(expected - actual, set(), 'missed injected events')

    def test_new_service_reported_as_new(self):
        end = END_DATES[0]
        new_event = next(e for e in demo_ground_truth(end) if e['type'] == 'new_service')
        flagged = [a for a in detect_anomalies(generate_demo_snapshots(end))
                   if a['level'] == 'service' and a['service'] == new_event['service']]
        self.assertEqual(len(flagged), 1)
        self.assertTrue(flagged[0]['is_new'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
