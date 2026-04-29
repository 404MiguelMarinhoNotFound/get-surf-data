"""Unified SF + Open-Meteo decision layer.

Pure merger helpers: no network, no filesystem, no UI concerns.
"""
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from open_meteo_explainer import _bearing_diff, _hour_score


TIER_GOLD = "gold"
TIER_GREEN = "green"
TIER_YELLOW = "yellow"
TIER_RED = "red"

DECISION_GO = "go"
DECISION_MAYBE = "maybe"
DECISION_SKIP = "skip"

_KNOWN_VERDICTS = {DECISION_GO, DECISION_MAYBE, DECISION_SKIP}
_MISSING_VERDICTS = {None, "", "empty", "unknown"}

SF_WEIGHT = 0.60
OM_WEIGHT = 0.40

SCORE_GOLD = 7.5
SCORE_GREEN = 6.2
SCORE_BEST_WINDOW = 5.0

_SF_HARD_GATE_LABELS = {"Height", "Period", "Tide"}
_OM_HARD_GATE_LABELS = {"Wind", "Shape"}

_SF_QUALITY_CURVE = {
    0: 0.0,
    1: 2.0,
    2: 3.5,
    3: 4.8,
    4: 5.8,
    5: 6.8,
    6: 7.6,
    7: 8.4,
    8: 9.0,
    9: 9.5,
    10: 10.0,
}


def _last_sunday(year, month):
    day = datetime(year, month, 28)
    while day.weekday() != 6:
        day += timedelta(days=1)
    while (day + timedelta(days=7)).month == month:
        day += timedelta(days=7)
    return day


def _eu_western_offset(dt_utc):
    year = dt_utc.year
    start = datetime(year, 3, _last_sunday(year, 3).day, 1, tzinfo=timezone.utc)
    end = datetime(year, 10, _last_sunday(year, 10).day, 1, tzinfo=timezone.utc)
    return timedelta(hours=1 if start <= dt_utc < end else 0)


_FALLBACK_TZ_RULES = {
    "Europe/Lisbon": _eu_western_offset,
    "Europe/London": _eu_western_offset,
    "Atlantic/Faroe": _eu_western_offset,
}


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_verdict(value):
    if value is None:
        return None
    value = str(value).strip().lower()
    if value in _KNOWN_VERDICTS:
        return value
    if value in _MISSING_VERDICTS:
        return None
    return None


def _clamp_score(value):
    value = _to_float(value)
    if value is None:
        return None
    return max(0.0, min(10.0, value))


def _sf_quality_score(rating):
    rating = _to_float(rating)
    if rating is None:
        return None
    rating = max(0.0, min(10.0, rating))
    lower = int(rating)
    upper = min(10, lower + 1)
    if lower == upper or rating == lower:
        return _SF_QUALITY_CURVE[lower]
    lower_score = _SF_QUALITY_CURVE[lower]
    upper_score = _SF_QUALITY_CURVE[upper]
    return lower_score + (upper_score - lower_score) * (rating - lower)


def _weighted_harmonic(sf_score, om_score, sf_weight=SF_WEIGHT, om_weight=OM_WEIGHT):
    sf_score = _clamp_score(sf_score)
    om_score = _clamp_score(om_score)
    if sf_score is None and om_score is None:
        return None
    if sf_score is None:
        return om_score
    if om_score is None:
        return sf_score
    if sf_score <= 0 or om_score <= 0:
        return 0.0
    return 1.0 / ((sf_weight / sf_score) + (om_weight / om_score))


def _confidence(sf_score, om_score):
    sf_score = _clamp_score(sf_score)
    om_score = _clamp_score(om_score)
    if sf_score is None and om_score is None:
        return "unknown"
    if sf_score is None:
        return "om_only"
    if om_score is None:
        return "sf_only"
    return "high" if abs(sf_score - om_score) <= 1.5 else "mixed"


def _consensus_score(sf_score, om_score, extra_penalty=0.0):
    base = _weighted_harmonic(sf_score, om_score)
    if base is None:
        return None
    sf_score = _clamp_score(sf_score)
    om_score = _clamp_score(om_score)
    penalty = 0.0
    if sf_score is not None and om_score is not None:
        penalty = min(1.0, abs(sf_score - om_score) * 0.12)
    penalty += _to_float(extra_penalty) or 0.0
    return _clamp_score(base - penalty)


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _hour_key(dt):
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _is_om_available(om_analysis):
    return isinstance(om_analysis, dict) and bool(om_analysis)


