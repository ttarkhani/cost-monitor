import boto3
from datetime import datetime, timedelta
from backend.cost_fetcher import fetch_and_store_yesterday
from backend.db import get_snapshots
from backend.alerts import detect_anomalies
from backend.alerting import send_alert


def main():
    sts = boto3.client('sts', region_name='us-east-1')
    account_id = sts.get_caller_identity()['Account']

    print(f"Fetching yesterday's cost data for account {account_id}...\n")

    try:
        result = fetch_and_store_yesterday(account_id)
        print(f"SUCCESS: Stored snapshot for {result['date']}")
        print(f"  Total cost: ${result['total_cost']:.4f}")
        print(f"  Services with spend: {result['service_count']}")
    except Exception as e:
        print(f"ERROR: {e}")
        print("\nThis is expected right now if Cost Explorer is still indexing")
        print("your account (can take up to 24h after first enabling it).")
        return

    print("\nChecking for anomalies against full history...")
    today = datetime.now().date()
    start = (today - timedelta(days=60)).strftime('%Y-%m-%d')
    end = today.strftime('%Y-%m-%d')
    snapshots = get_snapshots(account_id, start, end)

    anomalies = detect_anomalies(snapshots)
    if anomalies:
        print(f"  {len(anomalies)} anomaly(ies) detected -- sending alert...")
        send_alert(anomalies)
        print("  Alert sent.")
    else:
        print("  No anomalies detected. No alert sent.")


if __name__ == '__main__':
    main()