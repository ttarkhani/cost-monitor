import json
import boto3

REGION = 'us-east-1'
USER_NAME = 'cost-monitor-dev'

sts = boto3.client('sts', region_name=REGION)
iam = boto3.client('iam', region_name=REGION)

ACCOUNT_ID = sts.get_caller_identity()['Account']


def ensure_user():
    try:
        iam.get_user(UserName=USER_NAME)
        print(f"IAM user '{USER_NAME}' already exists.")
    except iam.exceptions.NoSuchEntityException:
        iam.create_user(UserName=USER_NAME, Path='/',
                         Tags=[{'Key': 'Project', 'Value': 'cost-monitor'}])
        print(f"IAM user '{USER_NAME}' created.")


def attach_scoped_policy():
    """
    Policy for the dev user (local runs plus one-time provisioning).
    Statements are scoped to this project's named resources, except
    ce:GetCostAndUsage and sts:GetCallerIdentity, which do not support
    resource-level scoping and use "*". iam:PassRole is limited to the
    single Lambda role. Known limitation: scoping PassRole does not by
    itself make this policy escalation-proof. The user can also modify
    that one role (AttachRolePolicy, PutRolePolicy) and update and invoke
    the function that runs under it, so it can widen what the role may
    do. A stricter setup would split provisioning from day-to-day runtime
    identities, or cap the role with a permissions boundary.
    """
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "CostExplorerReadOnly", "Effect": "Allow",
             "Action": ["ce:GetCostAndUsage"], "Resource": "*"},
            {"Sid": "CallerIdentity", "Effect": "Allow",
             "Action": ["sts:GetCallerIdentity"], "Resource": "*"},
            {"Sid": "ThisTableOnly", "Effect": "Allow",
             "Action": ["dynamodb:CreateTable", "dynamodb:DescribeTable",
                        "dynamodb:PutItem", "dynamodb:Query"],
             "Resource": f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/CostMonitorSnapshots"},
            {"Sid": "ThisTopicOnly", "Effect": "Allow",
             "Action": ["sns:CreateTopic", "sns:Publish", "sns:Subscribe",
                        "sns:ListSubscriptionsByTopic"],
             "Resource": f"arn:aws:sns:{REGION}:{ACCOUNT_ID}:cost-monitor-alerts"},
            {"Sid": "ThisLambdaRoleOnly", "Effect": "Allow",
             "Action": ["iam:CreateRole", "iam:GetRole",
                        "iam:AttachRolePolicy", "iam:PutRolePolicy"],
             "Resource": f"arn:aws:iam::{ACCOUNT_ID}:role/cost-monitor-lambda-role"},
            {"Sid": "PassOnlyTheLambdaRole", "Effect": "Allow",
             "Action": ["iam:PassRole"],
             "Resource": f"arn:aws:iam::{ACCOUNT_ID}:role/cost-monitor-lambda-role"},
            {"Sid": "ThisFunctionOnly", "Effect": "Allow",
             "Action": ["lambda:CreateFunction", "lambda:UpdateFunctionCode",
                        "lambda:GetFunction", "lambda:AddPermission",
                        "lambda:InvokeFunction"],
             "Resource": f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:cost-monitor-daily-ingestion"},
            {"Sid": "ThisRuleOnly", "Effect": "Allow",
             "Action": ["events:PutRule", "events:PutTargets"],
             "Resource": f"arn:aws:events:{REGION}:{ACCOUNT_ID}:rule/cost-monitor-daily-trigger"},
        ]
    }

    iam.put_user_policy(
        UserName=USER_NAME,
        PolicyName='cost-monitor-scoped-access',
        PolicyDocument=json.dumps(policy)
    )
    print("Attached a scoped policy -- every statement limited to this")
    print("project's specific named resources, not the whole account.")


def ensure_access_key():
    existing = iam.list_access_keys(UserName=USER_NAME)['AccessKeyMetadata']
    if existing:
        print(f"\nUser already has {len(existing)} access key(s). Not creating a new one.")
        print("If you don't have a saved secret for one, delete it in the console")
        print("and re-run this script to get a fresh one.")
        return

    response = iam.create_access_key(UserName=USER_NAME)
    key = response['AccessKey']

    print("\n" + "=" * 60)
    print("NEW ACCESS KEY -- THE SECRET IS SHOWN ONLY THIS ONCE")
    print("=" * 60)
    print(f"Access Key ID:     {key['AccessKeyId']}")
    print(f"Secret Access Key: {key['SecretAccessKey']}")
    print("=" * 60)
    print("\nSave these now -- AWS will never show this secret again.")


def main():
    print(f"Account: {ACCOUNT_ID}\n")
    ensure_user()
    attach_scoped_policy()
    ensure_access_key()

    print("\nNext steps, in order -- do NOT skip step 2:")
    print("1. Run: aws configure")
    print("   (paste in the new Access Key ID / Secret Access Key above)")
    print("2. Run: python3.14 run_fetch.py")
    print("   Confirm it still works exactly as before, under the new credentials.")
    print("3. ONLY once step 2 succeeds: delete the OLD root access key in the")
    print("   AWS Console (Security credentials -> Access keys).")


if __name__ == '__main__':
    main()