def _current_om_score(om_analysis, spot):
    if not _is_om_available(om_analysis):
        return None
    current_like = {
        "wave_height": om_analysis.get("wave_height"),
        "wave_period": om_analysis.get("wave_period"),
        "wave_direction": om_analysis.get("wave_direction"),
        "swell_height": om_analysis.get("swell_height"),
        "swell_period": om_analysis.get("swell_period"),
        "swell_direction": om_analysis.get("swell_direction_deg"),
        "wind_wave_height": om_analysis.get("wind_wave_height"),
        "wind_speed": om_analysis.get("wind_speed_kmh"),
        "wind_direction": om_analysis.get("wind_direction_deg"),
    }
    try:
        return _hour_score(
            current_like,
            spot.get("optimal_swell_bearing"),
            spot.get("offshore_bearing"),
        )
    except Exception:
        return None


def _current_sf_score(sf_data):
    sf_data = sf_data or {}
    direct = _sf_quality_score(sf_data.get("rating"))
    if direct is not None:
        return direct
    now_dt = _parse_dt(sf_data.get("now_utc") or sf_data.get("fetched_at")) or datetime.now(timezone.utc)
    raw = _nearest_sf_rating(now_dt, _sf_cells(sf_data.get("rating_timeline", [])))
    return _sf_quality_score(raw)


def _has_compromised_om_grade(om_analysis):
    if not _is_om_available(om_analysis):
        return True
    for detail in om_analysis.get("om_details") or []:
        if detail.get("color") in ("yellow", "red"):
            return True
    return False


def _red_detail_labels(details):
    labels = []
    for detail in details or []:
        if detail.get("color") == "red" and detail.get("label"):
            labels.append(str(detail["label"]))
    return labels


def _label_reason(label):
    reasons = {
        "Height": "The size is outside the safe range for your level.",
        "Period": "The waves are carrying too much power for this level.",
        "Tide": "The tide window is not working for this break right now.",
        "Wind": "Wind is adding too much chop right now.",
        "Shape": "The wave shape is too messy right now.",
    }
    return reasons.get(label, "Conditions have a hard stop right now.")


def _hard_gate(sf_data, om_analysis):
    sf_data = sf_data or {}
    om = om_analysis if isinstance(om_analysis, dict) else {}
    sf_reds = _red_detail_labels(sf_data.get("details"))
    om_reds = _red_detail_labels(om.get("om_details"))

    for label in sf_reds:
        if label in _SF_HARD_GATE_LABELS:
            return {"blocked": True, "reason": _label_reason(label), "source": f"sf_{label.lower()}"}

    for label in om_reds:
        if label in _OM_HARD_GATE_LABELS:
            return {"blocked": True, "reason": _label_reason(label), "source": f"om_{label.lower()}"}

    sf = _normalize_verdict(sf_data.get("verdict"))
    om_verdict = _normalize_verdict(om.get("om_verdict"))
    if sf == DECISION_SKIP and not (sf_reds and all(label == "Direction" for label in sf_reds)):
        return {"blocked": True, "reason": "Conditions have a hard stop right now.", "source": "sf_verdict"}
    if om_verdict == DECISION_SKIP and not (om_reds and all(label == "Direction" for label in om_reds)):
        return {"blocked": True, "reason": "Conditions have a hard stop right now.", "source": "om_verdict"}

    return {"blocked": False, "reason": None, "source": None}


def _direction_penalty(sf_data, om_analysis):
    sf_data = sf_data or {}
    om = om_analysis if isinstance(om_analysis, dict) else {}
    penalty = 0.0
    if "Direction" in _red_detail_labels(sf_data.get("details")):
        penalty += 0.9
    if "Direction" in _red_detail_labels(om.get("om_details")):
        penalty += 0.9
    return min(1.5, penalty)


def _om_hour_hard_gate(row, spot):
    if not row:
        return {"blocked": False, "reason": None, "source": None}
    wave_h = _to_float(row.get("swell_height") or row.get("wave_height")) or 0.0
    wind_h = _to_float(row.get("wind_wave_height")) or 0.0
    if wave_h > 0 and wind_h / wave_h > 0.50:
        return {"blocked": True, "reason": _label_reason("Shape"), "source": "om_shape"}

    speed = _to_float(row.get("wind_speed"))
    wind_dir = _to_float(row.get("wind_direction"))
    offshore = _to_float((spot or {}).get("offshore_bearing"))
    if speed is not None and wind_dir is not None and offshore is not None:
        if speed >= 5 and _bearing_diff(wind_dir, offshore) > 150:
            return {"blocked": True, "reason": _label_reason("Wind"), "source": "om_wind"}

    return {"blocked": False, "reason": None, "source": None}


