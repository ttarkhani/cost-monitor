"""
SYNTHETIC demo dataset. Nothing in this module is real AWS billing data.

Generates a deterministic, made-up cost history so the dashboard can be
shown without AWS access and with something for the detector to find
(the real monitored account is free tier and has never had an anomaly).
Every payload built from this data must be labeled synthetic.

Stdlib only, so it is safe to ship in the Lambda package even though the
Lambda never uses it.
"""
import random
from datetime import timedelta

SYNTHETIC = True

DAYS = 45                 # calendar days covered, including the gap
SEED = 20260923           # fixed: same numbers on every run

# Baseline daily dollars per service. Noise is +/-4% multiplicative,
# which at these sizes keeps normal day-to-day moves well under $1.
BASE_COSTS = {
    'Amazon EC2': 4.20,
    'Amazon RDS': 2.60,
    'Amazon S3': 1.10,
}
NOISE_PCT = 0.04

# Injected events, as offsets from the first calendar day (0 .. DAYS-1).
GAP_OFFSETS = (18, 19)    # two consecutive days with no snapshot
SPIKE_OFFSET = 30
SPIKE_SERVICE = 'Amazon EC2'
SPIKE_MULTIPLIER = 3.0    # one day at ~3x normal, then back to normal
NEW_SERVICE_OFFSET = 38
NEW_SERVICE = 'Amazon CloudWatch'
NEW_SERVICE_BASE = 3.10


def _start(end_date):
    return end_date - timedelta(days=DAYS - 1)


def generate_demo_snapshots(end_date):
    """
    SYNTHETIC. Snapshots ending on end_date (a datetime.date), oldest
    first, in the same shape the real API returns:
    {'date': 'YYYY-MM-DD', 'total_cost': float, 'services': {name: float}}.

    The dollar amounts do not depend on end_date; only the dates shift.
    """
    rng = random.Random(SEED)
    start = _start(end_date)
    snapshots = []

    for offset in range(DAYS):
        # Draw noise for every day, including gap days, so the numbers on
        # either side of the gap don't depend on where the gap sits.
        noise = {name: rng.uniform(-NOISE_PCT, NOISE_PCT) for name in BASE_COSTS}
        new_noise = rng.uniform(-NOISE_PCT, NOISE_PCT)

        if offset in GAP_OFFSETS:
            continue

        services = {}
        for name, base in BASE_COSTS.items():
            cost = base * (1 + noise[name])
            if name == SPIKE_SERVICE and offset == SPIKE_OFFSET:
                cost *= SPIKE_MULTIPLIER
            services[name] = round(cost, 2)
        if offset >= NEW_SERVICE_OFFSET:
            services[NEW_SERVICE] = round(NEW_SERVICE_BASE * (1 + new_noise), 2)

        snapshots.append({
            'date': (start + timedelta(days=offset)).isoformat(),
            'total_cost': round(sum(services.values()), 2),
            'services': services,
        })

    return snapshots


def demo_ground_truth(end_date):
    """
    SYNTHETIC. The events deliberately injected into generate_demo_snapshots,
    with the detector flags each one should produce: a list of
    (level, service, date) tuples, service None for the aggregate.
    """
    start = _start(end_date)

    def day(offset):
        return (start + timedelta(days=offset)).isoformat()

    return [
        {
            'type': 'service_spike',
            'date': day(SPIKE_OFFSET),
            'service': SPIKE_SERVICE,
            'expected_flags': [('aggregate', None, day(SPIKE_OFFSET)),
                               ('service', SPIKE_SERVICE, day(SPIKE_OFFSET))],
        },
        {
            'type': 'new_service',
            'date': day(NEW_SERVICE_OFFSET),
            'service': NEW_SERVICE,
            'expected_flags': [('aggregate', None, day(NEW_SERVICE_OFFSET)),
                               ('service', NEW_SERVICE, day(NEW_SERVICE_OFFSET))],
        },
        {
            'type': 'ingestion_gap',
            'missing_dates': [day(o) for o in GAP_OFFSETS],
            'expected_flags': [],
        },
    ]
