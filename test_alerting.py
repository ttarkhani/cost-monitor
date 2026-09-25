import boto3
from backend.alerting import get_or_create_topic, send_alert

_sns_client = boto3.client('sns', region_name='us-east-1')


def check_subscription_confirmed(topic_arn):
    response = _sns_client.list_subscriptions_by_topic(TopicArn=topic_arn)
    subs = response['Subscriptions']
    if not subs:
        return False, "No subscriptions found on this topic at all. Run setup_sns.py first."

    pending = [s for s in subs if s['SubscriptionArn'] == 'PendingConfirmation']
    confirmed = [s for s in subs if s['SubscriptionArn'] != 'PendingConfirmation']

    if confirmed:
        return True, f"{len(confirmed)} confirmed subscriber(s): {[s['Endpoint'] for s in confirmed]}"
    if pending:
        return False, (f"{len(pending)} subscriber(s) still PENDING confirmation: "
                        f"{[s['Endpoint'] for s in pending]}. Check that inbox and click "
                        f"the confirmation link, then re-run this test.")
    return False, "Unexpected subscription state."


def run_test():
    print("=" * 60)
    print("SNS alerting test -- SYNTHETIC anomaly data")
    print("=" * 60)

    topic_arn = get_or_create_topic()
    print(f"\nTopic ARN: {topic_arn}")

    ok, message = check_subscription_confirmed(topic_arn)
    print(f"Subscription status: {message}\n")

    if not ok:
        print("Stopping here -- publishing now would succeed on the AWS side,")
        print("but nothing would actually land in an inbox to verify against.")
        return

    synthetic_anomalies = [
        {
            'level': 'aggregate', 'service': None, 'date': '2099-01-09',
            'previous_date': '2099-01-08', 'previous_cost': 5.20, 'current_cost': 25.00,
            'delta': 19.80, 'modified_z': 42.1, 'status': 'anomaly', 'flagged': True,
        },
        {
            'level': 'service', 'service': 'Amazon RDS', 'date': '2099-01-09',
            'previous_date': '2099-01-08', 'previous_cost': 0.0, 'current_cost': 18.00,
            'delta': 18.00, 'modified_z': None, 'status': 'anomaly', 'flagged': True,
            'is_new': True,
        },
    ]

    print("This is a SYNTHETIC test message -- not a real detected anomaly.")
    print("Publishing to SNS now...\n")

    message_id = send_alert(synthetic_anomalies)
    print(f"Published. SNS MessageId: {message_id}")
    print("\nThis confirms AWS accepted and queued the message for delivery.")
    print("It does NOT confirm delivery itself -- check the actual inbox")
    print("in the next minute or two and report back what you see.")


if __name__ == '__main__':
    run_test()