def _tide_state_at(dt, tide_events):
    if not dt or not tide_events:
        return None

    parsed = []
    for event in tide_events:
        event_dt = _parse_dt(event.get("time"))
        height = _to_float(event.get("height_m"))
        kind = event.get("type")
        if event_dt is None or height is None or kind not in ("high", "low"):
            continue
        parsed.append((event_dt, kind, height))

    parsed.sort(key=lambda item: item[0])
    if len(parsed) < 2:
        return None

    previous_event = None
    next_event = None
    for event in parsed:
        if event[0] <= dt:
            previous_event = event
        elif next_event is None:
            next_event = event
            break

    if previous_event is None or next_event is None:
        return None

    prev_dt, _prev_kind, prev_h = previous_event
    next_dt, next_kind, next_h = next_event
    total_seconds = max(1.0, (next_dt - prev_dt).total_seconds())
    elapsed_seconds = min(max(0.0, (dt - prev_dt).total_seconds()), total_seconds)
    progress = elapsed_seconds / total_seconds
    height_m = prev_h + (next_h - prev_h) * progress
    state = "rising" if next_h > prev_h else "falling"
    low_h = min(prev_h, next_h)
    high_h = max(prev_h, next_h)
    tide_range = high_h - low_h
    position = 0.5 if tide_range <= 0 else (height_m - low_h) / tide_range

    return {
        "height_m": round(height_m, 2),
        "state": state,
        "position": round(position, 2),
        "next_type": next_kind,
        "minutes_to_next_turn": int(round((next_dt - dt).total_seconds() / 60)),
    }


def _tide_window_effect(dt, tide_events, spot):
    tide = _tide_state_at(dt, tide_events)
    window = str((spot or {}).get("tide_window") or "").lower()
    neutral = {
        "color": None,
        "penalty": 0.0,
        "gate": {"blocked": False, "reason": None, "source": None},
        "tide": tide,
    }

    if not tide or not window or window in ("any", "all"):
        return neutral

    state = tide.get("state")
    position = tide.get("position")
    next_type = tide.get("next_type")
    minutes = tide.get("minutes_to_next_turn")
    color = None

    if position is None or state not in ("rising", "falling"):
        return neutral

    if window == "mid-to-high":
        if state == "rising" and 0.35 <= position <= 0.90:
            color = "green"
        elif state == "rising" and position < 0.35:
            color = "yellow" if next_type == "high" and minutes is not None and minutes <= 90 else "red"
        elif state == "falling" and position >= 0.55:
            color = "yellow"
        elif position > 0.90:
            color = "yellow"
        else:
            color = "red"
    elif window == "low-to-mid":
        if position <= 0.60:
            color = "green"
        elif position <= 0.80:
            color = "yellow"
        else:
            color = "red"
    else:
        return neutral

    if color == "red":
        return {
            "color": color,
            "penalty": 0.0,
            "gate": {"blocked": True, "reason": _label_reason("Tide"), "source": "sf_tide"},
            "tide": tide,
        }
    if color == "yellow":
        return {
            "color": color,
            "penalty": 0.6,
            "gate": {"blocked": False, "reason": None, "source": "sf_tide"},
            "tide": tide,
        }
    return {**neutral, "color": color}


def _resolve_decision(sf_verdict, om_verdict):
    sf = _normalize_verdict(sf_verdict)
    om = _normalize_verdict(om_verdict)

    if sf is None and om is None:
        return (
            DECISION_MAYBE,
            "unknown",
            "Not enough data to make a confident call.",
        )

    if om is None:
        if sf == DECISION_GO:
            decision = DECISION_GO
        elif sf == DECISION_SKIP:
            decision = DECISION_SKIP
        else:
            decision = DECISION_MAYBE
        return (
            decision,
            "sf_only",
            "Open-Meteo is unavailable, so this uses surf-forecast only.",
        )

    if sf is None:
        if om == DECISION_GO:
            decision = DECISION_GO
        elif om == DECISION_SKIP:
            decision = DECISION_SKIP
        else:
            decision = DECISION_MAYBE
        return (
            decision,
            "om_only",
            "Surf-forecast is unavailable, so this uses Open-Meteo only.",
        )

    table = {
        (DECISION_GO, DECISION_GO): (
            DECISION_GO,
            "agree",
            "Both forecasts agree (high confidence).",
        ),
        (DECISION_GO, DECISION_SKIP): (
            DECISION_SKIP,
            "disagree",
            "Open-Meteo sees a wind or wave-shape problem surf-forecast missed.",
        ),
        (DECISION_SKIP, DECISION_GO): (
            DECISION_SKIP,
            "disagree",
            "Surf-forecast sees a tide or local-break problem Open-Meteo cannot detect.",
        ),
        (DECISION_SKIP, DECISION_SKIP): (
            DECISION_SKIP,
            "agree",
            "Both forecasts agree: wait for a better window.",
        ),
        (DECISION_MAYBE, DECISION_GO): (
            DECISION_GO,
            "mixed",
            "Open-Meteo's detail clarifies the marginal surf-forecast call.",
        ),
        (DECISION_MAYBE, DECISION_SKIP): (
            DECISION_SKIP,
            "mixed",
            "Open-Meteo confirms the doubt: wait for a better window.",
        ),
        (DECISION_GO, DECISION_MAYBE): (
            DECISION_GO,
            "mixed",
            "Mostly positive, but one forecast has a caution flag.",
        ),
        (DECISION_SKIP, DECISION_MAYBE): (
            DECISION_SKIP,
            "mixed",
            "Surf-forecast has a hard stop, so the unified call stays conservative.",
        ),
        (DECISION_MAYBE, DECISION_MAYBE): (
            DECISION_MAYBE,
            "agree",
            "Both forecasts are cautious: check the details before going.",
        ),
    }
    return table.get(
        (sf, om),
        (DECISION_MAYBE, "unknown", "Not enough data to make a confident call."),
    )


