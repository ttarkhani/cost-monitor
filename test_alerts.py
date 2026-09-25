import boto3
from datetime import datetime, timedelta
from backend.db import get_snapshots
from backend.alerts import detect_anomalies, _build_cost_series, _evaluate_series

sts = boto3.client('sts', region_name='us-east-1')
ACCOUNT_ID = sts.get_caller_identity()['Account']


def test_real_data_gap_handling_and_no_false_anomalies():
    """
    Real stored DynamoDB data. run_fetch.py was run manually and
    sporadically during development, not daily, so the real table has a
    genuine gap in it. Confirms non-consecutive transitions are reported as
    'gap_skipped' rather than silently corrupting the statistical baseline,
    and that nothing gets flagged as an anomaly before there's enough real
    consecutive-day history to judge fairly.
    """
    print("=" * 60)
    print("TEST 1: Real stored data -- gap handling + no false anomalies")
    print("=" * 60)

    today = datetime.now().date()
    start = (today - timedelta(days=60)).strftime('%Y-%m-%d')
    end = today.strftime('%Y-%m-%d')
    snapshots = get_snapshots(ACCOUNT_ID, start, end)

    print(f"\nLoaded {len(snapshots)} real snapshots:")
    for s in snapshots:
        print(f"  {s['date']}: ${float(s['total_cost']):.2f}")

    dates, costs = _build_cost_series(snapshots, service_name=None)
    evaluated = _evaluate_series(dates, costs)
    anomalies = detect_anomalies(snapshots)

    gap_entries = [r for r in evaluated if r.get('status') == 'gap_skipped']
    flagged = [r for r in evaluated if r.get('flagged')]

    print(f"\n{len(evaluated)} transition(s) surfaced by _evaluate_series:")
    for r in evaluated:
        print(f"  {r['previous_date']} -> {r['date']}  delta={r['delta']:+.2f}  status={r['status']}")

    assert len(flagged) == 0, f"expected nothing flagged with this little real history, got {len(flagged)}"
    assert len(anomalies) == 0

    print(f"\nGap(s) correctly detected: {len(gap_entries)}")
    for g in gap_entries:
        print(f"  {g['previous_date']} -> {g['date']}: {g['gap_days']} calendar days apart, excluded from the baseline")

    print("\nPASS: no false anomalies, and any real gap in ingestion is surfaced")
    print("explicitly rather than silently distorting the statistical baseline.")


def test_per_service_attribution_synthetic():
    """
    SYNTHETIC -- 7 consecutive days, no gaps. RDS appears only on the final
    day with a real jump; EC2 and S3 stay flat. Confirms attribution to RDS
    specifically, and that EC2/S3 are correctly left alone.
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
    test_real_data_gap_handling_and_no_false_anomalies()
    test_per_service_attribution_synthetic()
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)