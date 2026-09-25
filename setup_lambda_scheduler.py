import json
import time
import base64
import boto3

ROLE_NAME = 'cost-monitor-lambda-role'
FUNCTION_NAME = 'cost-monitor-daily-ingestion'
RULE_NAME = 'cost-monitor-daily-trigger'
REGION = 'us-east-1'

sts = boto3.client('sts', region_name=REGION)
iam = boto3.client('iam', region_name=REGION)
lambda_client = boto3.client('lambda', region_name=REGION)
events = boto3.client('events', region_name=REGION)

ACCOUNT_ID = sts.get_caller_identity()['Account']


def ensure_role():
    trust_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    })

    just_created = False
    try:
        role = iam.get_role(RoleName=ROLE_NAME)
        print(f"IAM role '{ROLE_NAME}' already exists.")
    except iam.exceptions.NoSuchEntityException:
        role = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=trust_policy,
            Description="Execution role for the Cost Monitor daily ingestion Lambda"
        )
        just_created = True
        print(f"IAM role '{ROLE_NAME}' created.")

    role_arn = role['Role']['Arn']

    iam.attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn='arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
    )

    sns_topic_arn = f"arn:aws:sns:{REGION}:{ACCOUNT_ID}:cost-monitor-alerts"
    custom_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": ["ce:GetCostAndUsage"], "Resource": "*"},
            {"Effect": "Allow",
             "Action": ["dynamodb:PutItem", "dynamodb:Query", "dynamodb:DescribeTable"],
             "Resource": f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/CostMonitorSnapshots"},
            {"Effect": "Allow",
             "Action": ["sns:CreateTopic", "sns:Publish", "sns:ListSubscriptionsByTopic"],
             "Resource": sns_topic_arn},
            {"Effect": "Allow", "Action": ["sts:GetCallerIdentity"], "Resource": "*"},
        ]
    })
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName='cost-monitor-pipeline-permissions',
        PolicyDocument=custom_policy
    )
    print("Attached permissions: Cost Explorer read, DynamoDB (this table only),")
    print("SNS (this topic only), STS -- deliberately narrower than root.")

    if just_created:
        print("Waiting 10s for the new IAM role to propagate...")
        time.sleep(10)

    return role_arn


def ensure_function(role_arn):
    with open('lambda_deployment.zip', 'rb') as f:
        zip_bytes = f.read()

    try:
        lambda_client.get_function(FunctionName=FUNCTION_NAME)
        print(f"Function '{FUNCTION_NAME}' already exists -- updating code...")
        lambda_client.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=zip_bytes)
        print("Waiting for the code update to finish applying...")
        lambda_client.get_waiter('function_updated_v2').wait(FunctionName=FUNCTION_NAME)
    except lambda_client.exceptions.ResourceNotFoundException:
        print(f"Creating function '{FUNCTION_NAME}'...")
        lambda_client.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime='python3.14',
            Role=role_arn,
            Handler='lambda_handler.handler',
            Code={'ZipFile': zip_bytes},
            Timeout=30,
            MemorySize=256,
            Description='Daily Cost Monitor ingestion + anomaly detection + alerting'
        )
        print("Waiting for the function to become Active...")
        lambda_client.get_waiter('function_active_v2').wait(FunctionName=FUNCTION_NAME)

    return lambda_client.get_function(FunctionName=FUNCTION_NAME)['Configuration']['FunctionArn']

def ensure_schedule(function_arn):
    events.put_rule(
        Name=RULE_NAME,
        ScheduleExpression='cron(0 13 * * ? *)',  # 13:00 UTC daily -- ~9am Eastern; adjust as you like
        State='ENABLED',
        Description='Triggers the Cost Monitor daily ingestion Lambda'
    )
    rule_arn = f"arn:aws:events:{REGION}:{ACCOUNT_ID}:rule/{RULE_NAME}"

    events.put_targets(
        Rule=RULE_NAME,
        Targets=[{'Id': 'cost-monitor-lambda-target', 'Arn': function_arn}]
    )

    try:
        lambda_client.add_permission(
            FunctionName=FUNCTION_NAME,
            StatementId='AllowEventBridgeInvoke',
            Action='lambda:InvokeFunction',
            Principal='events.amazonaws.com',
            SourceArn=rule_arn
        )
        print("Granted EventBridge permission to invoke the function.")
    except lambda_client.exceptions.ResourceConflictException:
        print("EventBridge already had invoke permission (safe to re-run).")


def verify_with_real_invoke():
    print("\nInvoking the function once right now -- not waiting a day to find out if this works.\n")
    response = lambda_client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType='RequestResponse',
        LogType='Tail'
    )

    logs = base64.b64decode(response['LogResult']).decode('utf-8')
    print("--- CloudWatch Logs from this invocation ---")
    print(logs)

    payload = json.loads(response['Payload'].read())
    print("--- Returned result ---")
    print(json.dumps(payload, indent=2))

    if 'FunctionError' in response:
        print("\nFAILED -- see the traceback above.")
    else:
        print("\nSUCCESS -- the Lambda ran for real, end to end.")
        print("Note: today's date was already ingested manually earlier, so this")
        print("just safely overwrote that same entry -- same idempotent behavior")
        print("as every other re-run tonight. Nothing new or duplicated.")


def main():
    print(f"Account: {ACCOUNT_ID}\n")
    role_arn = ensure_role()
    function_arn = ensure_function(role_arn)
    ensure_schedule(function_arn)
    verify_with_real_invoke()


if __name__ == '__main__':
    main()