def _tier_for_score(score, hard_gate=None, has_om=True):
    if hard_gate and hard_gate.get("blocked"):
        return TIER_RED
    score = _to_float(score)
    if score is None:
        return TIER_YELLOW
    if has_om and score >= SCORE_GOLD:
        return TIER_GOLD
    if score >= SCORE_GREEN:
        return TIER_GREEN
    if score >= SCORE_BEST_WINDOW:
        return TIER_YELLOW
    return TIER_RED


def _decision_for_tier(tier):
    if tier in (TIER_GOLD, TIER_GREEN):
        return DECISION_GO
    if tier == TIER_YELLOW:
        return DECISION_MAYBE
    return DECISION_SKIP


def _headline(tier, decision=None):
    if tier == TIER_GOLD:
        return "GOLD WINDOW - GO NOW"
    if tier == TIER_GREEN:
        return "GO NOW"
    if tier == TIER_YELLOW:
        return "WAIT FOR A BETTER WINDOW"
    if tier == TIER_RED:
        return "SKIP NOW"
    return "WAIT FOR A BETTER WINDOW"


def plain_height(h_m):
    h = _to_float(h_m)
    if h is None:
        return "unknown-size"
    if h < 0.4:
        return "ankle-high"
    if h < 0.7:
        return "knee-high"
    if h < 1.1:
        return "waist-high"
    if h < 1.5:
        return "chest-high"
    if h < 2.0:
        return "head-high"
    if h < 3.0:
        return "overhead"
    return "well overhead, big"


def plain_period(p_s):
    p = _to_float(p_s)
    if p is None:
        return "unknown-power waves"
    if p < 8:
        return "weak short waves"
    if p < 12:
        return "decent waves"
    if p <= 15:
        return "powerful waves"
    return "very powerful waves (advanced only)"


def plain_wind(speed_kmh, wind_dir_deg, offshore_bearing):
    speed = _to_float(speed_kmh)
    wind_dir = _to_float(wind_dir_deg)
    offshore = _to_float(offshore_bearing)

    if speed is None:
        speed_phrase = "unknown wind"
    elif speed < 5:
        speed_phrase = "no wind, glassy"
    elif speed <= 12:
        speed_phrase = "light wind"
    elif speed <= 22:
        speed_phrase = "breezy wind"
    elif speed <= 35:
        speed_phrase = "windy conditions"
    else:
        speed_phrase = "very windy conditions"

    if wind_dir is None or offshore is None:
        return speed_phrase

    diff = _bearing_diff(wind_dir, offshore)
    if diff <= 60:
        suffix = "from land - cleans the waves"
    elif diff <= 120:
        suffix = "sideways - adds chop"
    else:
        suffix = "from sea - kills the waves"
    return f"{speed_phrase} {suffix}"


def _window_wind_phrase(row, spot):
    speed = _to_float(row.get("wind_speed"))
    wind_dir = _to_float(row.get("wind_direction"))
    offshore = _to_float((spot or {}).get("offshore_bearing"))
    if speed is None:
        return None
    if speed < 5:
        return "glassy wind"
    if wind_dir is None or offshore is None:
        if speed <= 22:
            return "manageable wind"
        return None
    diff = _bearing_diff(wind_dir, offshore)
    if diff <= 60 and speed <= 22:
        return "clean wind"
    if diff <= 120 and speed <= 22:
        return "manageable wind"
    return None


def _window_period_phrase(period_s):
    period = _to_float(period_s)
    if period is None:
        return None
    if period < 8:
        return "weak waves"
    if period < 12:
        return "decent waves"
    return "powerful waves"


def _window_shape_phrase(row):
    wave_h = _to_float(row.get("swell_height") or row.get("wave_height"))
    wind_h = _to_float(row.get("wind_wave_height"))
    if wave_h is None or wave_h <= 0 or wind_h is None:
        return None
    ratio = wind_h / wave_h
    if ratio < 0.25:
        return "clean shape"
    if ratio <= 0.50:
        return "a bit mixed"
    return None


