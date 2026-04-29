"""
Cross-check: surf-forecast.com (scraper) vs Open-Meteo Marine.

Run manually:  python scripts/cross_check_sources.py
Appends one CSV row per spot per run to scripts/cross_check_log.csv.

Purpose: measure divergence between the two sources to calibrate the
confidence thresholds in open_meteo_explainer.py.
"""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scraper
import open_meteo

SPOTS = json.loads((ROOT / "spots.json").read_text(encoding="utf-8"))
LOG_FILE = Path(__file__).parent / "cross_check_log.csv"

_DIRECTION_DEGREES = {
    "N": 0, "NNE": 22, "NE": 45, "ENE": 67,
    "E": 90, "ESE": 112, "SE": 135, "SSE": 157,
    "S": 180, "SSW": 202, "SW": 225, "WSW": 247,
    "W": 270, "WNW": 292, "NW": 315, "NNW": 337,
}

_OFFSHORE_LABELS = {
    "Offshore": {"offshore", "offshore"},
    "Cross-offshore": {"cross-offshore"},
    "Cross-shore": {"cross-shore"},
    "Cross-onshore": {"cross-onshore"},
    "Onshore": {"onshore"},
}


def _bearing_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _pct(a, b) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round(abs(a - b) / b * 100, 1)


def _om_wind_label(wind_dir_deg: float | None, offshore_bearing: float | None) -> str:
    if wind_dir_deg is None or offshore_bearing is None:
        return "unknown"
    diff = _bearing_diff(wind_dir_deg, offshore_bearing)
    if diff <= 30:
        return "offshore"
    if diff <= 60:
        return "cross-offshore"
    if diff <= 120:
        return "cross-shore"
    if diff <= 150:
        return "cross-onshore"
    return "onshore"


def _winds_agree(sf_wind: str | None, om_label: str) -> str:
    if sf_wind is None:
        return "unknown"
    sf_norm = sf_wind.lower().replace(" ", "-")
    return "AGREE" if sf_norm == om_label else f"DISAGREE (sf={sf_norm}, om={om_label})"


def _check_spot(spot: dict, now_utc: datetime) -> dict:
    sid = spot["id"]
    name = spot["name"]
    offshore_bearing = spot.get("offshore_bearing")

    print(f"\nSpot: {name}")

    # --- surf-forecast.com ---
    sf = {}
    sf_error = None
    try:
        sf = scraper.scrape(spot["url"], tz_name=spot.get("tz"))
    except Exception as e:
        sf_error = str(e)
        print(f"  [ERROR] SF scrape failed: {e}")

    # --- Open-Meteo ---
    om = {}
    om_error = None
    try:
        om_data = open_meteo.fetch(spot["lat"], spot["lon"], now_utc)
        om = om_data.get("current") or {}
    except Exception as e:
        om_error = str(e)
        print(f"  [ERROR] OM fetch failed: {e}")

    sf_height = sf.get("height_m")
    sf_period = sf.get("period_s")
    sf_dir_text = sf.get("swell_direction")
    sf_wind = sf.get("wind_state")
    sf_rating = sf.get("rating")

    om_wave = om.get("wave_height")
    om_swell = om.get("swell_height")
    om_period = om.get("swell_period")
    om_dir_deg = om.get("swell_direction")
    om_wind_dir = om.get("wind_direction")
    om_wind_speed = om.get("wind_speed")

    sf_dir_deg = _DIRECTION_DEGREES.get(sf_dir_text) if sf_dir_text else None
    dir_diff = round(_bearing_diff(sf_dir_deg, om_dir_deg), 1) if (sf_dir_deg is not None and om_dir_deg is not None) else None
    om_wind_label = _om_wind_label(om_wind_dir, offshore_bearing)
    wind_agree = _winds_agree(sf_wind, om_wind_label)

    h_div = _pct(sf_height, om_wave)
    s_div = _pct(sf_height, om_swell)
    p_div = _pct(sf_period, om_period)

    # Print comparison
    if sf_height is not None or om_wave is not None:
        print(f"  Height     SF={sf_height}m   OM wave={om_wave}m   OM swell={om_swell}m"
              f"   d wave={h_div}%   d swell={s_div}%")
    if sf_period is not None or om_period is not None:
        print(f"  Period     SF={sf_period}s   OM={om_period}s   d={p_div}%")
    if sf_dir_text or om_dir_deg is not None:
        print(f"  Direction  SF={sf_dir_text} ({sf_dir_deg}deg)   OM={om_dir_deg}deg   d={dir_diff}deg")
    if sf_wind or om_wind_dir is not None:
        print(f"  Wind       SF={sf_wind}   OM={om_wind_label} ({om_wind_speed} km/h from {om_wind_dir}deg)   => {wind_agree}")
    if sf_rating is not None:
        print(f"  SF rating  {sf_rating}/10")

    return {
        "timestamp_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "spot_id": sid,
        "sf_height_m": sf_height,
        "om_wave_height": om_wave,
        "om_swell_height": om_swell,
        "sf_period_s": sf_period,
        "om_swell_period": om_period,
        "sf_direction_text": sf_dir_text,
        "sf_direction_deg": sf_dir_deg,
        "om_swell_direction_deg": om_dir_deg,
        "sf_wind_state": sf_wind,
        "om_wind_label": om_wind_label,
        "wind_agree": wind_agree,
        "sf_rating": sf_rating,
        "height_divergence_pct": h_div,
        "swell_divergence_pct": s_div,
        "period_divergence_pct": p_div,
        "direction_diff_deg": dir_diff,
        "sf_error": sf_error,
        "om_error": om_error,
    }


def _append_csv(rows: list[dict]) -> None:
    fieldnames = [
        "timestamp_utc", "spot_id",
        "sf_height_m", "om_wave_height", "om_swell_height",
        "sf_period_s", "om_swell_period",
        "sf_direction_text", "sf_direction_deg", "om_swell_direction_deg",
        "sf_wind_state", "om_wind_label", "wind_agree",
        "sf_rating",
        "height_divergence_pct", "swell_divergence_pct",
        "period_divergence_pct", "direction_diff_deg",
        "sf_error", "om_error",
    ]
    write_header = not LOG_FILE.exists()
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def main():
    now_utc = datetime.now(timezone.utc)
    print(f"Cross-check: {now_utc.strftime('%Y-%m-%d %H:%M')} UTC")
    print("-" * 55)

    rows = [_check_spot(spot, now_utc) for spot in SPOTS]

    print(f"\n{'-' * 55}")
    _append_csv(rows)
    print(f"Logged {len(rows)} row(s) => {LOG_FILE}")

    # Summary guidance
    divs = [r["height_divergence_pct"] for r in rows if r["height_divergence_pct"] is not None]
    if divs:
        avg = sum(divs) / len(divs)
        flag = " !! HIGH — consider keeping SF height as primary" if avg > 30 else " OK within tolerance"
        print(f"Avg height divergence: {avg:.1f}%{flag}")


if __name__ == "__main__":
    main()
