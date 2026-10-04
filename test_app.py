"""
Offline tests for the Flask app (app.py). No AWS: demo mode never touches
it, and live mode is exercised with the data loader or STS mocked.

Run: ./venv/bin/python test_app.py
"""
import os
import subprocess
import sys
import unittest
from datetime import date
from unittest import mock

from botocore.exceptions import NoCredentialsError

import app as app_module
from backend import cache
from backend.config import HISTORY_DAYS

PINNED_TODAY = date(2026, 10, 4)

ALERT_KEYS = {'level', 'service', 'date', 'previous_date', 'previous_cost', 'current_cost',
              'delta', 'modified_z', 'status', 'flagged', 'window_size', 'day_index'}


class AppTests(unittest.TestCase):

    def setUp(self):
        cache.clear()
        app_module.get_account_id.cache_clear()
        self.client = app_module.create_app().test_client()
        patcher = mock.patch.object(app_module, '_utc_today', lambda: PINNED_TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, url):
        resp = self.client.get(url)
        return resp, resp.get_json()

    # --- offline import / config -------------------------------------------

    def test_import_makes_no_aws_call(self):
        self.assertEqual(app_module.get_account_id.cache_info().currsize, 0)

    def test_module_level_app_for_vercel_and_import_makes_no_aws_client(self):
        # Fresh interpreter, so nothing imported by this test file leaks in.
        # boto3's client/resource/Session constructors are replaced before
        # app.py is imported; any call to them fails the import.
        code = (
            "import boto3\n"
            "def _no(*a, **k): raise SystemExit('AWS client created at import')\n"
            "boto3.client = boto3.resource = boto3.Session = _no\n"
            "import app, flask\n"
            "assert isinstance(app.app, flask.Flask), type(app.app)\n"
            "print('ok')\n"
        )
        env = {k: v for k, v in os.environ.items() if not k.startswith('AWS_')}
        env.update(AWS_CONFIG_FILE=os.devnull, AWS_SHARED_CREDENTIALS_FILE=os.devnull)
        proc = subprocess.run([sys.executable, '-c', code], cwd=os.path.dirname(os.path.abspath(__file__)),
                              env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(proc.stdout.strip(), 'ok')

    def test_debug_off_by_default(self):
        self.assertFalse(app_module.app.debug)

    # --- demo mode -----------------------------------------------------------

    def test_demo_costs_labeled_synthetic(self):
        with mock.patch.object(app_module, 'get_account_id', side_effect=AssertionError('AWS touched')):
            resp, body = self.get('/api/costs?mode=demo&days=60')
        self.assertEqual(resp.status_code, 200)
        self.assertIs(body['synthetic'], True)
        self.assertEqual(body['meta']['source'], 'demo')
        self.assertEqual(body['meta']['mode'], 'demo')
        self.assertEqual(body['data'][-1]['date'], '2026-10-03')
        row = body['data'][0]
        self.assertEqual(set(row), {'date', 'total_cost', 'services'})

    def test_demo_alerts_are_real_detector_output(self):
        resp, body = self.get('/api/alerts?mode=demo&days=60')
        self.assertEqual(resp.status_code, 200)
        self.assertIs(body['synthetic'], True)
        self.assertEqual(len(body['data']), 4)
        for a in body['data']:
            self.assertTrue(ALERT_KEYS <= set(a), set(a) ^ ALERT_KEYS)
            if a['level'] == 'service':
                self.assertIn('is_new', a)

    def test_demo_detector_status(self):
        resp, body = self.get('/api/detector-status?mode=demo')
        self.assertEqual(resp.status_code, 200)
        self.assertIs(body['synthetic'], True)
        self.assertEqual(body['data']['state'], 'active')
        self.assertEqual(body['data']['days_since_latest'], 1)
        self.assertEqual(len(body['data']['gaps']), 1)

    def test_days_narrows_view_but_not_detection(self):
        _, all_costs = self.get('/api/costs?mode=demo&days=60')
        _, week = self.get('/api/costs?mode=demo&days=7')
        self.assertEqual(week['meta']['view_start'], '2026-09-27')
        self.assertTrue(all(r['date'] >= '2026-09-27' for r in week['data']))
        self.assertLess(len(week['data']), len(all_costs['data']))
        # The new-service anomaly (2026-09-27) is still detected with a 7-day view,
        # because detection runs on the full window, not on the 7 displayed days.
        _, week_alerts = self.get('/api/alerts?mode=demo&days=7')
        self.assertEqual({a['date'] for a in week_alerts['data']}, {'2026-09-27'})

    # --- validation and errors ----------------------------------------------

    def test_bad_params_return_400_json(self):
        for qs in ('mode=prod', 'days=0', f'days={HISTORY_DAYS + 1}', 'days=abc',
                   'days=-5', 'days=7.5', 'mode='):
            for path in ('/api/costs', '/api/alerts', '/api/detector-status'):
                resp, body = self.get(f'{path}?{qs}')
                self.assertEqual(resp.status_code, 400, f'{path}?{qs}')
                self.assertEqual(set(body), {'error'})

    def test_unknown_api_route_is_json_404(self):
        resp, body = self.get('/api/nope')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(body, {'error': 'Not Found'})

    def test_wrong_method_is_json_405(self):
        resp = self.client.post('/api/costs')
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.get_json(), {'error': 'Method Not Allowed'})

    def test_live_aws_failure_is_503_without_details(self):
        with mock.patch.object(app_module, 'get_account_id', side_effect=NoCredentialsError()):
            resp, body = self.get('/api/costs')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(set(body), {'error'})
        self.assertNotIn('Traceback', resp.get_data(as_text=True))
        self.assertNotIn('credentials', body['error'].lower())

    def test_unexpected_error_is_generic_500(self):
        with mock.patch.object(app_module, '_load_live', side_effect=RuntimeError('secret detail')):
            with self.assertLogs(app_module.log, level='ERROR'):
                resp, body = self.get('/api/costs')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(body, {'error': 'Internal server error'})

    # --- live mode (mocked) --------------------------------------------------

    def test_live_mode_not_synthetic_and_cached(self):
        rows = [{'date': '2026-10-02', 'total_cost': 0.0, 'services': {}},
                {'date': '2026-10-03', 'total_cost': 0.004, 'services': {'Amazon S3': 0.004}}]
        with mock.patch.object(app_module, 'get_account_id', return_value='offline-test'), \
             mock.patch('backend.db.get_snapshots', return_value=rows) as get:
            r1, b1 = self.get('/api/costs')
            r2, b2 = self.get('/api/alerts')
        self.assertEqual(r1.status_code, 200)
        self.assertIs(b1['synthetic'], False)
        self.assertEqual(b1['meta']['source'], 'dynamodb')
        self.assertEqual(b2['meta']['source'], 'cache')
        self.assertEqual(get.call_count, 1)
        start, end = get.call_args.args[1:]
        self.assertEqual(end, '2026-10-04')
        self.assertEqual((PINNED_TODAY - date.fromisoformat(start)).days, HISTORY_DAYS)


if __name__ == '__main__':
    unittest.main(verbosity=2)