def _window_reason(block, spot):
    if not block:
        return "Best available window in the next 7 days."

    best = max(
        block,
        key=lambda row: _to_float(row.get("decider_score")) if _to_float(row.get("decider_score")) is not None else -1,
    )
    om_row = best.get("om_row")
    if not om_row:
        if best.get("sf_raw_rating") is not None:
            return "Strongest local window available."
        return "Best available window in the next 7 days."

    swell_h = (
        om_row.get("swell_height")
        if om_row.get("swell_height") is not None
        else om_row.get("wave_height")
    )
    period = (
        om_row.get("swell_period")
        if om_row.get("swell_period") is not None
        else om_row.get("wave_period")
    )
    wind = _window_wind_phrase(om_row, spot)
    height = plain_height(swell_h) if _to_float(swell_h) is not None else None
    power = _window_period_phrase(period)
    shape = _window_shape_phrase(om_row)

    swell_dir = _to_float(om_row.get("swell_direction"))
    optimal = _to_float((spot or {}).get("optimal_swell_bearing"))
    poor_direction = (
        swell_dir is not None
        and optimal is not None
        and _bearing_diff(swell_dir, optimal) > 90
    )
    if poor_direction:
        return "Best available, but not perfectly lined up."

    if wind and height and power:
        return f"{wind.capitalize()} + {height} {power}."
    if wind and height:
        return f"{wind.capitalize()} + {height} waves."
    if shape == "clean shape" and height and power:
        return f"Clean shape + {height} {power}."
    if shape and height:
        return f"{shape.capitalize()} + {height} waves."
    if shape == "clean shape" and power:
        return f"Clean shape and {power}."
    if _to_float(best.get("decider_score")) is not None and best.get("decider_score") >= SCORE_BEST_WINDOW:
        return "Best available, but still a compromise."
    return "Best available window in the next 7 days."


def plain_summary(om_analysis, sf_data, spot, level):
    sf_data = sf_data or {}
    spot = spot or {}
    om = om_analysis if isinstance(om_analysis, dict) else {}

    height = (
        om.get("swell_height")
        if om.get("swell_height") is not None
        else om.get("wave_height")
    )
    if height is None:
        height = sf_data.get("height_m")

    period = (
        om.get("swell_period")
        if om.get("swell_period") is not None
        else om.get("wave_period")
    )
    if period is None:
        period = sf_data.get("period_s")

    if om.get("wind_speed_kmh") is not None:
        wind = plain_wind(
            om.get("wind_speed_kmh"),
            om.get("wind_direction_deg"),
            spot.get("offshore_bearing"),
        )
    else:
        wind_state = sf_data.get("wind_state")
        wind = f"{wind_state} wind" if wind_state else "unknown wind"

    text = f"{plain_height(height).capitalize()} {plain_period(period)} with {wind}."
    return text


def _sf_cells(rating_timeline):
    cells = []
    for cell in rating_timeline or []:
        dt = _parse_dt(cell.get("timestamp_utc"))
        rating = _to_float(cell.get("rating"))
        if dt is None or rating is None:
            continue
        cells.append({"dt": dt, "rating": rating})
    return sorted(cells, key=lambda c: c["dt"])


def _nearest_sf_rating(target_dt, sf_cells):
    if not target_dt or not sf_cells:
        return None
    best = None
    best_seconds = None
    for cell in sf_cells:
        diff = abs((cell["dt"] - target_dt).total_seconds())
        if best_seconds is None or diff < best_seconds:
            best = cell
            best_seconds = diff
    if best is None or best_seconds is None or best_seconds > 90 * 60:
        return None
    return best["rating"]


def _om_by_hour(om_hourly):
    rows = {}
    for row in om_hourly or []:
        dt = _parse_dt(row.get("timestamp_utc"))
        if dt is None:
            continue
        rows[_hour_key(dt)] = row
    return rows


def _score_om_hour(row, spot):
    if not row:
        return None
    try:
        return _hour_score(
            row,
            spot.get("optimal_swell_bearing"),
            spot.get("offshore_bearing"),
        )
    except Exception:
        return None


