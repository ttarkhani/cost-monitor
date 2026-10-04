"""
Offline tests for the Flask app (app.py). No AWS: demo mode never touches
it, and live mode is exercised with the data loader or STS mocked.

Run: ./venv/bin/python test_app.py
"""
import os
import re
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
        # These tests exercise live mode, so run them as a local (non-Vercel) server.
        env = {k: v for k, v in os.environ.items() if k not in ('VERCEL', 'COST_MONITOR_LIVE_ENABLED')}
        env_patcher = mock.patch.dict(os.environ, env, clear=True)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

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

    def test_every_page_asset_served_with_correct_type(self):
        page = self.client.get('/').get_data(as_text=True)
        urls = set(re.findall(r'(?:src|href)="(/[^"]+)"', page))
        # Relative ES module imports inside the module scripts load too.
        for url in [u for u in urls if u.endswith('.mjs')]:
            resp = self.client.get(url)
            body = resp.get_data(as_text=True)
            resp.close()
            base = url.rsplit('/', 1)[0]
            urls |= {f"{base}/{m}" for m in re.findall(r"from '\./([^']+)'", body)}
        expected = {'.css': 'text/css', '.mjs': 'text/javascript', '.js': 'text/javascript'}
        self.assertIn('/static/js/dashboard.mjs', urls)
        self.assertIn('/static/js/logic.mjs', urls)
        self.assertIn('/static/css/dashboard.css', urls)
        root = os.path.dirname(os.path.abspath(__file__))
        for url in sorted(urls):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)
                ext = os.path.splitext(url)[1]
                self.assertEqual(resp.mimetype, expected[ext])
                # Vercel serves public/** from its CDN at the same path.
                self.assertTrue(os.path.isfile(os.path.join(root, 'public', url.lstrip('/'))), url)
                resp.close()

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



class DemoOnlyDeploymentTests(unittest.TestCase):
    """Live mode gating via VERCEL / COST_MONITOR_LIVE_ENABLED. No AWS anywhere."""

    def setUp(self):
        cache.clear()
        app_module.get_account_id.cache_clear()
        self.client = app_module.create_app().test_client()
        for patcher in (
            mock.patch.object(app_module, '_utc_today', lambda: PINNED_TODAY),
            # Any attempt to reach AWS fails the test loudly.
            mock.patch('boto3.client', side_effect=AssertionError('boto3.client called')),
            mock.patch('boto3.resource', side_effect=AssertionError('boto3.resource called')),
            mock.patch.object(app_module, 'get_account_id', side_effect=AssertionError('STS lookup')),
            mock.patch.object(app_module, '_load_live', side_effect=AssertionError('live data loaded')),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def env(self, **values):
        clean = {k: v for k, v in os.environ.items()
                 if k not in ('VERCEL', 'COST_MONITOR_LIVE_ENABLED')}
        clean.update(values)
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_live_enabled_rules(self):
        cases = [({}, True), ({'VERCEL': '1'}, False),
                 ({'VERCEL': '1', 'COST_MONITOR_LIVE_ENABLED': '1'}, True),
                 ({'COST_MONITOR_LIVE_ENABLED': '0'}, False),
                 ({'VERCEL': '1', 'COST_MONITOR_LIVE_ENABLED': '0'}, False),
                 ({'COST_MONITOR_LIVE_ENABLED': 'true'}, False)]  # only exactly "1" enables
        for values, expected in cases:
            with self.subTest(values=values), \
                 mock.patch.dict(os.environ, values, clear=True):
                self.assertIs(app_module.live_enabled(), expected)

    def test_on_vercel_live_requests_are_403_without_aws(self):
        self.env(VERCEL='1')
        for path in ('/api/costs', '/api/alerts', '/api/detector-status'):
            with self.subTest(path=path):
                resp = self.client.get(f'{path}?mode=live')
                self.assertEqual(resp.status_code, 403)
                body = resp.get_json()
                self.assertEqual(set(body), {'error'})
                self.assertIn('Live mode is disabled on this deployment', body['error'])

    def test_on_vercel_default_is_demo_and_synthetic(self):
        self.env(VERCEL='1')
        for path in ('/api/costs', '/api/alerts', '/api/detector-status'):
            with self.subTest(path=path):
                resp = self.client.get(path)  # no mode param
                self.assertEqual(resp.status_code, 200)
                self.assertIs(resp.get_json()['synthetic'], True)
                self.assertEqual(resp.get_json()['meta']['mode'], 'demo')

    def test_on_vercel_page_defaults_to_demo_without_live_toggle(self):
        self.env(VERCEL='1')
        page = self.client.get('/').get_data(as_text=True)
        self.assertIn('data-live-enabled="false"', page)
        self.assertNotIn('data-mode="live"', page)
        self.assertIn('data-mode="demo" aria-pressed="true"', page)
        self.assertIn('id="synthetic-banner"', page)
        self.assertIn('id="mode-notice"', page)

    def test_explicit_disable_works_off_vercel(self):
        self.env(COST_MONITOR_LIVE_ENABLED='0')
        self.assertEqual(self.client.get('/api/costs?mode=live').status_code, 403)
        self.assertNotIn('data-mode="live"', self.client.get('/').get_data(as_text=True))

    def test_explicit_enable_on_vercel_allows_live(self):
        self.env(VERCEL='1', COST_MONITOR_LIVE_ENABLED='1')
        rows = [{'date': '2026-10-03', 'total_cost': 0.0, 'services': {}}]
        with mock.patch.object(app_module, '_load_live', return_value=(rows, 'dynamodb')):
            resp = self.client.get('/api/costs?mode=live')
        self.assertEqual(resp.status_code, 200)
        self.assertIs(resp.get_json()['synthetic'], False)
        self.assertIn('data-mode="live"', self.client.get('/').get_data(as_text=True))

    def test_bad_mode_still_400_when_live_disabled(self):
        self.env(VERCEL='1')
        self.assertEqual(self.client.get('/api/costs?mode=prod').status_code, 400)


if __name__ == '__main__':
    unittest.main(verbosity=2)
