"""Surfline forecast client.

Uses the JSON endpoints that power Surfline spot pages. The public HTML page is
often behind a browser challenge, while these endpoints expose the current
report and short-range forecast rows without a rendered browser.
"""
import json
import urllib.request
from datetime import datetime, timezone


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)
KTS_TO_KMH = 1.852

REPORT_URL = "https://services.surfline.com/kbyg/spots/reports?spotId={spot_id}"
FORECAST_URL = "https://services.surfline.com/kbyg/spots/forecasts/{kind}?spotId={spot_id}&days={days}&intervalHours=1"


def _get_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _round(value, ndigits=2):
    try:
        if value is None:
            return None
        return round(float(value), ndigits)
    except (TypeError, ValueError):
        return None


def _timestamp(ts):
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _by_timestamp(rows):
    out = {}
    for row in rows or []:
        ts = row.get("timestamp")
        if ts is not None:
            out[int(ts)] = row
    return out


def _wind_state(direction_type):
    if not direction_type:
        return None
    return str(direction_type).strip().lower().replace(" ", "-")


# Canonical 7-tier set per Surfline's surf-ratings documentation.
# LOTUS (model) maxes at FAIR TO GOOD (optimalScore=4); GOOD and EPIC are
# always forecaster-assigned and can never be inferred from optimalScore alone.
_SURFLINE_LABELS = {
    0: "VERY POOR",
    1: "POOR",
    2: "POOR TO FAIR",
    3: "FAIR",
    4: "FAIR TO GOOD",
    5: "GOOD",
}
_FORECASTER_ONLY_RATINGS = {"GOOD", "EPIC"}


def _condition_rating(report, fallback_wave=None):
    condition = (report.get("condition") or {}).get("value")
    if condition:
        return str(condition).upper().replace("_", " ")

    ad_units = (
        report.get("associated", {})
        .get("advertising", {})
        .get("conditionsBasedAdUnits", {})
    )
    if ad_units.get("pub_meta_9"):
        return str(ad_units["pub_meta_9"]).upper().replace("_", " ")

    score = None
    if fallback_wave:
        score = ((fallback_wave.get("surf") or {}).get("optimalScore"))
    if score is None:
        return None
    return _SURFLINE_LABELS.get(int(score), None)


def _rating_source(report, condition_rating):
    """Return 'forecaster' or 'model' for the given condition_rating.

    GOOD/EPIC are always forecaster-assigned. LOTUS (height+wind only, no
    tide/direction/spot dynamics) is the default for all other ratings.
    """
    if condition_rating in _FORECASTER_ONLY_RATINGS:
        return "forecaster"

    condition = report.get("condition") or {}
    for key in ("attribution", "source", "observed", "author", "expert", "observer"):
        val = condition.get(key)
        if val:
            v = str(val).lower()
            if any(k in v for k in ("forecast", "human", "expert", "observer")):
                return "forecaster"
            if any(k in v for k in ("model", "lotus", "machine", "auto")):
                return "model"

    report_data = report.get("data") or {}
    associated = report.get("associated") or {}
    if (report_data.get("forecasterName") or report_data.get("forecasterId")
            or associated.get("forecasterName")):
        return "forecaster"

    return "model"


def _swell_fields(swells, idx, prefix):
    if idx >= len(swells or []):
        return {}
    swell = swells[idx] or {}
    height = _round(swell.get("height"), 2)
    period = _round(swell.get("period"), 1)
    direction = _round(swell.get("direction"), 1)
    direction_min = _round(swell.get("directionMin"), 1)
    if not any(v not in (None, 0, 0.0) for v in (height, period, direction)):
        return {}
    return {
        f"{prefix}_swell_height_m": height,
        f"{prefix}_swell_period_s": period,
        f"{prefix}_swell_direction_deg": direction,
        f"{prefix}_swell_direction_min_deg": direction_min,
        f"{prefix}_swell_power": _round(swell.get("power"), 2),
        f"{prefix}_swell_impact": _round(swell.get("impact"), 2),
    }


