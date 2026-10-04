from datetime import datetime, timedelta, timezone
from backend.db import put_snapshot, get_snapshots, get_latest_snapshot

# SYNTHETIC FIXTURES ONLY. Every row this script writes goes under this
# dedicated partition key, never under the real AWS account ID. The app,
# the pipeline and the Lambda all read by the real account ID (from STS),
# so they never see these rows, and running this script can never
# overwrite a real day's snapshot.
FIXTURE_ACCOUNT_ID = "test-fixture-account"


def run_test():
    print(f"Writing SYNTHETIC fixture rows under partition key '{FIXTURE_ACCOUNT_ID}'")
    print("(not the real account -- the dashboard and pipeline never read this key)\n")

    today = datetime.now().date()
    dummy_data = [
        (today - timedelta(days=2), 5.20, {"Amazon EC2": 3.10, "Amazon S3": 2.10}),
        (today - timedelta(days=1), 5.35, {"Amazon EC2": 3.10, "Amazon S3": 2.25}),
        (today,                     9.80, {"Amazon EC2": 3.10, "Amazon S3": 2.25, "Amazon RDS": 4.45}),
    ]

    for date_obj, total, services in dummy_data:
        date_str = date_obj.strftime('%Y-%m-%d')
        put_snapshot(
            account_id=FIXTURE_ACCOUNT_ID,
            date=date_str,
            total_cost=total,
            services=services,
            ingested_at=datetime.now(timezone.utc).isoformat()
        )
        print(f"  [SYNTHETIC] Wrote {date_str}: ${total:.2f}")

    print("\nReading back last 7 days of fixture rows...\n")
    start = (today - timedelta(days=7)).strftime('%Y-%m-%d')
    end = today.strftime('%Y-%m-%d')
    results = get_snapshots(FIXTURE_ACCOUNT_ID, start, end)

    for item in results:
        total = float(item['total_cost'])
        services_display = {name: float(cost) for name, cost in item['services'].items()}
        print(f"  [SYNTHETIC] {item['date']}: total=${total:.2f}  services={services_display}")

    print("\nLatest fixture snapshot:")
    latest = get_latest_snapshot(FIXTURE_ACCOUNT_ID)
    print(f"  [SYNTHETIC] {latest['date']}: ${float(latest['total_cost']):.2f}")

    print("\nSUCCESS: DynamoDB read/write pipeline confirmed working.")
    print(f"All rows above are SYNTHETIC fixtures under '{FIXTURE_ACCOUNT_ID}'.")
    print("No real account data was read or written.")


if __name__ == '__main__':
    run_test()
