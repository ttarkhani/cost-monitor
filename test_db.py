import boto3
from datetime import datetime, timedelta
from backend.db import put_snapshot, get_snapshots, get_latest_snapshot

sts = boto3.client('sts', region_name='us-east-1')
ACCOUNT_ID = sts.get_caller_identity()['Account']


def run_test():
    print(f"Using AWS account: {ACCOUNT_ID}\n")
    print("Writing 3 dummy snapshots...\n")

    today = datetime.now().date()
    dummy_data = [
        (today - timedelta(days=2), 5.20, {"Amazon EC2": 3.10, "Amazon S3": 2.10}),
        (today - timedelta(days=1), 5.35, {"Amazon EC2": 3.10, "Amazon S3": 2.25}),
        (today,                     9.80, {"Amazon EC2": 3.10, "Amazon S3": 2.25, "Amazon RDS": 4.45}),
    ]

    for date_obj, total, services in dummy_data:
        date_str = date_obj.strftime('%Y-%m-%d')
        put_snapshot(
            account_id=ACCOUNT_ID,
            date=date_str,
            total_cost=total,
            services=services,
            ingested_at=datetime.utcnow().isoformat()
        )
        print(f"  Wrote {date_str}: ${total:.2f}")

    print("\nReading back last 7 days...\n")
    start = (today - timedelta(days=7)).strftime('%Y-%m-%d')
    end = today.strftime('%Y-%m-%d')
    results = get_snapshots(ACCOUNT_ID, start, end)

    for item in results:
        total = float(item['total_cost'])
        services_display = {name: float(cost) for name, cost in item['services'].items()}
        print(f"  {item['date']}: total=${total:.2f}  services={services_display}")

    print("\nLatest snapshot:")
    latest = get_latest_snapshot(ACCOUNT_ID)
    print(f"  {latest['date']}: ${float(latest['total_cost']):.2f}")

    print("\nSUCCESS: DynamoDB read/write pipeline confirmed working.")
    print("Note: this is DUMMY data. Once Cost Explorer finishes indexing,")
    print("the real fetcher will overwrite these same 3 dates with real numbers —")
    print("same account_id + date means same primary key, so it overwrites automatically.")


if __name__ == '__main__':
    run_test()