import boto3
from backend.cost_fetcher import fetch_and_store_yesterday


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


if __name__ == '__main__':
    main()