import boto3

TOPIC_NAME = "cost-monitor-alerts"

_sns_client = boto3.client('sns', region_name='us-east-1')


def get_or_create_topic():
    """
    Idempotent: SNS create_topic returns the existing TopicArn if a topic
    with this exact name already exists, rather than creating a duplicate.
    """
    response = _sns_client.create_topic(Name=TOPIC_NAME)
    return response['TopicArn']


def format_alert_message(anomalies):
    """
    Turns a list of anomaly dicts (from backend.alerts.detect_anomalies)
    into a plain-text subject + body for an SNS email notification.
    """
    lines = []
    for a in anomalies:
        label = a['service'] if a['level'] == 'service' else 'Total spend'
        if a.get('is_new'):
            change = f"NEW -- ${a['current_cost']:.2f}"
        else:
            z = f"z={a['modified_z']}" if a['modified_z'] is not None else "zero-variance window"
            change = f"${a['previous_cost']:.2f} -> ${a['current_cost']:.2f}  ({z})"
        lines.append(f"[{a['level'].upper()}] {label} -- {a['date']}: {change}")

    body = "Cost Monitor detected the following anomalies:\n\n" + "\n".join(lines)
    subject = f"Cost Monitor: {len(anomalies)} anomaly(ies) detected"
    return subject, body


def send_alert(anomalies):
    """
    Publishes an SNS notification if anomalies is non-empty. Does nothing
    (no API call, no cost) if the list is empty.
    """
    if not anomalies:
        return None

    topic_arn = get_or_create_topic()
    subject, body = format_alert_message(anomalies)

    response = _sns_client.publish(
        TopicArn=topic_arn,
        Subject=subject,
        Message=body,
    )
    return response['MessageId']