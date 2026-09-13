from flask import Flask, jsonify
import boto3
from datetime import datetime, timedelta
from backend.db import get_snapshots

app = Flask(__name__)

# Fetched once at startup, not per-request — calling AWS on every
# page load would be an artificial hit to your dashboard load-time metric.
_sts = boto3.client('sts', region_name='us-east-1')
ACCOUNT_ID = _sts.get_caller_identity()['Account']


@app.route('/')
def health():
    return jsonify({"status": "ok", "service": "Cost Monitor"})


@app.route('/api/costs')
def api_costs():
    today = datetime.now().date()
    start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    end = today.strftime('%Y-%m-%d')

    snapshots = get_snapshots(ACCOUNT_ID, start, end)

    result = [
        {
            'date': item['date'],
            'total_cost': float(item['total_cost']),
            'services': {name: float(cost) for name, cost in item['services'].items()}
        }
        for item in snapshots
    ]

    return jsonify(result)


if __name__ == '__main__':
    # Port 5001, not 5000 — macOS reserves 5000 for AirPlay Receiver,
    # which throws a confusing 403 instead of a clean "port in use" error.
    app.run(debug=True, port=5001)