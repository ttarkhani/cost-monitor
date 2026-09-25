import boto3
from datetime import datetime, timedelta
from backend.db import get_snapshots
from backend.alerts import detect_anomalies, _build_cost_series, _evaluate_series, MIN_WINDOW

sts = boto3.client('sts', region_name='us-east-1')
ACCOUNT_ID = sts.get_caller_identity()['Account']


def test_real_data_correctly_reports_insufficient_history():
    """
    Real stored DynamoDB data currently has only 3 days. The MAD method
    needs MIN_WINDOW + 2 days (currently 7) before it can produce a single
    verdict. Confirms the detector correctly recognizes that and reports
    nothing, rather than guessing on too little data.
    """
    print("=" * 60)
    print("TEST 1: Real stored data — expect correct 'insufficient history'")
    print("=" * 60)

    today = datetime.now().date()
    start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    end = today.strftime('%Y-%m-%d')
    snapshots = get_snapshots(ACCOUNT_ID, start, end)

    print(f"\nLoaded {len(snapshots)} real snapshots:")
    for s in snapshots:
        print(f"  {s['date']}: ${float(s['total_cost']):.2f}")

    dates, costs = _build_cost_series(snapshots, service_name=None)
    evaluated = _evaluate_series(dates, costs)
    anomalies = detect_anomalies(snapshots)

    print(f"\nDays evaluated: {len(evaluated)} (need {MIN_WINDOW + 1} prior deltas, "
          f"have only {len(snapshots) - 1} delta(s) total)")
    print(f"Anomalies returned: {len(anomalies)}")

    assert len(evaluated) == 0, "expected zero evaluated days with only 3 snapshots"
    assert len(anomalies) == 0

    print("\nPASS: correctly reports nothing — not enough history for an honest verdict yet.")
    print(f"Will start producing real verdicts once the account has {MIN_WINDOW + 2} real ingested days.")


def test_per_service_attribution_synthetic():
    """
    SYNTHETIC — 7 days, the minimum needed for exactly one verdict. RDS
    appears only on the final day with a real jump; EC2 and S3 stay flat.
    Confirms the anomaly is attributed to RDS specifically, and that EC2/S3
    are correctly left alone.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Synthetic per-service attribution (minimum 7-day window)")
    print("=" * 60)

    dates = [f"2099-01-{i+1:02d}" for i in range(7)]
    ec2 = [3.00, 3.05, 2.95, 3.00, 3.10, 2.95, 3.00]
    s3 = [2.00, 2.05, 1.95, 2.00, 2.10, 1.95, 2.00]
    rds = [0, 0, 0, 0, 0, 0, 8.00]

    snapshots = [
        {'date': dates[i], 'total_cost': ec2[i] + s3[i] + rds[i],
         'services': {'Amazon EC2': ec2[i], 'Amazon S3': s3[i],
                       **({'Amazon RDS': rds[i]} if rds[i] > 0 else {})}}
        for i in range(7)
    ]

    print("\nRDS appears for the first time on day 7 with a real jump to $8.00.")
    print("EC2 and S3 stay within normal noise the whole time.\n")

    anomalies = detect_anomalies(snapshots)

    for a in anomalies:
        label = a['service'] if a['level'] == 'service' else 'Total spend'
        print(f"  [{a['level'].upper()}:{label}] day {a['day_index']}: "
              f"${a['previous_cost']:.2f} -> ${a['current_cost']:.2f}  "
              f"z={a['modified_z']}  is_new={a.get('is_new')}")

    flagged_services = {a['service'] for a in anomalies if a['level'] == 'service'}
    assert flagged_services == {'Amazon RDS'}, f"expected only RDS flagged, got {flagged_services}"
    assert any(a['level'] == 'aggregate' for a in anomalies)

    print("\nPASS: RDS correctly flagged as new, EC2 and S3 correctly left alone,")
    print("aggregate also flagged (driven entirely by RDS).")


if __name__ == '__main__':
    test_real_data_correctly_reports_insufficient_history()
    test_per_service_attribution_synthetic()
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)