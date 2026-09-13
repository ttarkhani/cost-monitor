import time
from backend import cache


def run_test():
    cache.clear()
    print("Cache cleared.\n")

    print("1) Expect MISS (nothing set yet):")
    result = cache.get("costs:demo")
    print(f"   get() -> {result}")
    assert result is None

    print("\n2) Setting value with a 2-second TTL...")
    cache.set("costs:demo", [{"date": "2026-09-13", "total_cost": 9.8}], ttl_seconds=2)

    print("\n3) Expect HIT (just set, still within TTL):")
    result = cache.get("costs:demo")
    print(f"   get() -> {result}")
    assert result is not None

    print("\n4) Waiting 2.5s for TTL to expire...")
    time.sleep(2.5)

    print("\n5) Expect MISS (TTL expired):")
    result = cache.get("costs:demo")
    print(f"   get() -> {result}")
    assert result is None

    stats = cache.get_stats()
    print(f"\nFinal stats: {stats}")
    assert stats["hits"] == 1
    assert stats["misses"] == 2

    print("\nSUCCESS: cache stores, expires on schedule, and tracks accurate hit/miss stats.")


if __name__ == '__main__':
    run_test()