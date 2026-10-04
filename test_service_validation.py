"""
SYNTHETIC per-service validation: the confusion-matrix approach of
test_anomaly_validation.py, applied to individual service series.

Every scenario is hand-constructed, multi-service, and labeled with the
(service, day) pairs that are real anomalies. Each service series is run
through the same frozen functions detect_anomalies uses
(_build_cost_series + _evaluate_series). The script REPORTS precision,
recall and false-positive rate as measured; it does not require them to
be perfect. It only fails on broken invariants (numerically insane
z-scores, gap transitions being judged, or detect_anomalies disagreeing
with the per-series walk).

Run: ./venv/bin/python test_service_validation.py
"""
from datetime import date, timedelta

from backend.alerts import _build_cost_series, _evaluate_series, detect_anomalies

SANE_Z_BOUND = 1000


def _dates(start, n, skip=()):
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n) if i not in skip]


def _snapshots(dates, series):
    """series: {service: [cost per date]}; a 0 cost means the service is absent that day."""
    out = []
    for i, d in enumerate(dates):
        services = {name: costs[i] for name, costs in series.items() if costs[i] > 0}
        out.append({'date': d, 'total_cost': round(sum(services.values()), 2), 'services': services})
    return out


# Fixed irregular noise patterns (dollars), so scenarios are deterministic.
N1 = [0.00, 0.12, -0.07, 0.04, 0.18, -0.11, 0.02, 0.09, -0.03, 0.14, 0.00, -0.08, 0.06, 0.11]
N2 = [0.03, -0.05, 0.08, -0.02, 0.06, 0.01, -0.09, 0.04, 0.07, -0.04, 0.02, 0.05, -0.06, 0.00]
N3 = [-0.02, 0.01, 0.03, -0.01, 0.00, 0.02, -0.03, 0.01, 0.02, 0.00, -0.02, 0.03, 0.01, -0.01]


def _flat(base, noise):
    return [round(base + n, 2) for n in noise]


def _with(values, day_index, value):
    """day_index is 1-based, matching _evaluate_series' day_index."""
    out = list(values)
    out[day_index - 1] = value
    return out


SCENARIOS = {
    'stable_multi_service': {
        'description': 'Three services with ordinary noise. No anomalies.',
        'dates': _dates('2099-01-01', 14),
        'series': {'EC2': _flat(4.2, N1), 'RDS': _flat(2.6, N2), 'S3': _flat(1.1, N3)},
        'truth': set(),
    },
    'single_service_spike': {
        'description': 'EC2 triples for one day; RDS and S3 stay normal.',
        'dates': _dates('2099-01-01', 14),
        'series': {'EC2': _with(_flat(4.2, N1), 10, 12.5), 'RDS': _flat(2.6, N2), 'S3': _flat(1.1, N3)},
        'truth': {('EC2', 10)},
    },
    'masked_by_drop_elsewhere': {
        'description': 'EC2 jumps +$6 the same day RDS drops ~$2.5: only EC2 is a real anomaly.',
        'dates': _dates('2099-01-01', 14),
        'series': {'EC2': _with(_flat(4.2, N1), 9, 10.2), 'RDS': _with(_flat(2.6, N2), 9, 0.1),
                   'S3': _flat(1.1, N3)},
        'truth': {('EC2', 9)},
    },
    'new_service_appears': {
        'description': 'CloudWatch appears on day 11 at ~$3 and stays.',
        'dates': _dates('2099-01-01', 14),
        'series': {'EC2': _flat(4.2, N1), 'S3': _flat(1.1, N3),
                   'CloudWatch': [0.0] * 10 + _flat(3.1, N2[:4])},
        'truth': {('CloudWatch', 11)},
    },
    'organic_growth_one_service': {
        'description': 'RDS grows ~$1.20/day steadily (organic, not a spike); EC2 normal.',
        'dates': _dates('2099-01-01', 14),
        'series': {'EC2': _flat(4.2, N1),
                   'RDS': [round(2.0 + 1.2 * i + N3[i], 2) for i in range(14)]},
        'truth': set(),
    },
    'small_service_noise_below_floor': {
        'description': 'A cents-level service doubling and halving: big relative moves, all under $1.',
        'dates': _dates('2099-01-01', 14),
        'series': {'EC2': _flat(4.2, N1),
                   'Lambda': [0.05, 0.11, 0.04, 0.09, 0.22, 0.06, 0.10, 0.45, 0.07, 0.12, 0.05, 0.30, 0.08, 0.10]},
        'truth': set(),
    },
    'gap_then_service_spike': {
        'description': 'Day 9 missing for every service, then S3 spikes +$5 on the last day.',
        'dates': _dates('2099-02-01', 14, skip={8}),
        'series': {'EC2': _flat(4.2, N1[:13]), 'S3': _with(_flat(1.1, N3[:13]), 13, 6.1)},
        'truth': {('S3', 13)},
    },
    'two_services_spike_same_day': {
        'description': 'EC2 and RDS both spike on day 12.',
        'dates': _dates('2099-01-01', 14),
        'series': {'EC2': _with(_flat(4.2, N1), 12, 9.0), 'RDS': _with(_flat(2.6, N2), 12, 6.0),
                   'S3': _flat(1.1, N3)},
        'truth': {('EC2', 12), ('RDS', 12)},
    },
}


