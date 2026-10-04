"""
API contract check between the Flask backend and the dashboard JS.

tests/fixtures/api_demo_contract.json is a recorded copy of the demo-mode
responses (SYNTHETIC data, pinned date). This test regenerates them and
fails if the backend's payload shape or content drifts from the fixture.
The node tests (tests/js/) feed the same fixture through the dashboard's
view logic, so a field the frontend reads cannot disappear from the API
without one side failing.

Run:    ./venv/bin/python test_contract.py
Update: ./venv/bin/python test_contract.py --update   (after an intended change;
        then rerun `node --test tests/js/` to confirm the frontend still agrees)
"""
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import app as app_module

FIXTURE = Path(__file__).parent / 'tests' / 'fixtures' / 'api_demo_contract.json'
PINNED_TODAY = date(2026, 10, 4)
ENDPOINTS = {
    'costs': '/api/costs?mode=demo&days=60',
    'alerts': '/api/alerts?mode=demo&days=60',
    'detector_status': '/api/detector-status?mode=demo',
}


def record():
    client = app_module.create_app().test_client()
    out = {'_note': 'SYNTHETIC demo-mode API responses recorded by test_contract.py '
                    f'with today pinned to {PINNED_TODAY.isoformat()}. Not real AWS data.'}
    with mock.patch.object(app_module, '_utc_today', lambda: PINNED_TODAY), \
         mock.patch.object(app_module, 'get_account_id', side_effect=AssertionError('demo touched AWS')):
        for name, url in ENDPOINTS.items():
            body = client.get(url).get_json()
            body['meta'].pop('elapsed_ms')  # timing varies run to run
            out[name] = body
    return out


class ContractTests(unittest.TestCase):

    def test_demo_responses_match_fixture(self):
        expected = json.loads(FIXTURE.read_text())
        self.assertEqual(record(), expected,
                         'API payload drifted from tests/fixtures/api_demo_contract.json; '
                         'if intended, rerun with --update and check the node tests')

    def test_fixture_is_labeled_synthetic(self):
        fixture = json.loads(FIXTURE.read_text())
        for name in ENDPOINTS:
            self.assertIs(fixture[name]['synthetic'], True)


if __name__ == '__main__':
    if '--update' in sys.argv:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(record(), indent=1, sort_keys=True) + '\n')
        print(f'wrote {FIXTURE}')
    else:
        unittest.main(verbosity=2)
