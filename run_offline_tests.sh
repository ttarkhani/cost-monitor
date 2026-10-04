#!/usr/bin/env bash
# Runs every test that needs no AWS access. AWS credentials are blanked
# for the run, so a test that accidentally reached AWS would fail instead
# of quietly using real resources.
# Usage: ./run_offline_tests.sh   (PYTHON=... to override the interpreter)
set -u
cd "$(dirname "$0")"
PYTHON="${PYTHON:-./venv/bin/python}"
export AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE

fail=0
for t in test_anomaly_validation.py test_service_validation.py test_cache.py test_pipeline.py \
         test_demo_data.py test_history.py test_app.py test_contract.py test_lambda_handler.py; do
  if "$PYTHON" "$t" > /dev/null 2>&1; then
    echo "ok    $t"
  else
    echo "FAIL  $t"; "$PYTHON" "$t" 2>&1 | tail -20; fail=1
  fi
done
if node --test 'tests/js/*.test.mjs' > /dev/null 2>&1; then
  echo "ok    node --test tests/js"
else
  echo "FAIL  node --test tests/js"; node --test 'tests/js/*.test.mjs' 2>&1 | tail -30; fail=1
fi
exit $fail
