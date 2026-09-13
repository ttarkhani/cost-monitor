import boto3
from datetime import datetime, timedelta
from backend.db import get_snapshots
from backend.alerts import detect_anomalies

sts = boto3.client('sts', region_name='us-east-1')
ACCOUNT_ID = sts.get_caller_identity()['Account']


def run_test():
    today = datetime.now().date()
    start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    end = today.strftime('%Y-%m-%d')

    snapshots = get_snapshots(ACCOUNT_ID, start, end)
    print(f"Loaded {len(snapshots)} snapshots from DynamoDB.\n")

    for item in snapshots:
        print(f"  {item['date']}: ${float(item['total_cost']):.2f}")

    print("\nRunning anomaly detection (40% increase + $1.00 minimum)...\n")
    anomalies = detect_anomalies(snapshots, pct_threshold=0.4, min_abs_increase=1.0)

    if not anomalies:
        print("No anomalies detected.")
    else:
        for a in anomalies:
            print(
                f"  ANOMALY on {a['date']}: "
                f"${a['previous_cost']:.2f} -> ${a['current_cost']:.2f} "
                f"(+{a['increase_pct']:.1f}%, +${a['increase_abs']:.2f})"
            )

    print(f"\n{len(anomalies)} anomaly(ies) found out of {max(len(snapshots) - 1, 0)} day-over-day comparisons.")


if __name__ == '__main__':
    run_test()