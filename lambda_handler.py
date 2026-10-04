import json
from backend.pipeline import run_daily_pipeline


class IngestionFailed(RuntimeError):
    pass


def handler(event, context):
    """
    Entry point AWS Lambda calls on the daily EventBridge schedule. Just a
    thin wrapper around the same pipeline run_fetch.py uses -- never a
    second implementation to keep in sync.

    run_daily_pipeline() catches ingestion errors and returns a result
    with ingested=False. Raising here turns that into a failed invocation,
    so Lambda's Errors metric (and anything alarming on it) reflects a
    day that was not ingested, instead of reporting success.
    """
    result = run_daily_pipeline()
    print(json.dumps(result, default=str))  # lands in CloudWatch Logs
    if not result.get('ingested'):
        raise IngestionFailed(f"Ingestion failed: {result.get('error', 'unknown error')}")
    return result
