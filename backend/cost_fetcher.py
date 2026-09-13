import boto3
from datetime import datetime, timedelta
from backend.db import put_snapshot

_ce_client = boto3.client('ce', region_name='us-east-1')


def fetch_and_store_yesterday(account_id):
    """
    Pull yesterday's cost data from Cost Explorer and store it in DynamoDB.

    Uses yesterday, not today, because Cost Explorer has a ~24-36hr billing
    lag — today's data is always incomplete or unavailable. This is meant
    to run once per day (e.g. via cron or a scheduled Lambda).
    """
    yesterday = (datetime.now().date() - timedelta(days=1))
    # Cost Explorer's End date is exclusive, so End = yesterday + 1 day
    # gives us exactly one day of data: yesterday itself.
    date_str = yesterday.strftime('%Y-%m-%d')
    end_str = (yesterday + timedelta(days=1)).strftime('%Y-%m-%d')

    response = _ce_client.get_cost_and_usage(
        TimePeriod={'Start': date_str, 'End': end_str},
        Granularity='DAILY',
        Metrics=['UnblendedCost'],
        GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
    )

    if not response['ResultsByTime']:
        raise ValueError(f"Cost Explorer returned no data for {date_str}")

    day_result = response['ResultsByTime'][0]
    services = {}
    total_cost = 0.0

    for group in day_result['Groups']:
        service_name = group['Keys'][0]
        cost = float(group['Metrics']['UnblendedCost']['Amount'])
        if cost > 0:
            services[service_name] = cost
            total_cost += cost

    snapshot = put_snapshot(
        account_id=account_id,
        date=date_str,
        total_cost=total_cost,
        services=services,
        ingested_at=datetime.now().isoformat()
    )

    return {
        'date': date_str,
        'total_cost': round(total_cost, 4),
        'service_count': len(services),
    }