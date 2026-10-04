"""
Offline tests for lambda_handler.handler. No AWS: the pipeline is mocked.

Run: ./venv/bin/python test_lambda_handler.py
"""
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import lambda_handler


class HandlerTests(unittest.TestCase):

    def call(self, result):
        with mock.patch.object(lambda_handler, 'run_daily_pipeline', return_value=result), \
             redirect_stdout(io.StringIO()) as out:
            try:
                return lambda_handler.handler({}, None), out.getvalue()
            except lambda_handler.IngestionFailed as e:
                return e, out.getvalue()

    def test_success_returns_result(self):
        result = {'ingested': True, 'date': '2099-01-01', 'anomaly_count': 0,
                  'new_anomaly_count': 0, 'alert_sent': False}
        returned, logged = self.call(result)
        self.assertEqual(returned, result)
        self.assertIn('"ingested": true', logged)

    def test_ingestion_failure_raises_after_logging(self):
        returned, logged = self.call({'ingested': False, 'error': 'Cost Explorer returned no data'})
        self.assertIsInstance(returned, lambda_handler.IngestionFailed)
        self.assertIn('Cost Explorer returned no data', str(returned))
        self.assertIn('"ingested": false', logged)  # result is still logged before raising

    def test_pipeline_exception_propagates(self):
        with mock.patch.object(lambda_handler, 'run_daily_pipeline', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                lambda_handler.handler({}, None)


if __name__ == '__main__':
    unittest.main(verbosity=2)
