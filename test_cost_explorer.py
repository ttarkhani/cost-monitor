import boto3
from datetime import datetime, timedelta

def test_cost_explorer_access():
    """
    Read-only test: confirms Cost Explorer API access and shows
    real cost data from the last 7 days. Nothing is stored.
    """
    ce_client = boto3.client('ce', region_name='us-east-1')

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=7)

    print(f"Querying costs from {start_date} to {end_date}...\n")

    try:
        response = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['UnblendedCost'],
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
        )
    except Exception as e:
        print(f"ERROR: {e}\n")
        print("Common causes:")
        print("1. Cost Explorer hasn't been enabled yet in the AWS Console")
        print("   -> Go to Billing and Cost Management > Cost Explorer > Enable")
        print("   -> Can take up to 24 hours to activate")
        print("2. AWS credentials not configured correctly (run 'aws configure')")
        print("3. New account with no billing history yet")
        return

    print("SUCCESS: Cost Explorer API is accessible.\n")
    print("=" * 55)
    print("COSTS BY SERVICE (Last 7 Days)")
    print("=" * 55)

    grand_total = 0.0
    services_seen = set()

    for day in response['ResultsByTime']:
        date = day['TimePeriod']['Start']
        day_total = 0.0
        print(f"\n{date}:")

        for group in day['Groups']:
            service = group['Keys'][0]
            cost = float(group['Metrics']['UnblendedCost']['Amount'])
            day_total += cost
            if cost > 0:
                services_seen.add(service)
                print(f"  {service:<35} ${cost:.4f}")

        grand_total += day_total
        print(f"  {'DAILY TOTAL':<35} ${day_total:.4f}")

    print("\n" + "=" * 55)
    print(f"7-DAY TOTAL:      ${grand_total:.4f}")
    print(f"SERVICES ACTIVE:  {len(services_seen)}")
    print("=" * 55)

    if grand_total == 0:
        print("\nAll costs are $0.00 — you're within free tier.")
        print("That's fine: we'll build real monitoring/alerting,")
        print("just without a cost-savings number to report.")
    else:
        print(f"\nReal spend detected: ${grand_total:.2f} over 7 days.")
        print("Worth checking for anything we can genuinely optimize.")


if __name__ == '__main__':
    test_cost_explorer_access()