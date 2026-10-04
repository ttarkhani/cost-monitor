from datetime import timedelta

# How many calendar days of history the anomaly detector sees. Shared by
# the daily pipeline (what gets alerted on) and the dashboard API (what
# gets shown), so the two can never disagree about which days count.
HISTORY_DAYS = 60


def history_window(today):
    """(start, end) ISO date strings, inclusive, for the HISTORY_DAYS window ending today."""
    start = (today - timedelta(days=HISTORY_DAYS)).isoformat()
    return start, today.isoformat()
