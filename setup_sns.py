import os
import boto3
from backend.alerting import get_or_create_topic, TOPIC_NAME

_sns_client = boto3.client('sns', region_name='us-east-1')


def main():
    email = os.environ.get('ALERT_EMAIL')
    if not email:
        print("ERROR: ALERT_EMAIL environment variable is not set.")
        print("Run:  export ALERT_EMAIL=your_real_email@example.com")
        print("...then re-run this script.")
        return

    print(f"Creating/finding SNS topic '{TOPIC_NAME}'...")
    topic_arn = get_or_create_topic()
    print(f"Topic ARN: {topic_arn}\n")

    print(f"Checking existing subscriptions for {email}...")
    existing = _sns_client.list_subscriptions_by_topic(TopicArn=topic_arn)
    already_subscribed = any(
        sub['Endpoint'] == email for sub in existing['Subscriptions']
    )

    if already_subscribed:
        print(f"'{email}' is already subscribed (or pending confirmation). Nothing to do.")
        return

    print(f"Subscribing '{email}'...")
    _sns_client.subscribe(TopicArn=topic_arn, Protocol='email', Endpoint=email)

    print("\nSUCCESS: subscription request sent.")
    print(f"Check the inbox for '{email}' -- AWS just sent a confirmation email.")
    print("You MUST click the confirmation link before any alert will actually")
    print("reach that inbox. Until then, the subscription sits in")
    print("'PendingConfirmation' and SNS silently drops anything published to it.")


if __name__ == '__main__':
    main()