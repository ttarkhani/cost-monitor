import json
from backend.pipeline import run_daily_pipeline


def handler(event, context):
    """
    Entry point AWS Lambda calls on the daily EventBridge schedule. Just a
    thin wrapper around the same pipeline run_fetch.py uses -- never a
    second implementation to keep in sync.
    """
    result = run_daily_pipeline()
    print(json.dumps(result, default=str))  # lands in CloudWatch Logs
    return result