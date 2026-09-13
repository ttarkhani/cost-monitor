import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key

TABLE_NAME = "CostMonitorSnapshots"

_dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
_table = _dynamodb.Table(TABLE_NAME)


def _to_decimal(value):
    # DynamoDB's resource API rejects native Python floats.
    # Going through str() avoids binary float precision issues.
    return Decimal(str(value))


def put_snapshot(account_id, date, total_cost, services, ingested_at):
    """
    Store one day's cost snapshot. Writing to the same account_id + date
    overwrites whatever was there before.

    services: dict like {"Amazon EC2": 1.23, "Amazon S3": 0.04}
    """
    item = {
        'account_id': account_id,
        'date': date,
        'total_cost': _to_decimal(total_cost),
        'services': {name: _to_decimal(cost) for name, cost in services.items()},
        'ingested_at': ingested_at,
    }
    _table.put_item(Item=item)
    return item


def get_snapshots(account_id, start_date, end_date):
    """
    Return snapshots for account_id where start_date <= date <= end_date,
    ordered oldest to newest — the order a spend-over-time chart wants.
    """
    response = _table.query(
        KeyConditionExpression=Key('account_id').eq(account_id) & Key('date').between(start_date, end_date)
    )
    return response.get('Items', [])


def get_latest_snapshot(account_id):
    """Return the single most recent snapshot, or None if there's no data yet."""
    response = _table.query(
        KeyConditionExpression=Key('account_id').eq(account_id),
        ScanIndexForward=False,
        Limit=1
    )
    items = response.get('Items', [])
    return items[0] if items else None
