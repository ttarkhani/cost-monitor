from flask import Flask, jsonify, render_template
import boto3
import time
from datetime import datetime, timedelta
from backend.db import get_snapshots
from backend.alerts import detect_anomalies
from backend import cache

app = Flask(__name__)

_sts = boto3.client('sts', region_name='us-east-1')
ACCOUNT_ID = _sts.get_caller_identity()['Account']

CACHE_TTL_SECONDS = 60  # short on purpose: real spend data should feel current, not stale


def _fetch_last_30_days():
    """
    Cache-through: check cache first, fall back to DynamoDB on a miss,
    then populate the cache for next time. Also reports whether this
    particular call was a hit or miss, and how long it took either way.
    """
    cache_key = f"costs:{ACCOUNT_ID}"
    start_time = time.perf_counter()

    cached = cache.get(cache_key)
    if cached is not None:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return cached, {"source": "cache", "elapsed_ms": elapsed_ms}

    today = datetime.now().date()
    start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    end = today.strftime('%Y-%m-%d')
    snapshots = get_snapshots(ACCOUNT_ID, start, end)

    cache.set(cache_key, snapshots, ttl_seconds=CACHE_TTL_SECONDS)
    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return snapshots, {"source": "dynamodb", "elapsed_ms": elapsed_ms}


@app.route('/')
def dashboard():
    return render_template('dashboard.html')


@app.route('/api/health')
def health():
    return jsonify({"status": "ok", "service": "Cost Monitor"})


@app.route('/api/costs')
def api_costs():
    snapshots, meta = _fetch_last_30_days()
    result = [
        {
            'date': item['date'],
            'total_cost': float(item['total_cost']),
            'services': {name: float(cost) for name, cost in item['services'].items()}
        }
        for item in snapshots
    ]
    return jsonify({"data": result, "meta": meta})


@app.route('/api/alerts')
def api_alerts():
    snapshots, _ = _fetch_last_30_days()
    anomalies = detect_anomalies(snapshots, pct_threshold=0.4, min_abs_increase=1.0)
    return jsonify(anomalies)


@app.route('/api/cache-stats')
def api_cache_stats():
    return jsonify(cache.get_stats())


if __name__ == '__main__':
    app.run(debug=True, port=5001)