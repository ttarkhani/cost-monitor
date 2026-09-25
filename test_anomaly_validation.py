from datetime import date, timedelta
from backend.alerts import _build_cost_series, _evaluate_series, MIN_WINDOW


def _sequential_dates(start_str, n):
    start = date.fromisoformat(start_str)
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


SCENARIOS = {
    'stable_baseline': {
        'dates': _sequential_dates('2099-01-01', 14),
        'costs': [5.00, 5.10, 4.95, 5.05, 5.20, 4.90, 5.00, 5.15, 4.95, 5.10, 5.00, 4.95, 5.05, 5.10],
        'true_anomaly_days': set(),
        'description': 'Normal day-to-day noise around a flat baseline. Every evaluated day should be a true negative.',
    },
    'single_spike': {
        'dates': _sequential_dates('2099-01-01', 14),
        'costs': [5.00, 5.10, 4.95, 5.05, 5.20, 4.90, 5.00, 5.15, 4.95, 25.00, 5.05, 5.00, 4.95, 5.10],
        'true_anomaly_days': {10},
        'description': 'One real 5x spike, then back down. The drop back down should NOT be flagged -- this system only ever flags increases.',
    },
    'organic_growth': {
        'dates': _sequential_dates('2099-01-01', 14),
        'costs': [5.00, 6.30, 7.40, 8.70, 9.90, 11.20, 12.50, 13.60, 14.90, 16.20, 17.30, 18.60, 19.90, 21.10],
        'true_anomaly_days': set(),
        'description': 'Steady ~$1.20-1.30/day growth -- organic usage increase, not a spike. Should NOT be flagged, even though each day individually clears the $1.00 floor.',
    },
    'near_zero_then_jump': {
        'dates': _sequential_dates('2099-01-01', 14),
        'costs': [0.00, 0.01, 0.00, 0.02, 0.01, 0.00, 0.01, 3.50, 0.02, 0.01, 0.00, 0.01, 0.02, 0.00],
        'true_anomaly_days': {8},
        'description': 'Free-tier-style near-zero noise, one real jump. Tests the zero-variance-window edge case.',
    },
    'gap_in_history': {
        # day 9 is deliberately missing -- costs[8] is really "day 10", 2
        # calendar days after costs[7] ("day 8"). Everything after the gap
        # continues normally, including a real anomaly on the final day.
        'dates': _sequential_dates('2099-02-01', 8) + _sequential_dates('2099-02-10', 5),
        'costs': [5.00, 5.10, 4.95, 5.05, 5.20, 4.90, 5.00, 5.15, 4.95, 5.05, 4.90, 5.00, 25.00],
        'true_anomaly_days': {13},
        'expect_gap_at_day': 9,
        'description': 'A real missed-ingestion gap (day 9 absent), then a real anomaly 4 days later. Confirms the gap is excluded from both evaluation and the baseline, and does not mask or distort the later real anomaly.',
    },
}

SANE_Z_BOUND = 1000


def run_all_scenarios():
    total_tp = total_fp = total_tn = total_fn = 0
    insane_z_values = []
    gap_check_failures = []

    for name, scenario in SCENARIOS.items():
        dates = scenario['dates']
        costs = scenario['costs']
        true_days = scenario['true_anomaly_days']

        _, series_costs = _build_cost_series(
            [{'date': d, 'total_cost': c, 'services': {}} for d, c in zip(dates, costs)],
            service_name=None
        )
        results = _evaluate_series(dates, series_costs)

        print(f"\n{'=' * 70}")
        print(f"SCENARIO: {name}")
        print(f"{scenario['description']}")
        print(f"{'=' * 70}")
        print(f"{len(costs)} days total, {len(results)} transition(s) surfaced\n")

        gap_days_seen = set()

        for r in results:
            predicted = r['flagged']
            actual = r['day_index'] in true_days
            is_gap = r['status'] == 'gap_skipped'

            if is_gap:
                gap_days_seen.add(r['day_index'])

            if r['modified_z'] is not None and abs(r['modified_z']) > SANE_Z_BOUND:
                insane_z_values.append((name, r['day_index'], r['modified_z']))

            if is_gap:
                verdict = f"GAP ({r['gap_days']}d)"
            elif predicted and actual:
                verdict = "TRUE POSITIVE"; total_tp += 1
            elif predicted and not actual:
                verdict = "FALSE POSITIVE"; total_fp += 1
            elif not predicted and actual:
                verdict = "FALSE NEGATIVE"; total_fn += 1
            else:
                verdict = "true negative"; total_tn += 1

            z_display = f"z={r['modified_z']}" if r['modified_z'] is not None else "z=n/a"
            print(f"  day {r['day_index']:2d}  delta={r['delta']:+8.2f}  {z_display:12s} "
                  f"-> {'FLAGGED' if predicted else ('GAP' if is_gap else 'normal'):8s}  [{verdict}]")

        if 'expect_gap_at_day' in scenario:
            expected_day = scenario['expect_gap_at_day']
            if expected_day not in gap_days_seen:
                gap_check_failures.append(
                    f"{name}: expected a gap_skipped entry at day {expected_day}, found gaps at {gap_days_seen}"
                )

    print(f"\n{'=' * 70}")
    print("AGGREGATE CONFUSION MATRIX (gap_skipped entries excluded from all counts)")
    print(f"{'=' * 70}")
    print(f"  True Positives:  {total_tp}")
    print(f"  False Positives: {total_fp}")
    print(f"  True Negatives:  {total_tn}")
    print(f"  False Negatives: {total_fn}")

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else float('nan')
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else float('nan')
    fpr = total_fp / (total_fp + total_tn) if (total_fp + total_tn) else float('nan')

    print(f"\n  Precision: {precision:.3f}")
    print(f"  Recall:    {recall:.3f}")
    print(f"  False positive rate: {fpr:.3f}")
    print(f"  Total evaluated judgments: {total_tp + total_fp + total_tn + total_fn}")

    if insane_z_values:
        print(f"\n  WARNING -- {len(insane_z_values)} z-score(s) exceeded sane bound of {SANE_Z_BOUND}:")
        for name, day, z in insane_z_values:
            print(f"    {name} day {day}: z={z}")

    if gap_check_failures:
        print(f"\n  WARNING -- gap detection did not behave as expected:")
        for msg in gap_check_failures:
            print(f"    {msg}")

    return {'tp': total_tp, 'fp': total_fp, 'tn': total_tn, 'fn': total_fn,
            'precision': precision, 'recall': recall, 'fpr': fpr,
            'insane_z_values': insane_z_values, 'gap_check_failures': gap_check_failures}


if __name__ == '__main__':
    stats = run_all_scenarios()
    assert not stats['insane_z_values'], (
        f"found {len(stats['insane_z_values'])} numerically insane z-score(s)"
    )
    assert not stats['gap_check_failures'], "gap detection did not behave as expected -- see warnings above"
    assert stats['fn'] == 0, f"missed a known injected anomaly -- {stats['fn']} false negative(s)"
    assert stats['fp'] == 0, f"flagged something that shouldn't be flagged -- {stats['fp']} false positive(s)"
    print(f"\n{'=' * 70}")
    print("ALL SYNTHETIC SCENARIOS PASSED -- 0 false positives, 0 false negatives,")
    print("all z-scores sane, gap correctly detected and excluded from the baseline")
    print(f"{'=' * 70}")