def _score_hour(hour_dt, sf_cells, om_by_hour, spot, tide_events=None, require_sf=False):
    sf_raw = _nearest_sf_rating(hour_dt, sf_cells)
    sf_score = _sf_quality_score(sf_raw)
    om_row = om_by_hour.get(_hour_key(hour_dt))
    om_score = _score_om_hour(om_row, spot)
    if sf_score is None and om_score is None:
        return None
    hard_gate = _om_hour_hard_gate(om_row, spot)
    tide_effect = _tide_window_effect(hour_dt, tide_events, spot)
    tide_gate = tide_effect.get("gate") or {}
    blocked_by = []
    if hard_gate.get("blocked"):
        blocked_by.append(hard_gate.get("source") or "om_gate")
    if tide_gate.get("blocked"):
        blocked_by.append(tide_gate.get("source") or "sf_tide")
        if not hard_gate.get("blocked"):
            hard_gate = tide_gate
    if require_sf and sf_score is None:
        blocked_by.append("sf_gap")
    if om_row is not None and om_score is None:
        blocked_by.append("om_gap")

    decider_score = _consensus_score(
        sf_score,
        om_score,
        extra_penalty=tide_effect.get("penalty", 0.0),
    )
    window_eligible = not (require_sf and sf_score is None) and not (om_row is not None and om_score is None)
    tier = _tier_for_score(decider_score, hard_gate, has_om=om_score is not None)
    return {
        "dt": hour_dt,
        "sf_raw_rating": sf_raw,
        "sf_score": sf_score,
        "om_score": om_score,
        "om_row": om_row,
        "decider_score": decider_score,
        "combined": decider_score,
        "tier": tier,
        "has_hard_gate": bool(hard_gate.get("blocked")),
        "hard_gate": hard_gate,
        "blocked_by": blocked_by,
        "confidence": _confidence(sf_score, om_score),
        "tide": {
            "color": tide_effect.get("color"),
            **(tide_effect.get("tide") or {}),
        },
        "window_eligible": window_eligible,
        "step_hours": 1,
    }


def _score_sf_cell(cell, tide_events=None, spot=None):
    sf_score = _sf_quality_score(cell["rating"])
    tide_effect = _tide_window_effect(cell["dt"], tide_events, spot)
    hard_gate = tide_effect.get("gate") or {"blocked": False, "reason": None, "source": None}
    score = _consensus_score(sf_score, None, extra_penalty=tide_effect.get("penalty", 0.0))
    blocked_by = []
    if hard_gate.get("blocked"):
        blocked_by.append(hard_gate.get("source") or "sf_tide")
    return {
        "dt": cell["dt"],
        "sf_raw_rating": cell["rating"],
        "sf_score": sf_score,
        "om_score": None,
        "om_row": None,
        "decider_score": score,
        "combined": score,
        "tier": _tier_for_score(score, hard_gate=hard_gate, has_om=False),
        "has_hard_gate": bool(hard_gate.get("blocked")),
        "hard_gate": hard_gate,
        "blocked_by": blocked_by,
        "confidence": "sf_only",
        "tide": {
            "color": tide_effect.get("color"),
            **(tide_effect.get("tide") or {}),
        },
        "window_eligible": True,
        "step_hours": 3,
    }


def _hour_is_gold(row):
    return (
        row.get("tier") == TIER_GOLD
        and not row.get("has_hard_gate")
        and row.get("window_eligible", True)
    )


def _hour_is_green(row):
    return (
        row.get("tier") in (TIER_GOLD, TIER_GREEN)
        and not row.get("has_hard_gate")
        and row.get("window_eligible", True)
    )


def _hour_is_decent(row):
    return (
        not row.get("has_hard_gate")
        and row.get("window_eligible", True)
        and row.get("decider_score") is not None
        and row.get("decider_score") >= SCORE_BEST_WINDOW
    )


def _classify_hour(sf_score, om_score):
    score = _consensus_score(sf_score, om_score)
    return _tier_for_score(score, has_om=om_score is not None)


def _continuous(prev, current):
    prev_end = prev["dt"] + timedelta(hours=prev.get("step_hours", 1))
    return prev_end == current["dt"]


def _block_duration_hours(block):
    if not block:
        return 0
    return int((block[-1]["dt"] + timedelta(hours=block[-1].get("step_hours", 1)) - block[0]["dt"]).total_seconds() / 3600)


def _harmonic_mean(values):
    scores = [_to_float(value) for value in values]
    if not scores or any(score is None for score in scores):
        return None
    if any(score <= 0 for score in scores):
        return 0.0
    return len(scores) / sum(1.0 / score for score in scores)


def _session_candidates(scored_hours, predicate, min_hours=2, max_hours=4):
    candidates = []
    run = []

    def flush_run(rows):
        for start_idx in range(len(rows)):
            block = []
            for row in rows[start_idx:]:
                if block and not _continuous(block[-1], row):
                    break
                block.append(row)
                duration = _block_duration_hours(block)
                if duration > max_hours:
                    break
                if duration >= min_hours:
                    score = _harmonic_mean(row["decider_score"] for row in block)
                    if score is not None:
                        candidates.append({"block": list(block), "score": score})

    for row in scored_hours:
        if predicate(row):
            if run and not _continuous(run[-1], row):
                flush_run(run)
                run = []
            run.append(row)
        else:
            flush_run(run)
            run = []

    flush_run(run)
    return candidates


def _best_session(scored_hours, predicate, min_hours=2, max_hours=4):
    candidates = _session_candidates(scored_hours, predicate, min_hours, max_hours)
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            -item["score"],
            item["block"][0]["dt"],
            -_block_duration_hours(item["block"]),
        )
    )
    return candidates[0]["block"]


