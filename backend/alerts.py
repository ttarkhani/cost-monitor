def detect_anomalies(snapshots, pct_threshold=0.4, min_abs_increase=1.0):
    """
    Flag day-over-day cost increases that look like real anomalies,
    not just tiny free-tier noise.

    snapshots: list of items from db.get_snapshots(), sorted oldest -> newest
    pct_threshold: minimum fractional increase to flag (0.4 = 40%)
    min_abs_increase: minimum dollar increase to flag, so a jump from
                       $0.01 to $0.02 (a 100% increase) doesn't trigger
                       a false alarm

    Both thresholds must be crossed for a day to count as anomalous.
    """
    anomalies = []

    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        curr = snapshots[i]

        prev_cost = float(prev['total_cost'])
        curr_cost = float(curr['total_cost'])
        abs_increase = curr_cost - prev_cost

        if prev_cost > 0:
            pct_increase = abs_increase / prev_cost
        else:
            pct_increase = float('inf') if curr_cost > 0 else 0.0

        if abs_increase >= min_abs_increase and pct_increase >= pct_threshold:
            anomalies.append({
                'date': curr['date'],
                'previous_date': prev['date'],
                'previous_cost': round(prev_cost, 4),
                'current_cost': round(curr_cost, 4),
                'increase_pct': round(pct_increase * 100, 1),
                'increase_abs': round(abs_increase, 4),
            })

    return anomalies