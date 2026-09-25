def _compute_change(previous_cost, current_cost, pct_threshold, min_abs_increase):
    """
    Compare one cost value between two days and decide whether it's anomalous.
    Returns None if not anomalous, or a dict describing the change if it is.
    Shared by both the aggregate check and every per-service check, so both
    use identical math and identical thresholds.
    """
    increase_abs = current_cost - previous_cost

    if previous_cost == 0:
        # Division by a previous cost of zero is undefined — treat this as
        # its own case ("new service") rather than an infinite percentage.
        if current_cost >= min_abs_increase:
            return {
                'previous_cost': round(previous_cost, 4),
                'current_cost': round(current_cost, 4),
                'increase_abs': round(increase_abs, 4),
                'increase_pct': None,
                'is_new': True,
            }
        return None

    increase_pct = increase_abs / previous_cost
    if increase_abs >= min_abs_increase and increase_pct >= pct_threshold:
        return {
            'previous_cost': round(previous_cost, 4),
            'current_cost': round(current_cost, 4),
            'increase_abs': round(increase_abs, 4),
            'increase_pct': round(increase_pct * 100, 1),
            'is_new': False,
        }
    return None


def detect_anomalies(snapshots, pct_threshold=0.4, min_abs_increase=1.0, per_service=True):
    """
    Compare each pair of consecutive days and flag both:
      - aggregate-level anomalies (total_cost jumped)
      - per-service anomalies (one specific service jumped, or is new)

    per_service=False reproduces the original aggregate-only behavior —
    kept as an option so the two approaches can be directly compared
    against identical data (see test_alerts.py).

    Decreases are never flagged: increase_abs would be <= 0, which always
    fails the min_abs_increase check inside _compute_change.
    """
    anomalies = []

    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        curr = snapshots[i]

        prev_total = float(prev['total_cost'])
        curr_total = float(curr['total_cost'])
        agg_change = _compute_change(prev_total, curr_total, pct_threshold, min_abs_increase)
        if agg_change:
            anomalies.append({
                'level': 'aggregate',
                'service': None,
                'date': curr['date'],
                'previous_date': prev['date'],
                **agg_change,
            })

        if not per_service:
            continue

        prev_services = {name: float(cost) for name, cost in prev.get('services', {}).items()}
        curr_services = {name: float(cost) for name, cost in curr.get('services', {}).items()}

        for service_name in sorted(set(prev_services) | set(curr_services)):
            prev_cost = prev_services.get(service_name, 0.0)
            curr_cost = curr_services.get(service_name, 0.0)
            svc_change = _compute_change(prev_cost, curr_cost, pct_threshold, min_abs_increase)
            if svc_change:
                anomalies.append({
                    'level': 'service',
                    'service': service_name,
                    'date': curr['date'],
                    'previous_date': prev['date'],
                    **svc_change,
                })

    return anomalies