def _count_blocks(scored_hours, predicate, min_hours=2):
    count = 0
    block = []
    for row in scored_hours:
        if predicate(row):
            if block and not _continuous(block[-1], row):
                if _block_duration_hours(block) >= min_hours:
                    count += 1
                block = []
            block.append(row)
        else:
            if _block_duration_hours(block) >= min_hours:
                count += 1
            block = []
    if _block_duration_hours(block) >= min_hours:
        count += 1
    return count


def _spot_tzinfo(spot, dt=None):
    tz_name = (spot or {}).get("tz")
    if tz_name and ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    rule = _FALLBACK_TZ_RULES.get(tz_name)
    if rule is not None:
        dt_utc = dt or datetime.now(timezone.utc)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        else:
            dt_utc = dt_utc.astimezone(timezone.utc)
        return timezone(rule(dt_utc), tz_name)
    return timezone.utc


def _local_dt(dt, spot):
    return dt.astimezone(_spot_tzinfo(spot, dt))


def _label_window(start_dt, end_dt, now_dt, spot=None):
    start_local = _local_dt(start_dt, spot)
    end_local = _local_dt(end_dt, spot)
    now_local = _local_dt(now_dt, spot)
    if start_local.date() == now_local.date():
        prefix = "Today"
    elif start_local.date() == (now_local + timedelta(days=1)).date():
        prefix = "Tomorrow"
    else:
        prefix = start_local.strftime("%A")
    end_label = end_local.strftime("%H:%M")
    if end_local.date() != start_local.date():
        end_label = end_local.strftime("%a %H:%M")
    return f"{prefix} {start_local.strftime('%H:%M')}-{end_label}"


def _window_confidence(block):
    values = {row.get("confidence") for row in block if row.get("confidence")}
    if not values:
        return "unknown"
    if values == {"high"}:
        return "high"
    if "mixed" in values:
        return "mixed"
    if len(values) == 1:
        return next(iter(values))
    return "mixed"


def _score_components(block):
    components = []
    for row in block:
        tide = row.get("tide") or {}
        components.append({
            "starts_at": _iso(row.get("dt")),
            "score": round(row["decider_score"], 1) if row.get("decider_score") is not None else None,
            "sf_raw_rating": row.get("sf_raw_rating"),
            "sf_score": round(row["sf_score"], 1) if row.get("sf_score") is not None else None,
            "om_score": round(row["om_score"], 1) if row.get("om_score") is not None else None,
            "tide": tide.get("color"),
        })
    return components


def _window_payload(block, now_dt, spot):
    if not block:
        return None
    start = block[0]["dt"]
    end = block[-1]["dt"] + timedelta(hours=block[-1].get("step_hours", 1))
    score = _harmonic_mean(row["decider_score"] for row in block)
    hours_away = max(0, round((start - now_dt).total_seconds() / 3600))
    blocked_by = sorted({item for row in block for item in row.get("blocked_by", []) if item})
    return {
        "starts_at": _iso(start),
        "ends_at": _iso(end),
        "label": _label_window(start, end, now_dt, spot),
        "hours_away": hours_away,
        "score": round(score, 1) if score is not None else None,
        "tier": _tier_for_score(score, has_om=any(row.get("om_score") is not None for row in block)),
        "reason": _window_reason(block, spot),
        "confidence": _window_confidence(block),
        "score_components": _score_components(block),
        "blocked_by": blocked_by,
    }


def _current_window_end(scored_hours, now_dt):
    current = None
    for idx, row in enumerate(scored_hours):
        row_end = row["dt"] + timedelta(hours=row.get("step_hours", 1))
        if row["dt"] <= now_dt < row_end:
            current = idx
            break
    if current is None:
        return None

    current_row = scored_hours[current]
    if not _hour_is_green(current_row):
        return None

    end = current_row["dt"] + timedelta(hours=current_row.get("step_hours", 1))
    for row in scored_hours[current + 1:]:
        if not _continuous({"dt": end, "step_hours": 0}, row):
            break
        if not _hour_is_green(row):
            break
        end = row["dt"] + timedelta(hours=row.get("step_hours", 1))
    return _iso(end)


def _now_tier(scored_hours, now_dt):
    for row in scored_hours:
        row_end = row["dt"] + timedelta(hours=row.get("step_hours", 1))
        if row["dt"] <= now_dt < row_end:
            return row.get("tier") or TIER_YELLOW
    return TIER_YELLOW


