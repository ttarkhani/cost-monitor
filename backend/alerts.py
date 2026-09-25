import statistics
from datetime import date as _date

Z_THRESHOLD = 3.5
MIN_WINDOW = 5
MIN_ABS_INCREASE = 1.0
MAD_EPSILON = 1e-6


def _parse_date(date_str):
    return _date.fromisoformat(date_str)


def _modified_z_verdict(historical_deltas, today_delta,
                         z_threshold=Z_THRESHOLD, min_window=MIN_WINDOW,
                         min_abs_increase=MIN_ABS_INCREASE):
    n = len(historical_deltas)
    if n < min_window:
        return {'flagged': False, 'status': 'insufficient_data',
                'window_size': n, 'modified_z': None}

    if today_delta <= 0:
        return {'flagged': False, 'status': 'normal',
                'window_size': n, 'modified_z': None}

    median = statistics.median(historical_deltas)
    abs_devs = [abs(d - median) for d in historical_deltas]
    mad = statistics.median(abs_devs)

    if mad < MAD_EPSILON:
        max_dev = max(abs_devs) if abs_devs else 0.0
        today_dev = abs(today_delta - median)
        flagged = today_delta >= min_abs_increase and today_dev > max_dev + MAD_EPSILON
        return {'flagged': flagged, 'status': 'anomaly' if flagged else 'normal',
                'window_size': n, 'modified_z': None, 'note': 'zero_variance_window'}

    modified_z = 0.6745 * (today_delta - median) / mad
    flagged = modified_z >= z_threshold and today_delta >= min_abs_increase
    return {'flagged': flagged, 'status': 'anomaly' if flagged else 'normal',
            'window_size': n, 'modified_z': round(modified_z, 2)}


def _build_cost_series(snapshots, service_name=None):
    dates = [s['date'] for s in snapshots]
    if service_name is None:
        costs = [float(s['total_cost']) for s in snapshots]
    else:
        costs = [float(s.get('services', {}).get(service_name, 0.0)) for s in snapshots]
    return dates, costs


def _evaluate_series(dates, costs, z_threshold=Z_THRESHOLD, min_window=MIN_WINDOW,
                      min_abs_increase=MIN_ABS_INCREASE):
    """
    Walks the series day by day. Only a transition between two CONSECUTIVE
    calendar dates (exactly 1 day apart) ever gets evaluated or contributes
    to the historical baseline. A transition spanning a gap (a missed
    ingestion day) is reported for visibility with status 'gap_skipped',
    but excluded from both -- a multi-day jump isn't the same kind of
    quantity as a 1-day jump, and letting it into the baseline would
    distort every future comparison.

    Deliberate design choice: a gap does NOT reset the accumulated
    baseline. Valid deltas from before the gap remain part of the history
    used to judge deltas after it -- only the one transition that actually
    spans the gap is excluded.
    """
    results = []
    consecutive_deltas = []

    for i in range(1, len(costs)):
        prev_date = _parse_date(dates[i - 1])
        curr_date = _parse_date(dates[i])
        gap_days = (curr_date - prev_date).days
        delta = costs[i] - costs[i - 1]

        base_fields = {
            'day_index': i + 1,
            'date': dates[i],
            'previous_date': dates[i - 1],
            'previous_cost': round(costs[i - 1], 4),
            'current_cost': round(costs[i], 4),
            'delta': round(delta, 4),
        }

        if gap_days != 1:
            results.append({
                **base_fields,
                'flagged': False,
                'status': 'gap_skipped',
                'gap_days': gap_days,
                'window_size': len(consecutive_deltas),
                'modified_z': None,
            })
            continue

        if len(consecutive_deltas) >= min_window:
            verdict = _modified_z_verdict(consecutive_deltas, delta, z_threshold=z_threshold,
                                           min_window=min_window, min_abs_increase=min_abs_increase)
            results.append({**base_fields, **verdict})

        consecutive_deltas.append(delta)

    return results


def detect_anomalies(snapshots, z_threshold=Z_THRESHOLD, min_window=MIN_WINDOW,
                      min_abs_increase=MIN_ABS_INCREASE, per_service=True):
    anomalies = []

    dates, agg_costs = _build_cost_series(snapshots, service_name=None)
    for v in _evaluate_series(dates, agg_costs, z_threshold=z_threshold,
                               min_window=min_window, min_abs_increase=min_abs_increase):
        if v['flagged']:
            anomalies.append({'level': 'aggregate', 'service': None, **v})

    if per_service:
        service_names = sorted({name for s in snapshots for name in s.get('services', {})})
        for name in service_names:
            svc_dates, svc_costs = _build_cost_series(snapshots, service_name=name)
            for v in _evaluate_series(svc_dates, svc_costs, z_threshold=z_threshold,
                                       min_window=min_window, min_abs_increase=min_abs_increase):
                if v['flagged']:
                    v['is_new'] = v['previous_cost'] == 0.0
                    anomalies.append({'level': 'service', 'service': name, **v})

    return anomalies