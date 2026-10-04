import boto3
from datetime import datetime
from backend.config import history_window
from backend.cost_fetcher import fetch_and_store_yesterday
from backend.db import get_snapshots
from backend.alerts import detect_anomalies
from backend.alerting import send_alert

_sts_client = boto3.client('sts', region_name='us-east-1')


def _today():
    # Separate function so offline tests can pin "today" without AWS.
    return datetime.now().date()


def run_daily_pipeline():
    """
    The full daily job: fetch yesterday's real cost data, store it, run
    anomaly detection over the shared HISTORY_DAYS window, and alert only
    on anomalies dated the day that was just ingested.

    Detection still runs over the whole window (the baseline needs it),
    but an anomaly from an earlier day was already alerted on by the run
    that ingested that day, so re-sending it would repeat the same email
    every day for as long as it stays inside the window.

    Caveat: re-running this manually for the same date (e.g. run_fetch.py
    twice in one day) re-ingests that date and can re-alert for it.

    Shared by run_fetch.py (manual/local) and the Lambda handler
    (scheduled) so the two never drift out of sync with each other.
    """
    account_id = _sts_client.get_caller_identity()['Account']
    result = {'account_id': account_id, 'ingested': False, 'anomaly_count': 0,
              'new_anomaly_count': 0, 'alert_sent': False}

    try:
        fetch_result = fetch_and_store_yesterday(account_id)
        result['ingested'] = True
        result['date'] = fetch_result['date']
        result['total_cost'] = fetch_result['total_cost']
        result['service_count'] = fetch_result['service_count']
    except Exception as e:
        result['error'] = str(e)
        return result

    start, end = history_window(_today())
    snapshots = get_snapshots(account_id, start, end)

    anomalies = detect_anomalies(snapshots)
    new_anomalies = [a for a in anomalies if a['date'] == result['date']]
    # anomaly_count keeps its old meaning (everything flagged in the window)
    # for backward compatibility; new_anomaly_count is what was alerted on.
    result['anomaly_count'] = len(anomalies)
    result['new_anomaly_count'] = len(new_anomalies)

    if new_anomalies:
        send_alert(new_anomalies)
        result['alert_sent'] = True

    return result