def find_next_windows(rating_timeline, om_hourly, spot, sf_now_utc, tide=None):
    now_dt = _parse_dt(sf_now_utc) or datetime.now(timezone.utc)
    cutoff = now_dt + timedelta(days=7)
    spot = spot or {}
    sf_cells = _sf_cells(rating_timeline)
    om_hours = _om_by_hour(om_hourly)
    tide_events = tide.get("events") if isinstance(tide, dict) else tide

    scored = []
    if om_hours:
        require_sf = bool(sf_cells)
        for hour_dt in sorted(om_hours):
            if hour_dt < now_dt.replace(minute=0, second=0, microsecond=0):
                continue
            if hour_dt > cutoff:
                continue
            row = _score_hour(
                hour_dt,
                sf_cells,
                om_hours,
                spot,
                tide_events=tide_events,
                require_sf=require_sf,
            )
            if row is not None:
                scored.append(row)
    elif sf_cells:
        for cell in sf_cells:
            cell_end = cell["dt"] + timedelta(hours=3)
            if cell_end <= now_dt:
                continue
            if cell["dt"] > cutoff:
                continue
            scored.append(_score_sf_cell(cell, tide_events=tide_events, spot=spot))

    scored.sort(key=lambda row: row["dt"])
    if not scored:
        return {
            "now_tier": TIER_YELLOW,
            "best_window": None,
            "next_decent_window": None,
            "next_gold_window": None,
            "gold_count_7d": 0,
            "current_window_ends": None,
        }

    best_block = _best_session(scored, _hour_is_decent, min_hours=2, max_hours=4)
    gold_block = _best_session(scored, _hour_is_gold, min_hours=2, max_hours=4)
    best_window = _window_payload(best_block, now_dt, spot)

    return {
        "now_tier": _now_tier(scored, now_dt),
        "best_window": best_window,
        "next_decent_window": best_window,
        "next_gold_window": _window_payload(gold_block, now_dt, spot),
        "gold_count_7d": _count_blocks(scored, _hour_is_gold, min_hours=2),
        "current_window_ends": _current_window_end(scored, now_dt),
    }


def _decision_reason(sf_data, om_analysis, hard_gate, score, best_window=None):
    if hard_gate and hard_gate.get("blocked"):
        return hard_gate.get("reason") or "Conditions have a hard stop right now."
    score = _to_float(score)
    if score is None:
        return "There is not enough clean data to make a confident call."
    if score >= SCORE_GOLD:
        return "Everything lines up cleanly for your level."
    if score >= SCORE_GREEN:
        return "Conditions line up cleanly enough for your level."
    if score >= SCORE_BEST_WINDOW:
        return "The safer call is to wait for the cleaner window."
    if best_window:
        return "The best window is later when conditions improve."
    return "Conditions are not lining up well enough right now."


def unify(sf_data, om_analysis, om_hourly, spot, level):
    sf_data = sf_data or {}
    spot = spot or {}
    try:
        sf_score = _current_sf_score(sf_data)
        om_score = _current_om_score(om_analysis, spot)
        hard_gate = _hard_gate(sf_data, om_analysis)
        score = _consensus_score(
            sf_score,
            om_score,
            extra_penalty=_direction_penalty(sf_data, om_analysis),
        )
        confidence = _confidence(sf_score, om_score)
        tier = _tier_for_score(score, hard_gate, has_om=om_score is not None)
        decision = _decision_for_tier(tier)
        windows = find_next_windows(
            sf_data.get("rating_timeline", []),
            om_hourly or [],
            spot,
            sf_data.get("now_utc") or sf_data.get("fetched_at"),
            tide=sf_data.get("tide"),
        )
        reason = _decision_reason(
            sf_data,
            om_analysis,
            hard_gate,
            score,
            best_window=windows.get("best_window"),
        )

        return {
            "tier": tier,
            "decision": decision,
            "decision_headline": _headline(tier, decision),
            "plain_summary": plain_summary(om_analysis, sf_data, spot, level),
            "agreement": confidence,
            "agreement_note": reason,
            "current_window_ends": windows.get("current_window_ends"),
            "best_window": windows.get("best_window"),
            "next_decent_window": windows.get("next_decent_window"),
            "next_gold_window": windows.get("next_gold_window"),
            "gold_count_7d": windows.get("gold_count_7d", 0),
            "score": round(score, 1) if score is not None else None,
            "confidence": confidence,
            "decision_reason": reason,
            "level": level,
        }
    except Exception:
        return {
            "tier": TIER_YELLOW,
            "decision": DECISION_MAYBE,
            "decision_headline": "WAIT FOR A BETTER WINDOW",
            "plain_summary": plain_summary(None, sf_data, spot, level),
            "agreement": "unknown",
            "agreement_note": "Not enough data to make a confident call.",
            "current_window_ends": None,
            "best_window": None,
            "next_decent_window": None,
            "next_gold_window": None,
            "gold_count_7d": 0,
            "score": None,
            "confidence": "unknown",
            "decision_reason": "There is not enough clean data to make a confident call.",
            "level": level,
        }
