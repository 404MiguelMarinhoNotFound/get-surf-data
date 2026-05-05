"""Live RCA helper for hero-card surf windows.

Run from the project root:
    python scripts/diagnose_windows.py

This script is intentionally read-only. It fetches the same live sources as the
sync endpoint, then prints why the seven-day hero window carousel does or does
not receive eligible windows.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import copernicus_ibi  # noqa: E402
import copernicus_ibi_explainer  # noqa: E402
import explainer  # noqa: E402
import noaa_gfs  # noqa: E402
import noaa_gfs_explainer  # noqa: E402
import open_meteo  # noqa: E402
import open_meteo_explainer  # noqa: E402
import scraper  # noqa: E402
import unified_explainer as unified  # noqa: E402

SPOTS = json.loads((ROOT / "spots.json").read_text(encoding="utf-8"))


def _safe_fetch(fn):
    try:
        return fn(), None
    except Exception as exc:  # Network diagnostics should continue source by source.
        return None, f"{type(exc).__name__}: {exc}"


def _fmt_score(value):
    if value is None:
        return "None"
    return f"{float(value):.2f}"


def _sf_stats(sf_data):
    cells = sf_data.get("rating_timeline") or []
    ratings = [cell.get("rating") for cell in cells if cell.get("rating") is not None]
    timestamps = [
        cell.get("timestamp_utc")
        for cell in cells
        if cell.get("timestamp_utc")
    ]
    return {
        "cells": len(cells),
        "ratings": len(ratings),
        "min": min(ratings) if ratings else None,
        "max": max(ratings) if ratings else None,
        "low": sum(1 for rating in ratings if rating <= 2),
        "start": min(timestamps) if timestamps else None,
        "end": max(timestamps) if timestamps else None,
    }


def _build_scored_hours(sf_data, om_hourly, gfs_hourly, ibi_hourly, spot, level, now):
    sf_cells = unified._sf_cells(sf_data.get("rating_timeline", []))
    om_hours = unified._om_by_hour(om_hourly or [])
    gfs_hours = unified._om_by_hour(gfs_hourly or [])
    ibi_hours = unified._om_by_hour(ibi_hourly or [])
    cutoff = now + timedelta(days=7)
    scored = []
    require_sf = bool(sf_cells)

    for hour_dt in sorted(set(om_hours) | set(gfs_hours) | set(ibi_hours)):
        if hour_dt < now.replace(minute=0, second=0, microsecond=0):
            continue
        if hour_dt > cutoff:
            continue
        row = unified._score_hour(
            hour_dt,
            sf_cells,
            om_hours,
            spot,
            level=level,
            require_sf=require_sf,
            gfs_by_hour=gfs_hours,
            ibi_by_hour=ibi_hours,
        )
        if row is not None:
            scored.append(row)

    return sorted(scored, key=lambda row: row["dt"])


def _blocker_counts(scored_hours):
    counts = Counter()
    for row in scored_hours:
        reasons = list(row.get("blocked_by") or [])
        if not reasons and row.get("has_hard_gate"):
            gate = row.get("hard_gate") or {}
            reasons = [gate.get("source") or "hard_gate"]
        if not reasons and not row.get("window_eligible", True):
            reasons = ["ineligible_unknown"]
        if not reasons and (
            row.get("decider_score") is None
            or row.get("decider_score") < unified.SCORE_BEST_WINDOW
        ):
            reasons = ["score_below_5"]
        if not reasons:
            reasons = ["eligible_decent"]
        counts.update(reasons)
    return counts


def _interpret_sources(sf_data, om_data, gfs_data, ibi_data, spot, level):
    om_analysis = None
    if om_data:
        om_analysis = open_meteo_explainer.interpret_all(
            current=om_data.get("current"),
            today_hours=om_data.get("today_hours", []),
            sf_height_m=sf_data.get("height_m"),
            optimal_bearing=spot.get("optimal_swell_bearing"),
            offshore_bearing=spot.get("offshore_bearing"),
            optimal_label=spot.get("optimal_swell_label"),
            level=level,
        )

    gfs_analysis = None
    if gfs_data:
        gfs_analysis = noaa_gfs_explainer.interpret_all(
            current=gfs_data.get("current"),
            optimal_bearing=spot.get("optimal_swell_bearing"),
            offshore_bearing=spot.get("offshore_bearing"),
            optimal_label=spot.get("optimal_swell_label"),
            level=level,
        )

    ibi_analysis = None
    if ibi_data:
        ibi_analysis = copernicus_ibi_explainer.interpret_all(
            current=ibi_data.get("current"),
            optimal_bearing=spot.get("optimal_swell_bearing"),
            offshore_bearing=spot.get("offshore_bearing"),
            optimal_label=spot.get("optimal_swell_label"),
            level=level,
        )

    return om_analysis, gfs_analysis, ibi_analysis


def _print_windows(label, windows):
    top = windows.get("top_windows") or []
    print(f"  {label}: top_windows={len(top)} now_tier={windows.get('now_tier')}")
    if windows.get("best_window"):
        best = windows["best_window"]
        print(
            "    best="
            f"{best.get('label')} score={best.get('score')} starts={best.get('starts_at')}"
        )
    for window in top[:5]:
        pieces = []
        for component in window.get("score_components", []):
            pieces.append(
                "score={score} sf={sf} om={om} gfs={gfs} ibi={ibi}".format(
                    score=component.get("score"),
                    sf=component.get("sf_raw_rating"),
                    om=component.get("om_score"),
                    gfs=component.get("gfs_score"),
                    ibi=component.get("ibi_score"),
                )
            )
        print(f"    - {window.get('label')} score={window.get('score')} [{'; '.join(pieces)}]")


def diagnose_spot(spot, level, now):
    print("\n" + "=" * 88)
    print(f"{spot['name']} ({spot['id']}) @ {now.isoformat()}")

    sf_data, sf_error = _safe_fetch(lambda: scraper.scrape(spot["url"], tz_name=spot.get("tz")))
    om_data, om_error = _safe_fetch(lambda: open_meteo.fetch(spot["lat"], spot["lon"], now))
    gfs_data, gfs_error = _safe_fetch(lambda: noaa_gfs.fetch(spot["lat"], spot["lon"], now))
    ibi_data, ibi_error = _safe_fetch(
        lambda: copernicus_ibi.fetch(
            spot["lat"],
            spot["lon"],
            offshore_bearing=spot.get("offshore_bearing"),
        )
    )

    sf_data = sf_data or {}
    om_hourly = (om_data or {}).get("hourly", [])
    gfs_hourly = (gfs_data or {}).get("hourly", [])
    ibi_hourly = (ibi_data or {}).get("hourly", [])

    print(
        "fetch: "
        f"SF={'ok' if sf_data else sf_error}; "
        f"OM={len(om_hourly)}h error={om_error}; "
        f"GFS={len(gfs_hourly)}h error={gfs_error}; "
        f"IBI={len(ibi_hourly)}h error={ibi_error or ('none' if not ibi_data else None)}"
    )
    print(
        "sf_now: "
        f"rating={sf_data.get('rating')} "
        f"height={sf_data.get('height_m')}m "
        f"period={sf_data.get('period_s')}s "
        f"swell={sf_data.get('swell_direction')} "
        f"wind={sf_data.get('wind_state')} "
        f"issued={sf_data.get('upstream_issued_at')}"
    )

    stats = _sf_stats(sf_data)
    print(
        "sf_timeline: "
        f"cells={stats['cells']} ratings={stats['ratings']} "
        f"range={stats['start']}..{stats['end']} "
        f"min={stats['min']} max={stats['max']} <=2={stats['low']}"
    )

    sf_with_verdict = dict(sf_data)
    if sf_with_verdict:
        sf_with_verdict.update(explainer.verdict(sf_with_verdict, level, spot))

    om_analysis, gfs_analysis, ibi_analysis = _interpret_sources(
        sf_with_verdict,
        om_data,
        gfs_data,
        ibi_data,
        spot,
        level,
    )
    unified_result = unified.unify(
        sf_data=sf_with_verdict,
        om_analysis=om_analysis,
        om_hourly=om_hourly,
        spot=spot,
        level=level,
        ibi_analysis=ibi_analysis,
        gfs_analysis=gfs_analysis,
        gfs_hourly=gfs_hourly,
        ibi_hourly=ibi_hourly,
    )
    print(
        "current: "
        f"decision={unified_result.get('decision')} "
        f"score={unified_result.get('score')} "
        f"sources={unified_result.get('sources_used')} "
        f"confidence={unified_result.get('confidence')} "
        f"gate={unified_result.get('hard_gate_detail')}"
    )
    print(f"source_scores={unified_result.get('source_scores')} weights={unified_result.get('weights')}")

    scored = _build_scored_hours(sf_data, om_hourly, gfs_hourly, ibi_hourly, spot, level, now)
    decent = [row for row in scored if unified._hour_is_decent(row)]
    max_score = max((row.get("decider_score") or -1 for row in scored), default=None)
    print(
        "scored_hours: "
        f"total={len(scored)} decent={len(decent)} "
        f"max_score={_fmt_score(max_score) if max_score is not None else 'None'}"
    )
    print(f"blockers={dict(_blocker_counts(scored).most_common())}")

    normal_windows = unified.find_next_windows(
        sf_data.get("rating_timeline", []),
        om_hourly,
        spot,
        now.isoformat(),
        gfs_hourly=gfs_hourly,
        ibi_hourly=ibi_hourly,
        level=level,
    )
    model_only_windows = unified.find_next_windows(
        [],
        om_hourly,
        spot,
        now.isoformat(),
        gfs_hourly=gfs_hourly,
        ibi_hourly=ibi_hourly,
        level=level,
    )
    _print_windows("normal", normal_windows)
    _print_windows("model_only_counterfactual", model_only_windows)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Diagnose hero-card best-window eligibility.")
    parser.add_argument(
        "--spot",
        action="append",
        dest="spots",
        help="Spot id to diagnose. Can be repeated. Defaults to every spot.",
    )
    parser.add_argument(
        "--level",
        default=explainer.DEFAULT_LEVEL,
        choices=sorted(explainer.VALID_LEVELS),
        help="Skill tier to score. Defaults to improver.",
    )
    args = parser.parse_args(argv)

    selected = [
        spot for spot in SPOTS
        if not args.spots or spot["id"] in set(args.spots)
    ]
    unknown = sorted(set(args.spots or []) - {spot["id"] for spot in SPOTS})
    if unknown:
        print(f"Unknown spot id(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    print(f"Hero window diagnostics at {now.isoformat()} level={args.level}")
    for spot in selected:
        diagnose_spot(spot, args.level, now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
