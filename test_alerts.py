import boto3
from datetime import datetime, timedelta
from backend.db import get_snapshots
from backend.alerts import detect_anomalies

sts = boto3.client('sts', region_name='us-east-1')
ACCOUNT_ID = sts.get_caller_identity()['Account']


def test_against_real_stored_data():
    """
    Runs the per-service-aware detector against the real snapshots already
    stored in DynamoDB. Confirms it surfaces something the old aggregate-only
    version couldn't: that RDS specifically — not EC2 or S3 — caused the
    total to spike on 2026-09-13.
    """
    print("=" * 60)
    print("TEST 1: Real stored DynamoDB data")
    print("=" * 60)

    today = datetime.now().date()
    start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
    end = today.strftime('%Y-%m-%d')
    snapshots = get_snapshots(ACCOUNT_ID, start, end)

    print(f"\nLoaded {len(snapshots)} snapshots:")
    for s in snapshots:
        print(f"  {s['date']}: ${float(s['total_cost']):.2f}  {dict(s['services'])}")

    anomalies = detect_anomalies(snapshots, pct_threshold=0.4, min_abs_increase=1.0)

    print(f"\nDetected {len(anomalies)} anomalies:\n")
    for a in anomalies:
        if a['level'] == 'aggregate':
            print(f"  [AGGREGATE] {a['date']}: ${a['previous_cost']:.2f} -> ${a['current_cost']:.2f} "
                  f"(+{a['increase_pct']}%)")
        else:
            tag = "NEW SERVICE" if a['is_new'] else "SPIKE"
            pct = f"+{a['increase_pct']}%" if a['increase_pct'] is not None else "n/a (new)"
            print(f"  [SERVICE:{a['service']}] {tag} on {a['date']}: "
                  f"${a['previous_cost']:.2f} -> ${a['current_cost']:.2f} ({pct})")

    assert len(anomalies) == 2, f"expected 2 anomalies, got {len(anomalies)}"
    assert any(a['level'] == 'aggregate' for a in anomalies)
    assert any(a['level'] == 'service' and a['service'] == 'Amazon RDS' and a['is_new'] for a in anomalies)

    print("\nPASS: aggregate spike still detected, AND now correctly attributed to RDS specifically.")


def test_cancellation_masking_synthetic():
    """
    SYNTHETIC test — not real billing data, clearly constructed to prove a
    specific point: a service can spike while the account total looks
    unremarkable, if something else drops at the same time. Per-service
    detection catches this; aggregate-only cannot, by construction.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Synthetic cancellation-masking scenario")
    print("=" * 60)

    synthetic_snapshots = [
        {'date': '2099-01-01', 'total_cost': 20.00,
         'services': {'Amazon EC2': 10.00, 'Amazon S3': 10.00}},
        {'date': '2099-01-02', 'total_cost': 21.00,  # only +5% overall
         'services': {'Amazon EC2': 15.00, 'Amazon S3': 6.00}},  # EC2 +50%, S3 -40%
    ]

    print("\nScenario: total spend moves +5% (unremarkable), but EC2 alone jumped +50%")
    print("while S3 dropped at the same time, masking it in the total.\n")

    old_style = detect_anomalies(synthetic_snapshots, pct_threshold=0.4, min_abs_increase=1.0, per_service=False)
    new_style = detect_anomalies(synthetic_snapshots, pct_threshold=0.4, min_abs_increase=1.0, per_service=True)

    print(f"OLD (aggregate-only) detected: {len(old_style)} anomalies")
    print(f"NEW (per-service)     detected: {len(new_style)} anomalies")

    assert len(old_style) == 0, "aggregate-only should NOT catch this — that's the whole point"
    assert len(new_style) == 1
    assert new_style[0]['level'] == 'service' and new_style[0]['service'] == 'Amazon EC2'

    print("\nPASS: old logic misses the EC2 spike entirely. New logic catches it:")
    print(f"  -> [SERVICE:{new_style[0]['service']}] +{new_style[0]['increase_pct']}%, "
          f"${new_style[0]['previous_cost']:.2f} -> ${new_style[0]['current_cost']:.2f}")


if __name__ == '__main__':
    test_against_real_stored_data()
    test_cancellation_masking_synthetic()
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)