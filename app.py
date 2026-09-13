from flask import Flask, jsonify, render_template
import boto3
from datetime import datetime, timedelta
from backend.db import get_snapshots
from backend.alerts import detect_anomalies

app = Flask(__name__)

_sts = boto3.client('sts', region_name='us-east-1')
ACCOUNT_ID = _sts.get_caller_identity()['Account']


def _fetch_last_30_days():
    today = datetime.now().date()
    start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    end = today.strftime('%Y-%m-%d')
    return get_snapshots(ACCOUNT_ID, start, end)


@app.route('/')
def dashboard():
    return render_template('dashboard.html')


@app.route('/api/health')
def health():
    return jsonify({"status": "ok", "service": "Cost Monitor"})


@app.route('/api/costs')
def api_costs():
    snapshots = _fetch_last_30_days()
    result = [
        {
            'date': item['date'],
            'total_cost': float(item['total_cost']),
            'services': {name: float(cost) for name, cost in item['services'].items()}
        }
        for item in snapshots
    ]
    return jsonify(result)


@app.route('/api/alerts')
def api_alerts():
    snapshots = _fetch_last_30_days()
    anomalies = detect_anomalies(snapshots, pct_threshold=0.4, min_abs_increase=1.0)
    return jsonify(anomalies)


if __name__ == '__main__':
    app.run(debug=True, port=5001)