import statistics

Z_THRESHOLD = 3.5
MIN_WINDOW = 5
MIN_ABS_INCREASE = 1.0

# Deltas below this are floating-point noise around an effectively-zero MAD,
# not a real nonzero spread. Floating-point subtraction of two "equal"
# decimal values (e.g. 6.30 - 5.00) can leave a residual as small as 1e-15
# or 1e-16 instead of an exact 0.0. Comparing MAD to exactly 0.0 lets that
# residual slip through and blows the z-score up to a meaningless,
# astronomically large number instead of correctly triggering the
# zero-variance fallback below. 1e-6 is comfortably above realistic
# floating-point noise and comfortably below any real cent-level billing
# variation.
MAD_EPSILON = 1e-6


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
        # Same floating-point issue applies here: today's deviation and the
        # window's largest prior deviation can be "conceptually" equal (the
        # series has genuinely seen this exact delta before) but land as
        # bit-different floats from unrelated subtraction chains, making a
        # bare `>` comparison occasionally trip on noise. Requiring a clear
        # margin above the noise floor avoids flagging a value the window
        # has already effectively seen.
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
    all_deltas = [costs[i] - costs[i - 1] for i in range(1, len(costs))]
    results = []

    for k in range(min_window, len(all_deltas)):
        prior_deltas = all_deltas[:k]
        today_delta = all_deltas[k]
        verdict = _modified_z_verdict(prior_deltas, today_delta, z_threshold=z_threshold,
                                       min_window=min_window, min_abs_increase=min_abs_increase)
        results.append({
            'day_index': k + 2,
            'date': dates[k + 1],
            'previous_date': dates[k],
            'previous_cost': round(costs[k], 4),
            'current_cost': round(costs[k + 1], 4),
            'delta': round(today_delta, 4),
            **verdict,
        })
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