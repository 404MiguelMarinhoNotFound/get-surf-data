"""Live canary for Lineup data freshness and parse completeness.

Run from the project root:
    python scripts/check_latest_surf_data.py

The script exits non-zero if surf-forecast.com data is missing, implausible,
or older than the accepted freshness window.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scraper  # noqa: E402

SPOTS = json.loads((ROOT / "spots.json").read_text(encoding="utf-8"))

REQUIRED_FIELDS = (
    "height_m",
    "period_s",
    "swell_direction",
    "wind_state",
    "upstream_issued_at",
)

VALID_WIND_STATES = {
    "glassy",
    "offshore",
    "onshore",
    "cross",
    "cross-shore",
    "cross-offshore",
    "cross-onshore",
}


def parse_iso_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hours_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600


def validate_data(data: dict, *, now: datetime, max_age_hours: float) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for field in REQUIRED_FIELDS:
        if data.get(field) in (None, ""):
            errors.append(f"missing required field: {field}")

    height = data.get("height_m")
    if height is not None and not (0 < float(height) < 15):
        errors.append(f"height_m={height!r} outside sane range 0-15m")

    period = data.get("period_s")
    if period is not None and not (3 <= int(period) <= 25):
        errors.append(f"period_s={period!r} outside sane range 3-25s")

    wind = data.get("wind_state")
    if wind is not None and str(wind).lower() not in VALID_WIND_STATES:
        errors.append(f"wind_state={wind!r} is not recognized")

    rating = data.get("rating")
    if rating is None:
        warnings.append("rating missing")
    elif not (0 <= int(rating) <= 20):
        warnings.append(f"rating={rating!r} outside expected 0-20 range")

    sea_temp = data.get("sea_temp_c")
    if sea_temp is None:
        warnings.append("sea_temp_c missing")
    elif not (5 <= float(sea_temp) <= 30):
        warnings.append(f"sea_temp_c={sea_temp!r} outside expected 5-30C range")

    fetched_at = data.get("fetched_at")
    if fetched_at:
        fetched_age_minutes = hours_between(parse_iso_datetime(fetched_at), now) * 60
        if fetched_age_minutes < -1:
            errors.append(f"fetched_at={fetched_at!r} is in the future")
        elif fetched_age_minutes > 5:
            errors.append(f"fetched_at={fetched_at!r} is not from this run")

    issued_at = data.get("upstream_issued_at")
    if issued_at:
        issued_age_hours = hours_between(parse_iso_datetime(issued_at), now)
        if issued_age_hours < -0.5:
            errors.append(f"upstream_issued_at={issued_at!r} is unexpectedly in the future")
        elif issued_age_hours > max_age_hours:
            errors.append(
                f"upstream forecast is stale: {issued_age_hours:.1f}h old "
                f"(limit {max_age_hours:.1f}h)"
            )

    return errors, warnings


def check_spot(spot: dict, *, now: datetime, max_age_hours: float) -> dict:
    try:
        data = scraper.scrape(spot["url"])
        errors, warnings = validate_data(data, now=now, max_age_hours=max_age_hours)
    except Exception as exc:  # Network and parser crashes should fail the canary.
        data = {}
        errors = [f"scrape failed: {type(exc).__name__}: {exc}"]
        warnings = []

    return {
        "spot_id": spot["id"],
        "spot_name": spot["name"],
        "url": spot["url"],
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "data": {
            key: data.get(key)
            for key in (
                "height_m",
                "period_s",
                "swell_direction",
                "wind_state",
                "rating",
                "sea_temp_c",
                "fetched_at",
                "upstream_issued_at",
            )
        },
    }


def check_all_spots(*, max_age_hours: float, spot_ids: set[str] | None = None) -> dict:
    now = datetime.now(timezone.utc)
    selected = [spot for spot in SPOTS if not spot_ids or spot["id"] in spot_ids]
    return {
        "checked_at": now.isoformat(),
        "max_age_hours": max_age_hours,
        "results": [
            check_spot(spot, now=now, max_age_hours=max_age_hours)
            for spot in selected
        ],
    }


def print_human_report(report: dict) -> None:
    print(f"Lineup live data check at {report['checked_at']}")
    print(f"Freshness limit: {report['max_age_hours']}h\n")

    for result in report["results"]:
        status = "OK" if result["ok"] else "FAIL"
        data = result["data"]
        print(f"[{status}] {result['spot_name']} ({result['spot_id']})")
        print(
            "  "
            f"height={data.get('height_m')}m, "
            f"period={data.get('period_s')}s, "
            f"swell={data.get('swell_direction')}, "
            f"wind={data.get('wind_state')}"
        )
        print(f"  upstream_issued_at={data.get('upstream_issued_at')}")
        print(f"  fetched_at={data.get('fetched_at')}")
        for warning in result["warnings"]:
            print(f"  WARN: {warning}")
        for error in result["errors"]:
            print(f"  ERROR: {error}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check live surf data freshness and parser health.")
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=float(os.environ.get("SURF_MAX_UPSTREAM_AGE_HOURS", "8")),
        help="Maximum accepted age of surf-forecast.com's issued timestamp.",
    )
    parser.add_argument(
        "--spot",
        action="append",
        dest="spots",
        help="Spot id to check. Can be repeated. Defaults to every spot in spots.json.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = check_all_spots(
        max_age_hours=args.max_age_hours,
        spot_ids=set(args.spots) if args.spots else None,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human_report(report)

    return 0 if all(result["ok"] for result in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