def run():
    tp = fp = tn = fn = 0
    problems = []
    for name, sc in SCENARIOS.items():
        snaps = _snapshots(sc['dates'], sc['series'])
        print(f"\n{'=' * 70}\nSCENARIO: {name}\n{sc['description']}\n{'=' * 70}")
        walked_flags = set()
        for service in sorted(sc['series']):
            dates, costs = _build_cost_series(snaps, service_name=service)
            for r in _evaluate_series(dates, costs):
                key = (service, r['day_index'])
                if r['status'] == 'gap_skipped':
                    if r['flagged']:
                        problems.append(f'{name}: gap transition flagged for {service}')
                    continue
                if r['modified_z'] is not None and abs(r['modified_z']) > SANE_Z_BOUND:
                    problems.append(f"{name}: insane z {r['modified_z']} for {key}")
                actual = key in sc['truth']
                if r['flagged']:
                    walked_flags.add((service, r['date']))
                if r['flagged'] and actual:
                    tp += 1; verdict = 'TRUE POSITIVE'
                elif r['flagged']:
                    fp += 1; verdict = 'FALSE POSITIVE'
                elif actual:
                    fn += 1; verdict = 'FALSE NEGATIVE'
                else:
                    tn += 1; verdict = None
                if verdict:
                    print(f"  {service:11s} day {r['day_index']:2d}  delta={r['delta']:+7.2f}  "
                          f"z={r['modified_z']}  [{verdict}]")
        api_flags = {(a['service'], a['date']) for a in detect_anomalies(snaps) if a['level'] == 'service'}
        if api_flags != walked_flags:
            problems.append(f'{name}: detect_anomalies disagrees with per-series walk')

    precision = tp / (tp + fp) if tp + fp else float('nan')
    recall = tp / (tp + fn) if tp + fn else float('nan')
    fpr = fp / (fp + tn) if fp + tn else float('nan')
    print(f"\n{'=' * 70}\nPER-SERVICE CONFUSION MATRIX (SYNTHETIC; gap transitions excluded)\n{'=' * 70}")
    print(f"  TP {tp}  FP {fp}  TN {tn}  FN {fn}  (judgments: {tp + fp + tn + fn})")
    print(f"  Precision {precision:.3f}  Recall {recall:.3f}  False positive rate {fpr:.3f}")
    return problems


if __name__ == '__main__':
    problems = run()
    for p in problems:
        print(f"  INVARIANT BROKEN: {p}")
    assert not problems, 'see invariant failures above'
    print("\nInvariants hold. The metrics above are reported as measured, not asserted.")
