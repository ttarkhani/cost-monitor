import boto3
from datetime import datetime, timedelta
from backend.cost_fetcher import fetch_and_store_yesterday
from backend.db import get_snapshots
from backend.alerts import detect_anomalies
from backend.alerting import send_alert

_sts_client = boto3.client('sts', region_name='us-east-1')


def run_daily_pipeline():
    """
    The full daily job: fetch yesterday's real cost data, store it, check
    the full history for anomalies, and alert if anything's flagged.

    Shared by run_fetch.py (manual/local) and the Lambda handler
    (scheduled) so the two never drift out of sync with each other.
    """
    account_id = _sts_client.get_caller_identity()['Account']
    result = {'account_id': account_id, 'ingested': False, 'anomaly_count': 0, 'alert_sent': False}

    try:
        fetch_result = fetch_and_store_yesterday(account_id)
        result['ingested'] = True
        result['date'] = fetch_result['date']
        result['total_cost'] = fetch_result['total_cost']
        result['service_count'] = fetch_result['service_count']
    except Exception as e:
        result['error'] = str(e)
        return result

    today = datetime.now().date()
    start = (today - timedelta(days=60)).strftime('%Y-%m-%d')
    end = today.strftime('%Y-%m-%d')
    snapshots = get_snapshots(account_id, start, end)

    anomalies = detect_anomalies(snapshots)
    result['anomaly_count'] = len(anomalies)

    if anomalies:
        send_alert(anomalies)
        result['alert_sent'] = True

    return result