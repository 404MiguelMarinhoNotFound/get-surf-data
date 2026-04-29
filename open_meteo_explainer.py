"""
Surf-quality interpretation functions driven by Open-Meteo Marine data.
Pure functions — no I/O, stdlib math only.
All take individual scalar values so they're unit-testable without mocking.
"""
import math


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bearing_diff(a: float, b: float) -> float:
    """Shortest angular distance between two compass bearings (0–180)."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


# ---------------------------------------------------------------------------
# 1. Swell purity
# ---------------------------------------------------------------------------

def swell_purity(wave_height: float | None, wind_wave_height: float | None) -> dict:
    """How much of the total wave energy is wind-sea vs. organised swell."""
    if not wave_height or wave_height <= 0:
        return {"score": None, "label": "No wave data", "color": "unknown"}
    wind_h = wind_wave_height or 0.0
    ratio = wind_h / wave_height
    if ratio < 0.25:
        label, color = "Clean swell", "green"
    elif ratio <= 0.50:
        label, color = "Mixed", "yellow"
    else:
        label, color = "Wind-dominated chop", "red"
    return {"score": round(ratio, 2), "label": label, "color": color}


# ---------------------------------------------------------------------------
# 2. Swell quality (period-based)
# ---------------------------------------------------------------------------

def swell_quality(period_s: float | None) -> dict:
    if period_s is None:
        return {"label": "No period data", "color": "unknown"}
    if period_s < 8:
        label, color = "Poor — short-period chop", "red"
    elif period_s <= 11:
        label, color = "Fair — medium-period swell", "yellow"
    elif period_s <= 15:
        label, color = "Good — quality groundswell", "green"
    else:
        label, color = "Excellent — long-period groundswell", "green"
    return {"label": label, "color": color}


# ---------------------------------------------------------------------------
# 3. Direction precision vs. spot's optimal bearing
# ---------------------------------------------------------------------------

def direction_precision(swell_dir_deg: float | None, optimal_bearing: float | None) -> dict:
    if swell_dir_deg is None or optimal_bearing is None:
        return {"diff_deg": None, "label": "No direction data", "color": "unknown"}
    diff = int(round(_bearing_diff(swell_dir_deg, optimal_bearing)))
    if diff <= 20:
        label, color = "On target", "green"
    elif diff <= 45:
        label, color = "Slightly off", "yellow"
    else:
        label, color = "Wrong direction", "red"
    return {"diff_deg": diff, "label": label, "color": color}


# ---------------------------------------------------------------------------
# 4. Wind assessment (exact angle + speed)
# ---------------------------------------------------------------------------

def wind_assessment(
    wind_speed_kmh: float | None,
    wind_dir_deg: float | None,
    offshore_bearing: float | None,
) -> dict:
    if wind_dir_deg is None or offshore_bearing is None:
        return {"angle_deg": None, "angle_label": "No wind data", "speed_label": "", "color": "unknown", "summary": "No wind data"}

    angle = int(round(_bearing_diff(wind_dir_deg, offshore_bearing)))

    if angle <= 30:
        angle_label, color = "Offshore", "green"
    elif angle <= 60:
        angle_label, color = "Cross-offshore", "green"
    elif angle <= 120:
        angle_label, color = "Cross-shore", "yellow"
    elif angle <= 150:
        angle_label, color = "Cross-onshore", "yellow"
    else:
        angle_label, color = "Onshore", "red"

    speed = wind_speed_kmh or 0.0
    if speed < 10:
        speed_label = "Light"
    elif speed <= 20:
        speed_label = "Moderate"
    elif speed <= 30:
        speed_label = "Fresh"
    elif speed <= 40:
        speed_label = "Strong"
    else:
        speed_label = "Gale"

    summary = f"{round(speed)} km/h {angle_label} ({angle}° off)"
    return {
        "angle_deg": angle,
        "angle_label": angle_label,
        "speed_label": speed_label,
        "color": color,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# 5. Secondary swell interference
# ---------------------------------------------------------------------------

def secondary_swell_interference(
    swell1_height: float | None,
    swell2_height: float | None,
    swell1_dir: float | None,
    swell2_dir: float | None,
) -> dict:
    if not swell1_height or swell1_height <= 0 or not swell2_height:
        return {"flag": False, "label": "Clean dominant swell", "color": "green"}

    ratio = swell2_height / swell1_height
    dir_diff = _bearing_diff(swell1_dir or 0, swell2_dir or 0) if (swell1_dir is not None and swell2_dir is not None) else 0

    if ratio > 0.40 and dir_diff > 60:
        return {"flag": True, "label": "Confused/crossed seas", "color": "red"}
    if ratio > 0.40:
        return {"flag": False, "label": "Secondary swell stacking (same window)", "color": "yellow"}
    return {"flag": False, "label": "Clean dominant swell", "color": "green"}


# ---------------------------------------------------------------------------
# 6. Best 3-hour window today
# ---------------------------------------------------------------------------

def _hour_score(h: dict, optimal_bearing: float | None, offshore_bearing: float | None) -> float:
    wave_h = h.get("swell_height") or h.get("wave_height") or 0.0
    period = h.get("swell_period") or h.get("wave_period") or 0.0
    wind_h = h.get("wind_wave_height") or 0.0
    swell_dir = h.get("swell_direction")
    wind_dir = h.get("wind_direction")

    # Height 0–10 (0m→0, 3m→10, clamped)
    h_score = min(wave_h / 3.0 * 10, 10)

    # Period 0–10
    if period < 8:
        p_score = 2.0
    elif period <= 11:
        p_score = 5.0
    elif period <= 15:
        p_score = 8.0
    else:
        p_score = 10.0

    # Purity 0–10
    ratio = wind_h / wave_h if wave_h > 0 else 0.0
    if ratio < 0.25:
        pur_score = 10.0
    elif ratio <= 0.50:
        pur_score = 5.0
    else:
        pur_score = 2.0

    # Direction 0–10
    if swell_dir is not None and optimal_bearing is not None:
        diff = _bearing_diff(swell_dir, optimal_bearing)
        if diff <= 20:
            dir_score = 10.0
        elif diff <= 45:
            dir_score = 7.0
        elif diff <= 90:
            dir_score = 4.0
        else:
            dir_score = 1.0
    else:
        dir_score = 5.0

    # Wind 0–10
    if wind_dir is not None and offshore_bearing is not None:
        wdiff = _bearing_diff(wind_dir, offshore_bearing)
        if wdiff <= 30:
            wind_score = 10.0
        elif wdiff <= 60:
            wind_score = 7.0
        elif wdiff <= 120:
            wind_score = 5.0
        elif wdiff <= 150:
            wind_score = 3.0
        else:
            wind_score = 1.0
    else:
        wind_score = 5.0

    return (h_score * 0.30 + p_score * 0.25 + pur_score * 0.20 + dir_score * 0.15 + wind_score * 0.10)


def best_hourly_window(
    today_hours: list[dict],
    optimal_bearing: float | None,
    offshore_bearing: float | None,
) -> dict | None:
    if not today_hours:
        return None

    scores = [_hour_score(h, optimal_bearing, offshore_bearing) for h in today_hours]

    # Slide a 3-hour window
    best_start = 0
    best_sum = -1.0
    for i in range(len(scores) - 2):
        window_sum = scores[i] + scores[i + 1] + scores[i + 2]
        if window_sum > best_sum:
            best_sum = window_sum
            best_start = i

    avg_score = round(best_sum / 3, 1)
    hours_subset = today_hours[best_start:best_start + 3]

    # Extract display hours from timestamp_utc
    def _hour_str(h):
        ts = h.get("timestamp_utc", "")
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(ts)
            return dt.strftime("%H:%M")
        except Exception:
            return ts[11:16] if len(ts) >= 16 else "?"

    start_str = _hour_str(hours_subset[0])
    end_h = today_hours[min(best_start + 3, len(today_hours) - 1)]
    end_str = _hour_str(end_h)

    return {
        "best_start_hour": best_start,
        "hours": list(range(best_start, best_start + 3)),
        "label": f"{start_str}–{end_str} (score {avg_score}/10)",
        "score": avg_score,
    }


# ---------------------------------------------------------------------------
# 7. Data confidence (OM vs SF height divergence)
# ---------------------------------------------------------------------------

def data_confidence(om_swell_height: float | None, sf_height_m: float | None) -> dict:
    if om_swell_height is None or sf_height_m is None or sf_height_m == 0:
        return {"label": "Insufficient data", "color": "unknown", "divergence_pct": None}

    divergence = abs(om_swell_height - sf_height_m) / sf_height_m
    div_pct = round(divergence * 100, 1)

    if divergence < 0.20:
        label, color = "High confidence", "green"
    elif divergence <= 0.40:
        label, color = "Moderate confidence", "yellow"
    else:
        label, color = "Low confidence — models disagree", "red"

    return {"label": label, "color": color, "divergence_pct": div_pct}


# ---------------------------------------------------------------------------
# 8. Swell energy proxy
# ---------------------------------------------------------------------------

def swell_energy(height_m: float | None, period_s: float | None) -> float | None:
    if not height_m or not period_s:
        return None
    return round(height_m ** 2 * period_s, 1)


# ---------------------------------------------------------------------------
# Top-level aggregator
# ---------------------------------------------------------------------------

def interpret_all(
    current: dict | None,
    today_hours: list[dict],
    sf_height_m: float | None,
    optimal_bearing: float | None,
    offshore_bearing: float | None,
) -> dict:
    c = current or {}

    wave_h = c.get("wave_height")
    wave_p = c.get("wave_period")
    wave_d = c.get("wave_direction")
    swell_h = c.get("swell_height")
    swell_p = c.get("swell_period")
    swell_d = c.get("swell_direction")
    swell_pk = c.get("swell_peak_period")
    swell2_h = c.get("swell2_height")
    swell2_p = c.get("swell2_period")
    swell2_d = c.get("swell2_direction")
    wind_wave_h = c.get("wind_wave_height")
    wind_spd = c.get("wind_speed")
    wind_dir = c.get("wind_direction")
    wind_gust = c.get("wind_gusts")
    air_t = c.get("air_temp")

    return {
        # Raw current values
        "wave_height": wave_h,
        "wave_period": wave_p,
        "wave_direction": wave_d,
        "swell_height": swell_h,
        "swell_period": swell_p,
        "swell_direction_deg": swell_d,
        "swell_peak_period": swell_pk,
        "swell2_height": swell2_h,
        "swell2_period": swell2_p,
        "swell2_direction_deg": swell2_d,
        "wind_wave_height": wind_wave_h,
        "wind_speed_kmh": wind_spd,
        "wind_direction_deg": wind_dir,
        "wind_gusts_kmh": wind_gust,
        "air_temp_c": air_t,
        # Interpretations
        "swell_purity":                swell_purity(wave_h, wind_wave_h),
        "swell_quality":               swell_quality(swell_p or wave_p),
        "direction_precision":         direction_precision(swell_d, optimal_bearing),
        "wind_assessment":             wind_assessment(wind_spd, wind_dir, offshore_bearing),
        "secondary_swell":             secondary_swell_interference(swell_h, swell2_h, swell_d, swell2_d),
        "best_hourly_window":          best_hourly_window(today_hours, optimal_bearing, offshore_bearing),
        "data_confidence":             data_confidence(swell_h, sf_height_m),
        "swell_energy":                swell_energy(swell_h or wave_h, swell_p or wave_p),
        "om_fetched_at":               c.get("timestamp_utc"),
    }