def _normalize_current(report_payload, wave_payload, wind_payload, tide_payload, weather_payload, source_url=None):
    report = report_payload or {}
    associated = report.get("associated") or {}
    report_data = report.get("data") or {}
    conditions = report_data.get("conditions") or {}

    waves = ((wave_payload or {}).get("data") or {}).get("wave") or []
    winds = ((wind_payload or {}).get("data") or {}).get("wind") or []
    tides = ((tide_payload or {}).get("data") or {}).get("tides") or []
    weather = ((weather_payload or {}).get("data") or {}).get("weather") or []

    now_ts = datetime.now(timezone.utc).timestamp()
    current_wave = _nearest_timestamp(waves, now_ts)
    current_wind = _nearest_timestamp(winds, now_ts)
    current_tide = _nearest_timestamp(tides, now_ts)
    current_weather = _nearest_timestamp(weather, now_ts)

    report_wave_height = conditions.get("waveHeight") or {}
    report_wind = conditions.get("wind") or {}
    report_weather = conditions.get("weather") or {}
    water_temp = conditions.get("waterTemp") or {}
    wetsuit = conditions.get("wetsuit") or {}

    surf = (current_wave or {}).get("surf") or {}
    swells = (current_wave or {}).get("swells") or []
    wind = current_wind or report_wind
    tide = current_tide or {}
    weather_row = current_weather or report_weather

    _cond_rating = _condition_rating(report, current_wave)
    data = {
        "source": "surfline",
        "source_url": source_url or associated.get("href"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "surfline_fetched_at": datetime.now(timezone.utc).isoformat(),
        "model_init_utc": _timestamp(
            ((wave_payload or {}).get("associated") or {}).get("runInitializationTimestamp")
            or associated.get("runInitializationTimestamp")
        ),
        "condition_rating": _cond_rating,
        "surfline_rating_source": _rating_source(report, _cond_rating) if _cond_rating is not None else None,
        "surf_height_min_m": _round(surf.get("min", report_wave_height.get("min")), 2),
        "surf_height_max_m": _round(surf.get("max", report_wave_height.get("max")), 2),
        "surf_height_human": surf.get("humanRelation") or report_wave_height.get("humanRelation"),
        "wave_height": _round(surf.get("max", report_wave_height.get("max")), 2),
        "wave_period": _round((swells[0] or {}).get("period") if swells else None, 1),
        "wave_direction": _round((swells[0] or {}).get("direction") if swells else None, 1),
        "power": _round((current_wave or {}).get("power"), 2),
        "wind_speed_kts": _round(wind.get("speed"), 2),
        "wind_speed_kmh": _round((wind.get("speed") or 0) * KTS_TO_KMH if wind.get("speed") is not None else None, 2),
        "wind_direction_deg": _round(wind.get("direction"), 1),
        "wind_direction": _round(wind.get("direction"), 1),
        "wind_gust_kts": _round(wind.get("gust"), 2),
        "wind_gusts_kmh": _round((wind.get("gust") or 0) * KTS_TO_KMH if wind.get("gust") is not None else None, 2),
        "wind_state": _wind_state(wind.get("directionType")),
        "tide_height_m": _round(tide.get("height"), 2),
        "air_temp_c": _round(weather_row.get("temperature"), 1),
        "water_temp_c": _round(water_temp.get("max") or water_temp.get("min"), 1),
        "wetsuit_hint": " ".join(str(v) for v in (wetsuit.get("thickness"), wetsuit.get("type")) if v) or None,
    }
    data.update(_swell_fields(swells, 0, "primary"))
    data.update(_swell_fields(swells, 1, "secondary"))
    data.update(_swell_fields(swells, 2, "tertiary"))

    data["swell_height"] = data.get("primary_swell_height_m")
    data["swell_period"] = data.get("primary_swell_period_s")
    data["swell_direction"] = data.get("primary_swell_direction_deg")
    data["swell2_height"] = data.get("secondary_swell_height_m")
    data["swell2_period"] = data.get("secondary_swell_period_s")
    data["swell2_direction"] = data.get("secondary_swell_direction_deg")
    return {k: v for k, v in data.items() if v is not None}


def _nearest_timestamp(rows, target_ts):
    best = None
    best_diff = None
    for row in rows or []:
        ts = row.get("timestamp")
        if ts is None:
            continue
        diff = abs(float(ts) - target_ts)
        if best_diff is None or diff < best_diff:
            best = row
            best_diff = diff
    return best


def _normalize_hourly(wave_payload, wind_payload, tide_payload, weather_payload):
    wave_rows = _by_timestamp(((wave_payload or {}).get("data") or {}).get("wave"))
    wind_rows = _by_timestamp(((wind_payload or {}).get("data") or {}).get("wind"))
    tide_rows = _by_timestamp(((tide_payload or {}).get("data") or {}).get("tides"))
    weather_rows = _by_timestamp(((weather_payload or {}).get("data") or {}).get("weather"))

    hourly = []
    for ts in sorted(set(wave_rows) | set(wind_rows) | set(tide_rows) | set(weather_rows)):
        wave = wave_rows.get(ts) or {}
        surf = wave.get("surf") or {}
        swells = wave.get("swells") or []
        wind = wind_rows.get(ts) or {}
        tide = tide_rows.get(ts) or {}
        weather = weather_rows.get(ts) or {}
        row = {
            "timestamp_utc": _timestamp(ts),
            "wave_height": _round(surf.get("max"), 2),
            "wave_period": _round((swells[0] or {}).get("period") if swells else None, 1),
            "wave_direction": _round((swells[0] or {}).get("direction") if swells else None, 1),
            "swell_height": _round((swells[0] or {}).get("height") if swells else None, 2),
            "swell_period": _round((swells[0] or {}).get("period") if swells else None, 1),
            "swell_direction": _round((swells[0] or {}).get("direction") if swells else None, 1),
            "swell2_height": _round((swells[1] or {}).get("height") if len(swells) > 1 else None, 2),
            "swell2_period": _round((swells[1] or {}).get("period") if len(swells) > 1 else None, 1),
            "swell2_direction": _round((swells[1] or {}).get("direction") if len(swells) > 1 else None, 1),
            "wind_wave_height": None,
            "wind_speed": _round((wind.get("speed") or 0) * KTS_TO_KMH if wind.get("speed") is not None else None, 2),
            "wind_direction": _round(wind.get("direction"), 1),
            "wind_gusts": _round((wind.get("gust") or 0) * KTS_TO_KMH if wind.get("gust") is not None else None, 2),
            "tide_height_m": _round(tide.get("height"), 2),
            "air_temp": _round(weather.get("temperature"), 1),
            "surfline_optimal_score": surf.get("optimalScore"),
        }
        hourly.append({k: v for k, v in row.items() if v is not None})
    return hourly


def parse_payloads(report_payload, wave_payload, wind_payload, tide_payload, weather_payload, source_url=None):
    current = _normalize_current(report_payload, wave_payload, wind_payload, tide_payload, weather_payload, source_url)
    hourly = _normalize_hourly(wave_payload, wind_payload, tide_payload, weather_payload)
    return {
        "fetched_at": current.get("fetched_at"),
        "current": current,
        "hourly": hourly,
    }


def fetch(spot_id, source_url=None, days=7):
    report = _get_json(REPORT_URL.format(spot_id=spot_id))
    wave = _get_json(FORECAST_URL.format(kind="wave", spot_id=spot_id, days=days))
    wind = _get_json(FORECAST_URL.format(kind="wind", spot_id=spot_id, days=days))
    tides = _get_json(FORECAST_URL.format(kind="tides", spot_id=spot_id, days=days))
    weather = _get_json(FORECAST_URL.format(kind="weather", spot_id=spot_id, days=days))
    return parse_payloads(report, wave, wind, tides, weather, source_url=source_url)
