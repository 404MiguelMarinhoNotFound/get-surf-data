"""Populate the Neon forecast cache with the latest source data."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import forecast_cache


def main():
    result = forecast_cache.refresh_cache(force=True)
    print(f"status={result.get('status')}")
    print(f"spots={result.get('spots', 0)}")
    print(f"levels={result.get('levels', 0)}")
    if result.get("last_success_slot_local"):
        print(f"last_success_slot_local={result['last_success_slot_local']}")
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
