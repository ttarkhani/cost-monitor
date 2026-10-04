"""
Offline tests for backend.pipeline.run_daily_pipeline -- no AWS calls.
STS, Cost Explorer ingestion, DynamoDB reads and SNS publishing are all
replaced with unittest.mock, backed by an in-memory list of SYNTHETIC
snapshots.

Run: ./venv/bin/python test_pipeline.py
"""
import unittest
from datetime import date, timedelta
from unittest import mock

from backend import pipeline
from backend.config import HISTORY_DAYS

START = date(2099, 3, 1)
SPIKE_1 = 11   # day numbers, 1-based
SPIKE_2 = 21


# Fixed, non-periodic noise. A short repeating pattern makes many day-to-day
# deltas exactly equal, which drives MAD to zero and switches the detector to
# its zero-variance fallback; in that mode an earlier spike of the same size
# raises the bar for later ones (see backend/alerts.py). That is real detector
# behaviour, but not what this test is about, so the noise here is irregular.
_NOISE = [0.00, 0.12, -0.07, 0.04, 0.18, -0.11, 0.02, 0.09, -0.03, 0.14, 0.00, -0.08,
          0.06, 0.11, -0.02, 0.16, -0.09, 0.03, 0.07, -0.05, 0.00, 0.13, -0.04, 0.01]


def _synthetic_cost(day_number):
    """SYNTHETIC: ~$5/day with small deterministic noise, spikes on SPIKE_1 and SPIKE_2."""
    if day_number in (SPIKE_1, SPIKE_2):
        return 25.00
    return round(5.00 + _NOISE[day_number % len(_NOISE)], 2)


class FakeWorld:
    """In-memory stand-in for DynamoDB + Cost Explorer + SNS."""

    def __init__(self):
        self.store = {}
        self.today = None
        self.sent = []  # one entry per send_alert call: list of anomaly dicts

    def run_day(self, day_number):
        # The pipeline runs on day_number + 1 and ingests "yesterday" = day_number.
        ingest_date = START + timedelta(days=day_number - 1)
        self.today = ingest_date + timedelta(days=1)

        def fake_fetch(account_id):
            cost = _synthetic_cost(day_number)
            self.store[ingest_date.isoformat()] = {
                'date': ingest_date.isoformat(), 'total_cost': cost,
                'services': {'Amazon EC2': cost},
            }
            return {'date': ingest_date.isoformat(), 'total_cost': cost, 'service_count': 1}

        def fake_get_snapshots(account_id, start, end):
            return [self.store[d] for d in sorted(self.store) if start <= d <= end]

        sts = mock.Mock()
        sts.get_caller_identity.return_value = {'Account': 'offline-test'}
        with mock.patch.object(pipeline, '_sts_client', sts), \
             mock.patch.object(pipeline, '_today', lambda: self.today), \
             mock.patch.object(pipeline, 'fetch_and_store_yesterday', fake_fetch), \
             mock.patch.object(pipeline, 'get_snapshots', fake_get_snapshots), \
             mock.patch.object(pipeline, 'send_alert', side_effect=self.sent.append) as send:
            result = pipeline.run_daily_pipeline()
            return result, send.call_count


def _iso(day_number):
    return (START + timedelta(days=day_number - 1)).isoformat()


class RepeatAlertTests(unittest.TestCase):

    def setUp(self):
        self.world = FakeWorld()
        self.results = {}
        for n in range(1, SPIKE_2 + 3):
            self.results[n] = self.world.run_day(n)

    def test_spike_alerts_exactly_once(self):
        result, calls = self.results[SPIKE_1]
        self.assertEqual(calls, 1)
        self.assertTrue(result['alert_sent'])
        self.assertGreater(result['new_anomaly_count'], 0)
        alerted_dates = {a['date'] for a in self.world.sent[0]}
        self.assertEqual(alerted_dates, {_iso(SPIKE_1)})
        # Across the whole simulated run, SPIKE_1 appears in exactly one alert.
        calls_mentioning = [batch for batch in self.world.sent
                            if any(a['date'] == _iso(SPIKE_1) for a in batch)]
        self.assertEqual(len(calls_mentioning), 1)

    def test_next_day_with_spike_still_in_window_sends_nothing(self):
        result, calls = self.results[SPIKE_1 + 1]
        self.assertEqual(calls, 0)
        self.assertFalse(result['alert_sent'])
        self.assertEqual(result['new_anomaly_count'], 0)
        # The old spike is still detected in the window -- it just isn't re-sent.
        self.assertGreater(result['anomaly_count'], 0)

    def test_quiet_days_send_nothing(self):
        for n, (result, calls) in self.results.items():
            if n not in (SPIKE_1, SPIKE_2):
                self.assertEqual(calls, 0, f"day {n} unexpectedly alerted")

    def test_later_new_spike_alerts_again(self):
        result, calls = self.results[SPIKE_2]
        self.assertEqual(calls, 1)
        self.assertEqual({a['date'] for a in self.world.sent[-1]}, {_iso(SPIKE_2)})
        self.assertEqual(len(self.world.sent), 2)

    def test_result_keys_backward_compatible(self):
        result, _ = self.results[SPIKE_1]
        for key in ('account_id', 'ingested', 'anomaly_count', 'alert_sent',
                    'date', 'total_cost', 'service_count', 'new_anomaly_count'):
            self.assertIn(key, result)


class IngestionFailureTests(unittest.TestCase):

    def test_failed_ingestion_reports_error_and_sends_nothing(self):
        sts = mock.Mock()
        sts.get_caller_identity.return_value = {'Account': 'offline-test'}
        with mock.patch.object(pipeline, '_sts_client', sts), \
             mock.patch.object(pipeline, 'fetch_and_store_yesterday',
                               side_effect=ValueError('no data')), \
             mock.patch.object(pipeline, 'get_snapshots') as get, \
             mock.patch.object(pipeline, 'send_alert') as send:
            result = pipeline.run_daily_pipeline()
        self.assertFalse(result['ingested'])
        self.assertEqual(result['error'], 'no data')
        get.assert_not_called()
        send.assert_not_called()


class WindowTests(unittest.TestCase):

    def test_history_window_uses_shared_constant(self):
        from backend.config import history_window
        start, end = history_window(date(2099, 3, 1))
        self.assertEqual(end, '2099-03-01')
        self.assertEqual(start, (date(2099, 3, 1) - timedelta(days=HISTORY_DAYS)).isoformat())


if __name__ == '__main__':
    unittest.main(verbosity=2)
