"""
Offline tests for backend/history.py (detector status). No AWS.

Run: ./venv/bin/python test_history.py
"""
import unittest
from datetime import date, timedelta

from backend.alerts import MIN_WINDOW, detect_anomalies
from backend.demo_data import demo_ground_truth, generate_demo_snapshots
from backend.history import STALE_AFTER_DAYS, detector_status


def _days(start, n, skip=()):
    d0 = date.fromisoformat(start)
    return [{'date': (d0 + timedelta(days=i)).isoformat(), 'total_cost': 5.0, 'services': {}}
            for i in range(n) if i not in skip]


class DetectorStatusTests(unittest.TestCase):

    def test_empty_history(self):
        s = detector_status([], date(2099, 1, 10))
        self.assertEqual(s['snapshot_count'], 0)
        self.assertEqual(s['valid_transitions'], 0)
        self.assertEqual(s['state'], 'warming_up')
        self.assertEqual(s['gaps'], [])
        self.assertIsNone(s['latest_snapshot_date'])
        self.assertIsNone(s['days_since_latest'])
        self.assertFalse(s['stale'])
        self.assertEqual(s['required_baseline'], MIN_WINDOW)

    def test_one_row(self):
        s = detector_status(_days('2099-01-01', 1), date(2099, 1, 2))
        self.assertEqual(s['valid_transitions'], 0)
        self.assertEqual(s['state'], 'warming_up')
        self.assertEqual(s['latest_snapshot_date'], '2099-01-01')
        self.assertEqual(s['days_since_latest'], 1)
        self.assertFalse(s['stale'])

    def test_two_rows_with_gap(self):
        rows = [{'date': '2099-01-01'}, {'date': '2099-01-11'}]
        s = detector_status(rows, date(2099, 1, 12))
        self.assertEqual(s['valid_transitions'], 0)
        self.assertEqual(s['gaps'], [{'from': '2099-01-01', 'to': '2099-01-11',
                                      'days': 9, 'days_apart': 10}])
        self.assertEqual(s['state'], 'warming_up')

    def test_seven_day_minimum(self):
        # 6 consecutive days = 5 transitions: baseline full, nothing evaluated yet.
        six = detector_status(_days('2099-01-01', 6), date(2099, 1, 7))
        self.assertEqual(six['valid_transitions'], MIN_WINDOW)
        self.assertEqual(six['baseline_progress'], MIN_WINDOW)
        self.assertEqual(six['evaluated_transitions'], 0)
        self.assertEqual(six['state'], 'warming_up')
        # 7 consecutive days = 6 transitions: the 6th is the first one evaluated.
        seven = detector_status(_days('2099-01-01', 7), date(2099, 1, 8))
        self.assertEqual(seven['valid_transitions'], MIN_WINDOW + 1)
        self.assertEqual(seven['evaluated_transitions'], 1)
        self.assertEqual(seven['state'], 'active')

    def test_state_agrees_with_detector_evaluation(self):
        # Cross-check against the frozen detector: a big jump on the 7th day
        # is flagged, on the 6th it is not (not enough baseline yet).
        for n, should_flag in ((6, False), (7, True)):
            rows = _days('2099-01-01', n)
            rows[-1]['total_cost'] = 50.0
            flagged = bool(detect_anomalies(rows, per_service=False))
            state = detector_status(rows, date(2099, 2, 1))['state']
            self.assertEqual(flagged, should_flag)
            self.assertEqual(state == 'active', should_flag)

    def test_gap_breaks_consecutive_run(self):
        # 8 calendar days with day index 3 missing: 7 rows, 6 transitions, 1 spans the gap.
        s = detector_status(_days('2099-01-01', 8, skip={3}), date(2099, 1, 9))
        self.assertEqual(s['valid_transitions'], 5)
        self.assertEqual(len(s['gaps']), 1)
        self.assertEqual(s['state'], 'warming_up')

    def test_unsorted_input(self):
        rows = list(reversed(_days('2099-01-01', 3)))
        s = detector_status(rows, date(2099, 1, 4))
        self.assertEqual(s['latest_snapshot_date'], '2099-01-03')
        self.assertEqual(s['first_snapshot_date'], '2099-01-01')
        self.assertEqual(s['gaps'], [])

    def test_stale_threshold(self):
        rows = _days('2099-01-01', 1)
        self.assertFalse(detector_status(rows, date(2099, 1, 1) + timedelta(days=STALE_AFTER_DAYS))['stale'])
        self.assertTrue(detector_status(rows, date(2099, 1, 1) + timedelta(days=STALE_AFTER_DAYS + 1))['stale'])

    def test_demo_dataset(self):
        end = date(2026, 10, 3)
        snaps = generate_demo_snapshots(end)
        s = detector_status(snaps, end + timedelta(days=1))
        gap_truth = next(e for e in demo_ground_truth(end) if e['type'] == 'ingestion_gap')
        self.assertEqual(s['snapshot_count'], len(snaps))
        self.assertEqual(len(s['gaps']), 1)
        self.assertEqual(s['gaps'][0]['days'], len(gap_truth['missing_dates']))
        self.assertEqual(s['valid_transitions'], len(snaps) - 1 - 1)
        self.assertEqual(s['state'], 'active')
        self.assertEqual(s['latest_snapshot_date'], end.isoformat())
        self.assertEqual(s['days_since_latest'], 1)
        self.assertFalse(s['stale'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
