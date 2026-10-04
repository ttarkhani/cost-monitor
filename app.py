import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from botocore.exceptions import BotoCoreError, ClientError
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from backend import cache, demo_data
from backend.alerts import detect_anomalies
from backend.config import HISTORY_DAYS, history_window
from backend.history import detector_status

CACHE_TTL_SECONDS = 60  # short on purpose: real spend data should feel current, not stale
DEFAULT_VIEW_DAYS = 30
MODES = ('live', 'demo')

log = logging.getLogger(__name__)


class InvalidParam(ValueError):
    pass


@lru_cache(maxsize=1)
def get_account_id():
    """Looked up on first live request, not at import, so the app imports offline.
    lru_cache does not cache exceptions, so a failed lookup is retried next time."""
    import boto3
    return boto3.client('sts', region_name='us-east-1').get_caller_identity()['Account']


def _utc_today():
    return datetime.now(timezone.utc).date()


def _normalize(items):
    """DynamoDB Decimals -> floats, oldest first."""
    rows = [
        {
            'date': item['date'],
            'total_cost': float(item['total_cost']),
            'services': {name: float(cost) for name, cost in item.get('services', {}).items()},
        }
        for item in items
    ]
    return sorted(rows, key=lambda r: r['date'])


def _load_live(today):
    """
    Cache-through over the shared HISTORY_DAYS window (the same window the
    daily pipeline runs detection over): check cache first, fall back to
    DynamoDB on a miss, then populate the cache for next time.
    """
    from backend.db import get_snapshots  # boto3 resource is created on first live use

    cache_key = f"costs:{get_account_id()}:{today.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached, 'cache'

    start, end = history_window(today)
    snapshots = _normalize(get_snapshots(get_account_id(), start, end))
    cache.set(cache_key, snapshots, ttl_seconds=CACHE_TTL_SECONDS)
    return snapshots, 'dynamodb'


def _load_demo(today):
    # SYNTHETIC: anchored so the latest demo day is yesterday, like real ingestion.
    return demo_data.generate_demo_snapshots(today - timedelta(days=1)), 'demo'


def _parse_args():
    mode = request.args.get('mode', 'live')
    if mode not in MODES:
        raise InvalidParam(f"mode must be one of: {', '.join(MODES)}")

    raw_days = request.args.get('days', str(DEFAULT_VIEW_DAYS))
    if not raw_days.isdigit() or not 1 <= int(raw_days) <= HISTORY_DAYS:
        raise InvalidParam(f"days must be an integer from 1 to {HISTORY_DAYS}")
    return mode, int(raw_days)


def _load(mode):
    """
    Returns (snapshots over the full HISTORY_DAYS window, meta). Detection
    and detector status always use the full window; the days param only
    narrows what is displayed, and can never exceed HISTORY_DAYS, so no
    view shows a day the detector did not see.
    """
    today = _utc_today()
    started = time.perf_counter()
    if mode == 'demo':
        snapshots, source = _load_demo(today)
    else:
        snapshots, source = _load_live(today)
    meta = {
        'mode': mode,
        'source': source,
        'elapsed_ms': round((time.perf_counter() - started) * 1000, 2),
        'history_days': HISTORY_DAYS,
        'today_utc': today.isoformat(),
    }
    return snapshots, meta


def _view_start(today_iso, days):
    return (date.fromisoformat(today_iso) - timedelta(days=days)).isoformat()


def _envelope(data, meta, mode):
    # "synthetic" is always present so a consumer never has to infer it.
    return jsonify({'data': data, 'meta': meta, 'synthetic': mode == 'demo'})


def create_app():
    app = Flask(__name__)

    @app.route('/')
    def dashboard():
        return render_template('dashboard.html', history_days=HISTORY_DAYS)

    @app.route('/api/health')
    def health():
        return jsonify({"status": "ok", "service": "Cost Monitor"})

    @app.route('/api/costs')
    def api_costs():
        mode, days = _parse_args()
        snapshots, meta = _load(mode)
        start = _view_start(meta['today_utc'], days)
        meta.update(days=days, view_start=start)
        return _envelope([s for s in snapshots if s['date'] >= start], meta, mode)

    @app.route('/api/alerts')
    def api_alerts():
        mode, days = _parse_args()
        snapshots, meta = _load(mode)
        start = _view_start(meta['today_utc'], days)
        meta.update(days=days, view_start=start)
        anomalies = [a for a in detect_anomalies(snapshots) if a['date'] >= start]
        return _envelope(anomalies, meta, mode)

    @app.route('/api/detector-status')
    def api_detector_status():
        mode, _ = _parse_args()
        snapshots, meta = _load(mode)
        status = detector_status(snapshots, date.fromisoformat(meta['today_utc']))
        return _envelope(status, meta, mode)

    @app.route('/api/cache-stats')
    def api_cache_stats():
        return jsonify(cache.get_stats())

    def _is_api():
        return request.path.startswith('/api/')

    @app.errorhandler(InvalidParam)
    def handle_bad_request(e):
        return jsonify({'error': str(e)}), 400

    @app.errorhandler(HTTPException)
    def handle_http(e):
        if not _is_api():
            return e
        return jsonify({'error': e.name}), e.code

    @app.errorhandler(BotoCoreError)
    @app.errorhandler(ClientError)
    def handle_aws(e):
        log.warning("AWS request failed: %s", e)
        return jsonify({'error': 'Live data is unavailable: the AWS request failed. '
                                 'Demo mode works without AWS.'}), 503

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        log.exception("Unhandled error on %s", request.path)
        if not _is_api():
            return 'Internal Server Error', 500
        return jsonify({'error': 'Internal server error'}), 500

    return app


app = create_app()


if __name__ == '__main__':
    debug = os.environ.get('COST_MONITOR_DEBUG') == '1'
    app.run(host='127.0.0.1', port=5001, debug=debug)
