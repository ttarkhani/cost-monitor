from backend.pipeline import run_daily_pipeline


def main():
    """
    Manual/local entry point. A thin wrapper around the same
    run_daily_pipeline() the scheduled Lambda calls, so there is exactly
    one implementation of fetch -> detect -> alert.
    """
    print("Running the daily pipeline (fetch yesterday, detect, alert)...\n")
    result = run_daily_pipeline()

    if not result['ingested']:
        print(f"ERROR: {result.get('error')}")
        print("\nThis is expected right now if Cost Explorer is still indexing")
        print("your account (can take up to 24h after first enabling it).")
        return

    print(f"SUCCESS: Stored snapshot for {result['date']}")
    print(f"  Total cost: ${result['total_cost']:.4f}")
    print(f"  Services with spend: {result['service_count']}")

    print("\nAnomaly check:")
    print(f"  Anomalies anywhere in the history window: {result['anomaly_count']}")
    print(f"  New anomalies dated {result['date']}: {result['new_anomaly_count']}")
    if result['alert_sent']:
        print("  Alert sent (new anomalies only).")
    else:
        print("  No new anomalies. No alert sent.")


if __name__ == '__main__':
    main()
