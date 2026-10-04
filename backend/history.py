"""
Describes the state of the stored history from the detector's point of
view: how much usable baseline it has, where the ingestion gaps are, and
whether ingestion has gone stale. Read-only; does not change detection.

Mirrors the rules in backend/alerts.py (which is frozen): only a
transition between consecutive calendar days counts toward the baseline,
and a transition is evaluated only when at least MIN_WINDOW earlier valid
transitions exist.
"""
from datetime import date

from backend.alerts import MIN_WINDOW

# Ingestion normally lags one day (the pipeline stores "yesterday"), so a
# latest snapshot more than this many days old means runs are being missed.
STALE_AFTER_DAYS = 2


def find_gaps(dates):
    """Non-consecutive neighbours in a sorted list of ISO dates."""
    gaps = []
    for prev, curr in zip(dates, dates[1:]):
        apart = (date.fromisoformat(curr) - date.fromisoformat(prev)).days
        if apart != 1:
            # 'days' is how many calendar days have no snapshot between them.
            gaps.append({'from': prev, 'to': curr, 'days': apart - 1, 'days_apart': apart})
    return gaps


def detector_status(snapshots, today):
    """
    snapshots: list of {'date': 'YYYY-MM-DD', ...} (any order).
    today: datetime.date, normally the current UTC date.

    state is 'active' only once at least one transition has actually been
    evaluated (valid_transitions > MIN_WINDOW), so "nothing unusual" in the
    UI always means at least one day really was judged. With exactly
    MIN_WINDOW valid transitions the baseline is complete but nothing has
    been evaluated yet, so it is still 'warming_up'.
    """
    dates = sorted(s['date'] for s in snapshots)
    gaps = find_gaps(dates)
    valid = max(len(dates) - 1, 0) - len(gaps)
    evaluated = max(valid - MIN_WINDOW, 0)

    latest = dates[-1] if dates else None
    days_since = (today - date.fromisoformat(latest)).days if latest else None

    return {
        'snapshot_count': len(dates),
        'valid_transitions': valid,
        'required_baseline': MIN_WINDOW,
        'baseline_progress': min(valid, MIN_WINDOW),
        'evaluated_transitions': evaluated,
        'state': 'active' if evaluated > 0 else 'warming_up',
        'gaps': gaps,
        'first_snapshot_date': dates[0] if dates else None,
        'latest_snapshot_date': latest,
        'days_since_latest': days_since,
        'stale_after_days': STALE_AFTER_DAYS,
        'stale': days_since is not None and days_since > STALE_AFTER_DAYS,
    }
