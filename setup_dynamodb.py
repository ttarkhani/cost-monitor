import boto3
from botocore.exceptions import ClientError

TABLE_NAME = "CostMonitorSnapshots"

def create_table():
    dynamodb = boto3.client('dynamodb', region_name='us-east-1')

    try:
        dynamodb.describe_table(TableName=TABLE_NAME)
        print(f"Table '{TABLE_NAME}' already exists. Nothing to do.")
        return
    except ClientError as e:
        if e.response['Error']['Code'] != 'ResourceNotFoundException':
            raise

    print(f"Creating table '{TABLE_NAME}'...")

    dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {'AttributeName': 'account_id', 'KeyType': 'HASH'},
            {'AttributeName': 'date', 'KeyType': 'RANGE'}
        ],
        AttributeDefinitions=[
            {'AttributeName': 'account_id', 'AttributeType': 'S'},
            {'AttributeName': 'date', 'AttributeType': 'S'}
        ],
        BillingMode='PAY_PER_REQUEST'
    )

    print("Waiting for table to become active...")
    waiter = dynamodb.get_waiter('table_exists')
    waiter.wait(TableName=TABLE_NAME)
    print(f"Table '{TABLE_NAME}' is now ACTIVE.")


if __name__ == '__main__':
    create_table()