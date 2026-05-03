"""Unified SF + Open-Meteo + GFS + IBI decision layer.

Pure merger helpers: no network, no filesystem, no UI concerns.
"""
import math
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from open_meteo_explainer import (
    _bearing_diff,
    _hour_score,
    hour_factor_scores,
    tide_suitability,
)


TIER_GOLD = "gold"
TIER_GREEN = "green"
TIER_YELLOW = "yellow"
TIER_RED = "red"

DECISION_GO = "go"
DECISION_MAYBE = "maybe"
DECISION_SKIP = "skip"

_KNOWN_VERDICTS = {DECISION_GO, DECISION_MAYBE, DECISION_SKIP}
_MISSING_VERDICTS = {None, "", "empty", "unknown"}

SF_WEIGHT = 0.25
SURFLINE_WEIGHT = 0.10
WINDGURU_WEIGHT = 0.05
OM_WEIGHT = 0.35
GFS_WEIGHT = 0.20
IBI_WEIGHT = 0.05
BASE_WEIGHTS = {
    "sf": SF_WEIGHT,
    "surfline": SURFLINE_WEIGHT,
    "windguru": WINDGURU_WEIGHT,
    "om": OM_WEIGHT,
    "gfs": GFS_WEIGHT,
    "ibi": IBI_WEIGHT,
}

SCORE_GOLD = 7.5
SCORE_GREEN = 6.2
SCORE_BEST_WINDOW = 5.0

_SF_HARD_GATE_LABELS = {"Height", "Period", "Tide"}
_SURFLINE_HARD_GATE_LABELS = set()
_WINDGURU_HARD_GATE_LABELS = set()
_OM_HARD_GATE_LABELS = set()
_GFS_HARD_GATE_LABELS = set()
_IBI_HARD_GATE_LABELS = set()

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

# Gold-star override: SF's full predictor stack flagged the cell as a strong
# local fit (right tide/direction/period for the break). The lifted floor lets
# small-but-clean conditions out-score plain-star larger surf.
_SF_QUALITY_CURVE_GOLD = {
    0: 0.0,
    1: 4.0,
    2: 5.5,
    3: 6.8,
    4: 7.5,
    5: 8.2,
    6: 8.8,
    7: 9.2,
    8: 9.6,
    9: 9.8,
    10: 10.0,
}

# Super-gold: both SF's local predictor AND a Surfline forecaster agree the cell
# fits the spot. LOTUS-only ratings can never reach this curve — only a human
# forecaster's GOOD/EPIC can authorize the lift.
_SF_QUALITY_CURVE_SUPER = {
    0: 0.0,
    1: 5.0,
    2: 6.5,
    3: 7.5,
    4: 8.0,
    5: 8.5,
    6: 9.0,
    7: 9.4,
    8: 9.7,
    9: 9.9,
    10: 10.0,
}

# Dampened: both forecasters signal poor local fit. Caps the ceiling so raw
# model numbers can't over-ride clear negative curation from both sources.
_SF_QUALITY_CURVE_DAMPENED = {
    0: 0.0,
    1: 1.5,
    2: 2.5,
    3: 3.5,
    4: 4.5,
    5: 5.5,
    6: 6.5,
    7: 7.5,
    8: 8.5,
    9: 9.0,
    10: 9.5,
}

# Map Surfline canonical labels to internal curation tiers.
_SURFLINE_TIER_FROM_LABEL = {
    "EPIC": "epic",
    "GOOD": "good",
    "FAIR TO GOOD": "fair_plus",
    "FAIR": "fair",
    "POOR TO FAIR": "neutral",
    "POOR": "poor",
    "VERY POOR": "poor",
}

# 2D curve lookup: (sf_is_gold, surfline_tier_after_downshift) -> curve.
# None tier falls through to the default gold/plain pick below.
_SURFLINE_CURVE_MAP = {
    (False, "epic"):      _SF_QUALITY_CURVE_SUPER,
    (True,  "epic"):      _SF_QUALITY_CURVE_SUPER,
    (False, "good"):      _SF_QUALITY_CURVE_GOLD,
    (True,  "good"):      _SF_QUALITY_CURVE_SUPER,
    (False, "fair_plus"): _SF_QUALITY_CURVE,
    (True,  "fair_plus"): _SF_QUALITY_CURVE_GOLD,
    (False, "fair"):      _SF_QUALITY_CURVE,
    (True,  "fair"):      _SF_QUALITY_CURVE_GOLD,
    (False, "neutral"):   _SF_QUALITY_CURVE,
    (True,  "neutral"):   _SF_QUALITY_CURVE_GOLD,
    (False, "poor"):      _SF_QUALITY_CURVE_DAMPENED,
    (True,  "poor"):      _SF_QUALITY_CURVE,
}

# LOTUS (model) ratings miss tide, swell direction, and spot dynamics.
# Down-shift model-sourced tiers by one level so LOTUS confirmations add a
# small lift but never authorize super-gold or gate-rescue.
_MODEL_DOWNSHIFT = {
    "epic": "good",      # guard: LOTUS can't produce EPIC, but handle gracefully
    "good": "fair_plus",
    "fair_plus": "fair",
    "fair": "neutral",
    "neutral": "neutral",
    "poor": "poor",
}


def _apply_surfline_downshift(tier, source):
    if tier is None or source != "model":
        return tier
    return _MODEL_DOWNSHIFT.get(tier, tier)


def _surfline_curation_tier(row):
    """Return (tier, source) from a Surfline current or hourly row.

    Current rows carry condition_rating + surfline_rating_source.
    Hourly rows carry surfline_optimal_score (always model, maxes at fair_plus).
    Returns (None, None) if no rating signal is present.
    """
    if not row:
        return None, None
    condition_rating = row.get("condition_rating")
    if condition_rating:
        label = str(condition_rating).upper().strip()
        tier = _SURFLINE_TIER_FROM_LABEL.get(label)
        source = row.get("surfline_rating_source") or "model"
        return tier, source
    score = row.get("surfline_optimal_score")
    if score is not None:
        s = int(score)
        if s >= 4:
            tier = "fair_plus"  # LOTUS model maxes at FAIR TO GOOD
        elif s == 3:
            tier = "fair"
        elif s == 2:
            tier = "neutral"
        else:
            tier = "poor"
        return tier, "model"
    return None, None


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


def _has_value(row, *keys):
    if not isinstance(row, dict):
        return False
    return any(row.get(key) is not None for key in keys)


def _has_wave_fields(row):
    return _has_value(row, "swell_height", "wave_height") and _has_value(row, "swell_period", "wave_period")


def _has_wind_fields(row):
    return _has_value(row, "wind_speed", "wind_speed_kmh") and _has_value(row, "wind_direction", "wind_direction_deg")


def _normalize_model_row(row):
    """Accept raw hourly rows or analysis dicts and return _hour_score keys."""
    row = row or {}
    swell_direction = row.get("swell_direction")
    if _to_float(swell_direction) is None and row.get("swell_direction_deg") is not None:
        swell_direction = row.get("swell_direction_deg")
    swell2_direction = row.get("swell2_direction")
    if _to_float(swell2_direction) is None and row.get("swell2_direction_deg") is not None:
        swell2_direction = row.get("swell2_direction_deg")
    wind_direction = row.get("wind_direction")
    if _to_float(wind_direction) is None and row.get("wind_direction_deg") is not None:
        wind_direction = row.get("wind_direction_deg")
    return {
        "timestamp_utc": (
            row.get("timestamp_utc")
            or row.get("surfline_fetched_at")
            or row.get("windguru_fetched_at")
            or row.get("om_fetched_at")
            or row.get("gfs_fetched_at")
            or row.get("ibi_fetched_at")
            or row.get("fetched_at")
        ),
        "wave_height": row.get("wave_height"),
        "wave_period": row.get("wave_period"),
        "wave_direction": row.get("wave_direction"),
        "swell_height": row.get("swell_height"),
        "swell_period": row.get("swell_period"),
        "swell_direction": swell_direction,
        "swell_peak_period": row.get("swell_peak_period"),
        "swell2_height": row.get("swell2_height"),
        "swell2_period": row.get("swell2_period"),
        "swell2_direction": swell2_direction,
        "wind_wave_height": row.get("wind_wave_height"),
        "wind_speed": row.get("wind_speed")
        if row.get("wind_speed") is not None
        else row.get("wind_speed_kmh"),
        "wind_direction": wind_direction,
        "wind_gusts": row.get("wind_gusts")
        if row.get("wind_gusts") is not None
        else row.get("wind_gusts_kmh"),
    }


def _available_sources(sf_score=None, om_score=None, gfs_score=None, ibi_score=None,
                       surfline_score=None, windguru_score=None):
    return {
        key for key, score in {
            "sf": sf_score,
            "surfline": surfline_score,
            "windguru": windguru_score,
            "om": om_score,
            "gfs": gfs_score,
            "ibi": ibi_score,
        }.items()
        if _clamp_score(score) is not None
    }


def _adaptive_weights(sf=None, om=None, gfs=None, ibi=None, available=None, tide_known=True,
                      surfline=None, windguru=None):
    """Return normalized per-hour weights after completeness nudges.

    Base shape stays conservative: SF 40%, OM 30%, and the independent model
    bucket split between GFS 20% and regional IBI 10%.
    """
    available = set(available or [])
    weights = {key: (BASE_WEIGHTS[key] if key in available else 0.0) for key in BASE_WEIGHTS}

    if "sf" in available:
        pass

    if "surfline" in available:
        if not _has_wave_fields(surfline):
            weights["surfline"] = max(0.0, weights["surfline"] - 0.10)

    if "windguru" in available:
        if not _has_wave_fields(windguru):
            weights["windguru"] = max(0.0, weights["windguru"] - 0.10)
        elif not _has_wind_fields(windguru):
            weights["windguru"] = max(0.0, weights["windguru"] - 0.05)

    if "om" in available:
        if _has_value(om, "wind_gusts", "wind_gusts_kmh"):
            weights["om"] += 0.05
        if _has_wind_fields(om):
            weights["om"] += 0.03
        if not _has_wave_fields(om):
            weights["om"] = max(0.0, weights["om"] - 0.10)

    if "gfs" in available:
        if _has_wave_fields(gfs) and _has_wind_fields(gfs):
            weights["gfs"] += 0.04
        elif not _has_wave_fields(gfs):
            weights["gfs"] = max(0.0, weights["gfs"] - 0.10)
        elif not _has_wind_fields(gfs):
            weights["gfs"] = max(0.0, weights["gfs"] - 0.05)

    if "ibi" in available:
        if _has_wind_fields(ibi):
            weights["ibi"] += 0.03
        else:
            weights["ibi"] = max(0.0, weights["ibi"] - 0.04)
        if not _has_wave_fields(ibi):
            weights["ibi"] = max(0.0, weights["ibi"] - 0.10)

    total = sum(weights.values())
    if total <= 0:
        return weights
    return {key: (weights[key] / total if key in available else 0.0) for key in weights}


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


def _sf_quality_score(rating, is_gold_star=False, surfline_tier=None, surfline_source=None):
    rating = _to_float(rating)
    if rating is None:
        return None
    rating = max(0.0, min(10.0, rating))
    effective_tier = _apply_surfline_downshift(surfline_tier, surfline_source)
    curve = _SURFLINE_CURVE_MAP.get((bool(is_gold_star), effective_tier))
    if curve is None:
        curve = _SF_QUALITY_CURVE_GOLD if is_gold_star else _SF_QUALITY_CURVE
    lower = int(rating)
    upper = min(10, lower + 1)
    if lower == upper or rating == lower:
        return curve[lower]
    return curve[lower] + (curve[upper] - curve[lower]) * (rating - lower)


def _blend_inputs(sf_score, om_score, ibi_score=None, gfs_score=None, weights=None,
                  surfline_score=None, windguru_score=None):
    """Build a {key: (score, weight)} dict, dropping None scores."""
    weights = weights or BASE_WEIGHTS
    raw = {
        "sf":  (_clamp_score(sf_score),  weights.get("sf", SF_WEIGHT)),
        "surfline": (_clamp_score(surfline_score), weights.get("surfline", SURFLINE_WEIGHT)),
        "windguru": (_clamp_score(windguru_score), weights.get("windguru", WINDGURU_WEIGHT)),
        "om":  (_clamp_score(om_score),  weights.get("om", OM_WEIGHT)),
        "gfs": (_clamp_score(gfs_score), weights.get("gfs", GFS_WEIGHT)),
        "ibi": (_clamp_score(ibi_score), weights.get("ibi", IBI_WEIGHT)),
    }
    return {k: v for k, v in raw.items() if v[0] is not None}


def _weighted_harmonic(sf_score, om_score, ibi_score=None,
                       sf_weight=SF_WEIGHT, om_weight=OM_WEIGHT, ibi_weight=IBI_WEIGHT,
                       gfs_score=None, gfs_weight=GFS_WEIGHT,
                       surfline_score=None, surfline_weight=SURFLINE_WEIGHT,
                       windguru_score=None, windguru_weight=WINDGURU_WEIGHT):
    """Weighted harmonic mean across available sources with pro-rata renormalization
    when a source is missing."""
    raw = {
        "sf":  (_clamp_score(sf_score),  sf_weight),
        "surfline": (_clamp_score(surfline_score), surfline_weight),
        "windguru": (_clamp_score(windguru_score), windguru_weight),
        "om":  (_clamp_score(om_score),  om_weight),
        "gfs": (_clamp_score(gfs_score), gfs_weight),
        "ibi": (_clamp_score(ibi_score), ibi_weight),
    }
    available = {k: v for k, v in raw.items() if v[0] is not None}
    if not available:
        return None
    if any(score <= 0 for score, _ in available.values()):
        return 0.0
    total_weight = sum(w for _, w in available.values())
    if total_weight <= 0:
        return None
    return 1.0 / sum((w / total_weight) / score for score, w in available.values())


def _weighted_geometric(sf_score, om_score, ibi_score=None,
                        sf_weight=SF_WEIGHT, om_weight=OM_WEIGHT, ibi_weight=IBI_WEIGHT,
                        gfs_score=None, gfs_weight=GFS_WEIGHT,
                        surfline_score=None, surfline_weight=SURFLINE_WEIGHT,
                        windguru_score=None, windguru_weight=WINDGURU_WEIGHT,
                        epsilon=0.05):
    """Weighted geometric mean across available 0-10 source scores.

    Scores are normalized to 0-1 before multiplication. A small epsilon keeps
    one noisy zero-valued source from mathematically erasing every other source;
    true vetoes are handled by hard gates.
    """
    raw = {
        "sf":  (_clamp_score(sf_score),  sf_weight),
        "surfline": (_clamp_score(surfline_score), surfline_weight),
        "windguru": (_clamp_score(windguru_score), windguru_weight),
        "om":  (_clamp_score(om_score),  om_weight),
        "gfs": (_clamp_score(gfs_score), gfs_weight),
        "ibi": (_clamp_score(ibi_score), ibi_weight),
    }
    available = {k: v for k, v in raw.items() if v[0] is not None}
    if not available:
        return None
    total_weight = sum(w for _, w in available.values())
    if total_weight <= 0:
        return None
    product = 1.0
    for score, weight in available.values():
        product *= max(score / 10.0, epsilon) ** (weight / total_weight)
    return _clamp_score(product * 10.0)


def _raw_variable_spread(rows):
    normalized = [
        _normalize_model_row(row)
        for row in rows or []
        if isinstance(row, dict) and row
    ]

    def spread_for(*keys):
        values = []
        for row in normalized:
            for key in keys:
                value = _to_float(row.get(key))
                if value is not None:
                    values.append(value)
                    break
        if len(values) < 2:
            return None
        return round(max(values) - min(values), 2)

    return {
        "height_m": spread_for("swell_height", "wave_height"),
        "period_s": spread_for("swell_period", "wave_period", "swell_peak_period"),
        "wind_speed_kmh": spread_for("wind_speed"),
        "wind_direction_deg": spread_for("wind_direction"),
    }


def _confidence_detail(sf_score, om_score, ibi_score=None, gfs_score=None, weights=None, rows=None,
                       surfline_score=None, windguru_score=None):
    inputs = _blend_inputs(
        sf_score, om_score, ibi_score, gfs_score, weights,
        surfline_score=surfline_score,
        windguru_score=windguru_score,
    )
    scores = [s for s, _ in inputs.values()]
    source_score_spread = round(max(scores) - min(scores), 2) if len(scores) >= 2 else 0.0
    raw_spread = _raw_variable_spread(rows or [])

    source_count_score = {
        0: 0.0,
        1: 0.45,
        2: 0.75,
        3: 0.82,
        4: 0.85,
    }.get(len(inputs), 0.85)
    spread_penalty = min(0.35, source_score_spread * 0.05)
    raw_penalty = 0.0
    height_spread = raw_spread.get("height_m")
    period_spread = raw_spread.get("period_s")
    wind_spread = raw_spread.get("wind_speed_kmh")
    direction_spread = raw_spread.get("wind_direction_deg")
    if height_spread is not None and height_spread > 0.4:
        raw_penalty += 0.05
    if period_spread is not None and period_spread > 3.0:
        raw_penalty += 0.05
    if wind_spread is not None and wind_spread > 10.0:
        raw_penalty += 0.05
    if direction_spread is not None and direction_spread > 60.0:
        raw_penalty += 0.05

    confidence_score = max(0.0, min(1.0, source_count_score - spread_penalty - raw_penalty))
    return {
        "source_count": len(inputs),
        "source_score_spread": source_score_spread,
        "missing_sources": [key for key in BASE_WEIGHTS if key not in inputs],
        "raw_variable_spread": raw_spread,
        "confidence_score_0_1": round(confidence_score, 2),
    }


def _confidence(sf_score, om_score, ibi_score=None, gfs_score=None, weights=None,
                surfline_score=None, windguru_score=None):
    detail = _confidence_detail(
        sf_score, om_score, ibi_score, gfs_score, weights,
        surfline_score=surfline_score,
        windguru_score=windguru_score,
    )
    inputs = _blend_inputs(
        sf_score, om_score, ibi_score, gfs_score, weights,
        surfline_score=surfline_score,
        windguru_score=windguru_score,
    )
    n = len(inputs)
    if n == 0:
        return "unknown"
    if n == 1:
        only = next(iter(inputs))
        return f"{only}_only"
    return "high" if detail["confidence_score_0_1"] >= 0.65 else "mixed"


def _consensus_score(sf_score, om_score, ibi_score=None, gfs_score=None,
                     surfline_score=None, windguru_score=None,
                     extra_penalty=0.0, weights=None):
    weights = weights or BASE_WEIGHTS
    base = _weighted_geometric(
        sf_score,
        om_score,
        ibi_score,
        sf_weight=weights.get("sf", SF_WEIGHT),
        surfline_score=surfline_score,
        surfline_weight=weights.get("surfline", SURFLINE_WEIGHT),
        windguru_score=windguru_score,
        windguru_weight=weights.get("windguru", WINDGURU_WEIGHT),
        om_weight=weights.get("om", OM_WEIGHT),
        ibi_weight=weights.get("ibi", IBI_WEIGHT),
        gfs_score=gfs_score,
        gfs_weight=weights.get("gfs", GFS_WEIGHT),
    )
    if base is None:
        return None
    return _clamp_score(base - (_to_float(extra_penalty) or 0.0))


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


def _score_model_row(row, spot, level, tide_color=None):
    if not row:
        return None
    normalized = _normalize_model_row(row)
    try:
        return _hour_score(
            normalized,
            spot.get("optimal_swell_bearing"),
            spot.get("offshore_bearing"),
            level=level,
            spot=spot,
            tide_color=tide_color,
        )
    except Exception:
        return None


def _model_factor_scores(row, spot, level, tide_color=None):
    if not row:
        return None
    try:
        factors = hour_factor_scores(
            _normalize_model_row(row),
            spot.get("optimal_swell_bearing"),
            spot.get("offshore_bearing"),
            level=level,
            spot=spot,
            tide_color=tide_color,
        )
    except Exception:
        return None
    return {
        key: (round(value, 3) if value is not None else None)
        for key, value in factors.items()
    }


def _apply_tide_to_score(score, tide_color):
    score = _clamp_score(score)
    if score is None:
        return None
    return _clamp_score(score * tide_suitability(tide_color))


def _current_om_score(om_analysis, spot, level, tide_color=None):
    if not _is_om_available(om_analysis):
        return None
    return _score_model_row(om_analysis, spot, level, tide_color=tide_color)


def _is_ibi_available(ibi_analysis):
    return isinstance(ibi_analysis, dict) and bool(ibi_analysis)


def _is_gfs_available(gfs_analysis):
    return isinstance(gfs_analysis, dict) and bool(gfs_analysis)


def _current_gfs_score(gfs_analysis, spot, level, tide_color=None):
    if not _is_gfs_available(gfs_analysis):
        return None
    return _score_model_row(gfs_analysis, spot, level, tide_color=tide_color)


def _is_surfline_available(surfline_analysis):
    return isinstance(surfline_analysis, dict) and bool(surfline_analysis)


def _current_surfline_score(surfline_analysis, spot, level, tide_color=None):
    if not _is_surfline_available(surfline_analysis):
        return None
    return _score_model_row(surfline_analysis, spot, level, tide_color=tide_color)


def _is_windguru_available(windguru_analysis):
    return isinstance(windguru_analysis, dict) and bool(windguru_analysis)


def _current_windguru_score(windguru_analysis, spot, level, tide_color=None):
    if not _is_windguru_available(windguru_analysis):
        return None
    return _score_model_row(windguru_analysis, spot, level, tide_color=tide_color)


def _score_ibi_hour_with_om_wind(ibi_row, om_row, spot, level="improver", tide_color=None):
    """Score IBI wave fields with OM wind fields when they line up in time."""
    if not ibi_row:
        return None
    ibi_like = _normalize_model_row(ibi_row)
    om_like = _normalize_model_row(om_row)
    fused = dict(ibi_like)
    if _has_wind_fields(om_like):
        fused["wind_speed"] = om_like.get("wind_speed")
        fused["wind_direction"] = om_like.get("wind_direction")
        fused["wind_gusts"] = om_like.get("wind_gusts")
    return _score_model_row(fused, spot, level, tide_color=tide_color)


def _current_ibi_score(ibi_analysis, spot, om_analysis=None, level="improver", tide_color=None):
    """IBI lacks wind data, so _hour_score will fall back to the neutral wind
    score (5.0). That's fine — IBI's contribution is wave/swell/direction."""
    if not _is_ibi_available(ibi_analysis):
        return None
    return _score_ibi_hour_with_om_wind(ibi_analysis, om_analysis, spot, level=level, tide_color=tide_color)


def _current_sf_score(sf_data, surfline_analysis=None):
    sf_data = sf_data or {}
    sl_tier, sl_source = _surfline_curation_tier(surfline_analysis) if surfline_analysis else (None, None)
    direct = _sf_quality_score(sf_data.get("rating"), surfline_tier=sl_tier, surfline_source=sl_source)
    if direct is not None:
        return direct
    now_dt = _parse_dt(sf_data.get("now_utc") or sf_data.get("fetched_at")) or datetime.now(timezone.utc)
    raw = _nearest_sf_rating(now_dt, _sf_cells(sf_data.get("rating_timeline", [])))
    return _sf_quality_score(raw, surfline_tier=sl_tier, surfline_source=sl_source)


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


def _model_severe_hard_gate(row, spot, source, level="improver"):
    normalized = _normalize_model_row(row)
    wave_h = _to_float(normalized.get("swell_height") or normalized.get("wave_height"))
    period = _to_float(normalized.get("swell_period") or normalized.get("wave_period"))

    if wave_h is not None and wave_h < 0.20:
        return {"blocked": True, "reason": "There is not enough ridable wave height right now.", "source": f"{source}_flat"}

    if wave_h is not None and period is not None:
        danger_power = {
            "beginner": 56.0,
            "improver": 88.0,
            "intermediate": 225.0,
            "advanced": 450.0,
        }.get(level, 88.0)
        if wave_h ** 2 * period >= danger_power:
            return {"blocked": True, "reason": "The waves are carrying too much power for this level.", "source": f"{source}_power"}

    return _om_hour_hard_gate(normalized, spot, source)


def _hard_gate(sf_data, om_analysis, ibi_analysis=None, gfs_analysis=None, spot=None, level="improver",
               surfline_analysis=None, windguru_analysis=None):
    sf_data = sf_data or {}
    om = om_analysis if isinstance(om_analysis, dict) else {}
    ibi = ibi_analysis if isinstance(ibi_analysis, dict) else {}
    gfs = gfs_analysis if isinstance(gfs_analysis, dict) else {}
    surfline = surfline_analysis if isinstance(surfline_analysis, dict) else {}
    windguru = windguru_analysis if isinstance(windguru_analysis, dict) else {}
    sf_reds = _red_detail_labels(sf_data.get("details"))
    surfline_reds = _red_detail_labels(surfline.get("surfline_details"))
    windguru_reds = _red_detail_labels(windguru.get("windguru_details"))
    om_reds = _red_detail_labels(om.get("om_details"))
    gfs_reds = _red_detail_labels(gfs.get("gfs_details"))
    ibi_reds = _red_detail_labels(ibi.get("ibi_details"))

    for label in sf_reds:
        if label in _SF_HARD_GATE_LABELS:
            return {"blocked": True, "reason": _label_reason(label), "source": f"sf_{label.lower()}"}

    for label in om_reds:
        if label in _OM_HARD_GATE_LABELS:
            return {"blocked": True, "reason": _label_reason(label), "source": f"om_{label.lower()}"}

    for label in surfline_reds:
        if label in _SURFLINE_HARD_GATE_LABELS:
            return {"blocked": True, "reason": _label_reason(label), "source": f"surfline_{label.lower()}"}

    for label in windguru_reds:
        if label in _WINDGURU_HARD_GATE_LABELS:
            return {"blocked": True, "reason": _label_reason(label), "source": f"windguru_{label.lower()}"}

    for label in gfs_reds:
        if label in _GFS_HARD_GATE_LABELS:
            return {"blocked": True, "reason": _label_reason(label), "source": f"gfs_{label.lower()}"}

    for label in ibi_reds:
        if label in _IBI_HARD_GATE_LABELS:
            return {"blocked": True, "reason": _label_reason(label), "source": f"ibi_{label.lower()}"}

    for source, analysis in (("surfline", surfline), ("windguru", windguru), ("om", om), ("gfs", gfs), ("ibi", ibi)):
        gate = _model_severe_hard_gate(analysis, spot or {}, source, level=level)
        if gate.get("blocked"):
            return gate

    sf = _normalize_verdict(sf_data.get("verdict"))
    if sf == DECISION_SKIP and not (sf_reds and all(label == "Direction" for label in sf_reds)):
        return {"blocked": True, "reason": "Conditions have a hard stop right now.", "source": "sf_verdict"}

    return {"blocked": False, "reason": None, "source": None}


def _direction_penalty(sf_data, om_analysis, ibi_analysis=None, gfs_analysis=None):
    sf_data = sf_data or {}
    om = om_analysis if isinstance(om_analysis, dict) else {}
    ibi = ibi_analysis if isinstance(ibi_analysis, dict) else {}
    gfs = gfs_analysis if isinstance(gfs_analysis, dict) else {}
    penalty = 0.0
    if "Direction" in _red_detail_labels(sf_data.get("details")):
        penalty += 0.9
    if "Direction" in _red_detail_labels(om.get("om_details")):
        penalty += 0.9
    if "Direction" in _red_detail_labels(gfs.get("gfs_details")):
        penalty += 0.8
    if "Direction" in _red_detail_labels(ibi.get("ibi_details")):
        penalty += 0.6
    return min(1.5, penalty)


def _om_hour_hard_gate(row, spot, source="om"):
    if not row:
        return {"blocked": False, "reason": None, "source": None}
    row = _normalize_model_row(row)
    wave_h = _to_float(row.get("swell_height") or row.get("wave_height")) or 0.0
    wind_h = _to_float(row.get("wind_wave_height")) or 0.0
    windsea_ratio = wind_h / wave_h if wave_h > 0 else 0.0
    if wave_h > 0 and windsea_ratio >= 0.65:
        return {"blocked": True, "reason": _label_reason("Shape"), "source": f"{source}_shape"}

    speed = _to_float(row.get("wind_speed"))
    wind_dir = _to_float(row.get("wind_direction"))
    offshore = _to_float((spot or {}).get("offshore_bearing"))
    if speed is not None and wind_dir is not None and offshore is not None:
        diff_from_offshore = _bearing_diff(wind_dir, offshore)
        onshore_component = 0.0
        if diff_from_offshore > 90:
            onshore_component = speed * max(0.0, math.cos(math.radians(180.0 - diff_from_offshore)))
        if diff_from_offshore > 150 and onshore_component >= 12.0 and windsea_ratio >= 0.45:
            return {"blocked": True, "reason": _label_reason("Wind"), "source": f"{source}_wind"}

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
            "penalty": 0.0,
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
    om_row = best.get("om_row") or best.get("gfs_row") or best.get("ibi_row")
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
        cells.append({
            "dt": dt,
            "rating": rating,
            "wind_speed_kmh": cell.get("wind_speed_kmh"),
            "wind_state": cell.get("wind_state"),
            "sf_star_state": cell.get("sf_star_state"),
            "sf_is_gold_star": bool(cell.get("sf_is_gold_star")),
        })
    return sorted(cells, key=lambda c: c["dt"])


def _nearest_sf_cell(target_dt, sf_cells):
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
    return best


def _nearest_sf_rating(target_dt, sf_cells):
    cell = _nearest_sf_cell(target_dt, sf_cells)
    return cell.get("rating") if cell else None


def _om_by_hour(om_hourly):
    rows = {}
    for row in om_hourly or []:
        dt = _parse_dt(row.get("timestamp_utc"))
        if dt is None:
            continue
        rows[_hour_key(dt)] = row
    return rows


def _score_om_hour(row, spot, level, tide_color=None):
    return _score_model_row(row, spot, level, tide_color=tide_color)


def _score_gfs_hour(row, spot, level, tide_color=None):
    return _score_model_row(row, spot, level, tide_color=tide_color)


def _score_hour(hour_dt, sf_cells, om_by_hour, spot, level="improver", tide_events=None, require_sf=False,
                gfs_by_hour=None, ibi_by_hour=None, surfline_by_hour=None, windguru_by_hour=None):
    sf_cell = _nearest_sf_cell(hour_dt, sf_cells)
    sf_raw = sf_cell.get("rating") if sf_cell else None
    sf_is_gold = bool(sf_cell.get("sf_is_gold_star")) if sf_cell else False
    tide_effect = _tide_window_effect(hour_dt, tide_events, spot)
    om_row = om_by_hour.get(_hour_key(hour_dt))
    surfline_row = (surfline_by_hour or {}).get(_hour_key(hour_dt))
    windguru_row = (windguru_by_hour or {}).get(_hour_key(hour_dt))
    gfs_row = (gfs_by_hour or {}).get(_hour_key(hour_dt))
    ibi_row = (ibi_by_hour or {}).get(_hour_key(hour_dt))
    sl_tier, sl_source = _surfline_curation_tier(surfline_row)
    sf_score = _apply_tide_to_score(
        _sf_quality_score(sf_raw, is_gold_star=sf_is_gold, surfline_tier=sl_tier, surfline_source=sl_source),
        tide_effect.get("color"),
    )
    om_score = _score_om_hour(om_row, spot, level, tide_color=tide_effect.get("color"))
    surfline_score = _score_model_row(surfline_row, spot, level, tide_color=tide_effect.get("color"))
    windguru_score = _score_model_row(windguru_row, spot, level, tide_color=tide_effect.get("color"))
    gfs_score = _score_gfs_hour(gfs_row, spot, level, tide_color=tide_effect.get("color"))
    ibi_score = _score_ibi_hour_with_om_wind(ibi_row, om_row, spot, level=level, tide_color=tide_effect.get("color"))
    if sf_score is None and surfline_score is None and windguru_score is None and om_score is None and gfs_score is None and ibi_score is None:
        return None
    hard_gate = _om_hour_hard_gate(om_row, spot, "om")
    surfline_gate = _om_hour_hard_gate(surfline_row, spot, "surfline")
    windguru_gate = _om_hour_hard_gate(windguru_row, spot, "windguru")
    gfs_gate = _om_hour_hard_gate(gfs_row, spot, "gfs")
    ibi_gate = _om_hour_hard_gate(ibi_row, spot, "ibi")
    tide_gate = tide_effect.get("gate") or {}
    blocked_by = []
    if hard_gate.get("blocked"):
        blocked_by.append(hard_gate.get("source") or "om_gate")
    if surfline_gate.get("blocked"):
        blocked_by.append(surfline_gate.get("source") or "surfline_gate")
        if not hard_gate.get("blocked"):
            hard_gate = surfline_gate
    if windguru_gate.get("blocked"):
        blocked_by.append(windguru_gate.get("source") or "windguru_gate")
        if not hard_gate.get("blocked"):
            hard_gate = windguru_gate
    if gfs_gate.get("blocked"):
        blocked_by.append(gfs_gate.get("source") or "gfs_gate")
        if not hard_gate.get("blocked"):
            hard_gate = gfs_gate
    if ibi_gate.get("blocked"):
        blocked_by.append(ibi_gate.get("source") or "ibi_gate")
        if not hard_gate.get("blocked"):
            hard_gate = ibi_gate
    if tide_gate.get("blocked"):
        blocked_by.append(tide_gate.get("source") or "sf_tide")
        if not hard_gate.get("blocked"):
            hard_gate = tide_gate
    # Gold-star, model corroboration, or a Surfline forecaster GOOD/EPIC overrides
    # a low SF rating. LOTUS-only Surfline tiers do NOT rescue — they miss tide and
    # spot dynamics, so they're not a trustworthy local-fit signal at our spots.
    surfline_forecaster_rescue = (
        sl_tier in ("good", "epic") and sl_source == "forecaster"
    )
    sf_low_rating = (
        require_sf
        and sf_raw is not None
        and sf_raw <= 2
        and not sf_is_gold
        and not surfline_forecaster_rescue
        and (om_score is None or om_score < 5.5)
    )
    if sf_low_rating:
        blocked_by.append("sf_low_rating")
    if require_sf and sf_score is None:
        blocked_by.append("sf_gap")
    if om_row is not None and om_score is None:
        blocked_by.append("om_gap")
    if surfline_row is not None and surfline_score is None:
        blocked_by.append("surfline_gap")
    if windguru_row is not None and windguru_score is None:
        blocked_by.append("windguru_gap")
    if gfs_row is not None and gfs_score is None:
        blocked_by.append("gfs_gap")
    if ibi_row is not None and ibi_score is None:
        blocked_by.append("ibi_gap")

    available = _available_sources(
        sf_score, om_score, gfs_score, ibi_score,
        surfline_score=surfline_score,
        windguru_score=windguru_score,
    )
    weights = _adaptive_weights(
        sf=sf_cell,
        surfline=_normalize_model_row(surfline_row) if surfline_row else None,
        windguru=_normalize_model_row(windguru_row) if windguru_row else None,
        om=_normalize_model_row(om_row) if om_row else None,
        gfs=_normalize_model_row(gfs_row) if gfs_row else None,
        ibi=_normalize_model_row(ibi_row) if ibi_row else None,
        available=available,
        tide_known=bool(tide_events),
    )

    decider_score = _consensus_score(
        sf_score,
        om_score,
        ibi_score,
        surfline_score=surfline_score,
        windguru_score=windguru_score,
        gfs_score=gfs_score,
        weights=weights,
    )
    window_eligible = (
        not (require_sf and sf_score is None)
        and not sf_low_rating
        and not (om_row is not None and om_score is None)
        and not (surfline_row is not None and surfline_score is None)
        and not (windguru_row is not None and windguru_score is None)
        and not (gfs_row is not None and gfs_score is None)
        and not (ibi_row is not None and ibi_score is None)
    )
    tier = _tier_for_score(decider_score, hard_gate, has_om=bool(available - {"sf"}))
    return {
        "dt": hour_dt,
        "sf_raw_rating": sf_raw,
        "sf_score": sf_score,
        "surfline_score": surfline_score,
        "windguru_score": windguru_score,
        "om_score": om_score,
        "gfs_score": gfs_score,
        "ibi_score": ibi_score,
        "om_row": om_row,
        "surfline_row": surfline_row,
        "windguru_row": windguru_row,
        "gfs_row": gfs_row,
        "ibi_row": ibi_row,
        "decider_score": decider_score,
        "combined": decider_score,
        "tier": tier,
        "has_hard_gate": bool(hard_gate.get("blocked")),
        "hard_gate": hard_gate,
        "blocked_by": blocked_by,
        "confidence": _confidence(
            sf_score, om_score, ibi_score, gfs_score=gfs_score, weights=weights,
            surfline_score=surfline_score,
            windguru_score=windguru_score,
        ),
        "confidence_detail": _confidence_detail(
            sf_score,
            om_score,
            ibi_score,
            gfs_score=gfs_score,
            weights=weights,
            surfline_score=surfline_score,
            windguru_score=windguru_score,
            rows=[row for row in (surfline_row, windguru_row, om_row, gfs_row, ibi_row) if row],
        ),
        "weights": weights,
        "factor_scores": {
            "om": _model_factor_scores(om_row, spot, level, tide_color=tide_effect.get("color")),
            "surfline": _model_factor_scores(surfline_row, spot, level, tide_color=tide_effect.get("color")),
            "windguru": _model_factor_scores(windguru_row, spot, level, tide_color=tide_effect.get("color")),
            "gfs": _model_factor_scores(gfs_row, spot, level, tide_color=tide_effect.get("color")),
            "ibi": _model_factor_scores(ibi_row, spot, level, tide_color=tide_effect.get("color")),
            "tide": tide_suitability(tide_effect.get("color")),
        },
        "tide": {
            "color": tide_effect.get("color"),
            **(tide_effect.get("tide") or {}),
        },
        "window_eligible": window_eligible,
        "step_hours": 1,
    }


def _score_sf_cell(cell, tide_events=None, spot=None):
    tide_effect = _tide_window_effect(cell["dt"], tide_events, spot)
    sf_score = _apply_tide_to_score(_sf_quality_score(cell["rating"]), tide_effect.get("color"))
    hard_gate = tide_effect.get("gate") or {"blocked": False, "reason": None, "source": None}
    score = _consensus_score(sf_score, None)
    blocked_by = []
    if hard_gate.get("blocked"):
        blocked_by.append(hard_gate.get("source") or "sf_tide")
    return {
        "dt": cell["dt"],
        "sf_raw_rating": cell["rating"],
        "sf_score": sf_score,
        "surfline_score": None,
        "windguru_score": None,
        "om_score": None,
        "gfs_score": None,
        "ibi_score": None,
        "om_row": None,
        "surfline_row": None,
        "windguru_row": None,
        "gfs_row": None,
        "ibi_row": None,
        "decider_score": score,
        "combined": score,
        "tier": _tier_for_score(score, hard_gate=hard_gate, has_om=False),
        "has_hard_gate": bool(hard_gate.get("blocked")),
        "hard_gate": hard_gate,
        "blocked_by": blocked_by,
        "confidence": "sf_only",
        "confidence_detail": _confidence_detail(sf_score, None, None),
        "weights": {"sf": 1.0, "surfline": 0.0, "windguru": 0.0, "om": 0.0, "gfs": 0.0, "ibi": 0.0},
        "factor_scores": {
            "sf": {"tide": tide_suitability(tide_effect.get("color"))},
            "tide": tide_suitability(tide_effect.get("color")),
        },
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
            -round(item["score"], 6),
            -_block_duration_hours(item["block"]),
            item["block"][0]["dt"],
        )
    )
    return candidates[0]["block"]


def _top_windows(scored_hours, predicate, now_dt, spot, limit=5, min_hours=2, max_hours=4):
    candidates = _session_candidates(scored_hours, predicate, min_hours, max_hours)
    if not candidates:
        return []
    candidates.sort(
        key=lambda item: (
            -round(item["score"], 6),
            -_block_duration_hours(item["block"]),
            item["block"][0]["dt"],
        )
    )
    selected = []
    used_buckets = set()
    for cand in candidates:
        block = cand["block"]
        start_local = _local_dt(block[0]["dt"], spot)
        bucket = (start_local.date(), "AM" if start_local.hour < 13 else "PM")
        if bucket in used_buckets:
            continue
        used_buckets.add(bucket)
        selected.append(block)
        if len(selected) >= limit:
            break
    selected.sort(key=lambda block: block[0]["dt"])
    return selected


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


def _window_confidence_detail(block):
    details = [row.get("confidence_detail") for row in block if isinstance(row.get("confidence_detail"), dict)]
    if not details:
        return None
    raw_keys = set()
    for detail in details:
        raw_keys.update((detail.get("raw_variable_spread") or {}).keys())
    return {
        "source_count": min(detail.get("source_count", 0) for detail in details),
        "source_score_spread": round(max(detail.get("source_score_spread", 0.0) for detail in details), 2),
        "missing_sources": sorted({source for detail in details for source in detail.get("missing_sources", [])}),
        "raw_variable_spread": {
            key: max(
                (
                    (detail.get("raw_variable_spread") or {}).get(key)
                    for detail in details
                    if (detail.get("raw_variable_spread") or {}).get(key) is not None
                ),
                default=None,
            )
            for key in sorted(raw_keys)
        },
        "confidence_score_0_1": round(min(detail.get("confidence_score_0_1", 0.0) for detail in details), 2),
    }


def _score_components(block):
    components = []
    for row in block:
        tide = row.get("tide") or {}
        components.append({
            "starts_at": _iso(row.get("dt")),
            "score": round(row["decider_score"], 1) if row.get("decider_score") is not None else None,
            "sf_raw_rating": row.get("sf_raw_rating"),
            "sf_score": round(row["sf_score"], 1) if row.get("sf_score") is not None else None,
            "surfline_score": round(row["surfline_score"], 1) if row.get("surfline_score") is not None else None,
            "windguru_score": round(row["windguru_score"], 1) if row.get("windguru_score") is not None else None,
            "om_score": round(row["om_score"], 1) if row.get("om_score") is not None else None,
            "gfs_score": round(row["gfs_score"], 1) if row.get("gfs_score") is not None else None,
            "ibi_score": round(row["ibi_score"], 1) if row.get("ibi_score") is not None else None,
            "tide": tide.get("color"),
            "factor_scores": row.get("factor_scores"),
            "confidence_detail": row.get("confidence_detail"),
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
        "tier": _tier_for_score(
            score,
            has_om=any(
                row.get("om_score") is not None
                or row.get("surfline_score") is not None
                or row.get("windguru_score") is not None
                or row.get("gfs_score") is not None
                or row.get("ibi_score") is not None
                for row in block
            ),
        ),
        "reason": _window_reason(block, spot),
        "confidence": _window_confidence(block),
        "confidence_detail": _window_confidence_detail(block),
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


def find_next_windows(rating_timeline, om_hourly, spot, sf_now_utc, tide=None,
                      gfs_hourly=None, ibi_hourly=None, level="improver",
                      surfline_hourly=None, windguru_hourly=None):
    now_dt = _parse_dt(sf_now_utc) or datetime.now(timezone.utc)
    cutoff = now_dt + timedelta(days=7)
    spot = spot or {}
    sf_cells = _sf_cells(rating_timeline)
    om_hours = _om_by_hour(om_hourly)
    surfline_hours = _om_by_hour(surfline_hourly)
    windguru_hours = _om_by_hour(windguru_hourly)
    gfs_hours = _om_by_hour(gfs_hourly)
    ibi_hours = _om_by_hour(ibi_hourly)
    tide_events = tide.get("events") if isinstance(tide, dict) else tide

    scored = []
    model_hours = sorted(set(surfline_hours) | set(windguru_hours) | set(om_hours) | set(gfs_hours) | set(ibi_hours))
    if model_hours:
        require_sf = bool(sf_cells)
        for hour_dt in model_hours:
            if hour_dt < now_dt.replace(minute=0, second=0, microsecond=0):
                continue
            if hour_dt > cutoff:
                continue
            local_hour = _local_dt(hour_dt, spot).hour
            if local_hour >= 20 or local_hour < 5:
                continue
            row = _score_hour(
                hour_dt,
                sf_cells,
                om_hours,
                spot,
                level=level,
                tide_events=tide_events,
                require_sf=require_sf,
                surfline_by_hour=surfline_hours,
                windguru_by_hour=windguru_hours,
                gfs_by_hour=gfs_hours,
                ibi_by_hour=ibi_hours,
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
            local_hour = _local_dt(cell["dt"], spot).hour
            if local_hour >= 20 or local_hour < 5:
                continue
            scored.append(_score_sf_cell(cell, tide_events=tide_events, spot=spot))

    scored.sort(key=lambda row: row["dt"])
    if not scored:
        return {
            "now_tier": TIER_YELLOW,
            "best_window": None,
            "next_decent_window": None,
            "next_gold_window": None,
            "top_windows": [],
            "gold_count_7d": 0,
            "current_window_ends": None,
        }

    top_blocks = _top_windows(scored, _hour_is_decent, now_dt, spot, limit=5, min_hours=2, max_hours=4)
    top_windows = [_window_payload(block, now_dt, spot) for block in top_blocks]
    best_window = top_windows[0] if top_windows else None
    gold_block = _best_session(scored, _hour_is_gold, min_hours=2, max_hours=4)

    return {
        "now_tier": _now_tier(scored, now_dt),
        "best_window": best_window,
        "next_decent_window": best_window,
        "next_gold_window": _window_payload(gold_block, now_dt, spot),
        "top_windows": top_windows,
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


def unify(
    sf_data,
    om_analysis,
    om_hourly,
    spot,
    level,
    ibi_analysis=None,
    gfs_analysis=None,
    gfs_hourly=None,
    ibi_hourly=None,
    surfline_analysis=None,
    surfline_hourly=None,
    windguru_analysis=None,
    windguru_hourly=None,
):
    sf_data = sf_data or {}
    spot = spot or {}
    try:
        now_dt = _parse_dt(sf_data.get("now_utc") or sf_data.get("fetched_at")) or datetime.now(timezone.utc)
        tide_data = sf_data.get("tide")
        tide_events = tide_data.get("events") if isinstance(tide_data, dict) else tide_data
        tide_effect = _tide_window_effect(now_dt, tide_events, spot)
        tide_color = tide_effect.get("color")
        sf_score = _apply_tide_to_score(_current_sf_score(sf_data, surfline_analysis=surfline_analysis), tide_color)
        surfline_score = _current_surfline_score(surfline_analysis, spot, level, tide_color=tide_color)
        windguru_score = _current_windguru_score(windguru_analysis, spot, level, tide_color=tide_color)
        om_score = _current_om_score(om_analysis, spot, level, tide_color=tide_color)
        gfs_score = _current_gfs_score(gfs_analysis, spot, level, tide_color=tide_color)
        ibi_score = _current_ibi_score(ibi_analysis, spot, om_analysis, level=level, tide_color=tide_color)
        hard_gate = _hard_gate(
            sf_data,
            om_analysis,
            ibi_analysis,
            gfs_analysis,
            spot=spot,
            level=level,
            surfline_analysis=surfline_analysis,
            windguru_analysis=windguru_analysis,
        )
        tide_gate = tide_effect.get("gate") or {}
        if tide_gate.get("blocked") and not hard_gate.get("blocked"):
            hard_gate = tide_gate
        available = _available_sources(
            sf_score, om_score, gfs_score, ibi_score,
            surfline_score=surfline_score,
            windguru_score=windguru_score,
        )
        weights = _adaptive_weights(
            sf=sf_data,
            surfline=_normalize_model_row(surfline_analysis) if surfline_analysis else None,
            windguru=_normalize_model_row(windguru_analysis) if windguru_analysis else None,
            om=_normalize_model_row(om_analysis) if om_analysis else None,
            gfs=_normalize_model_row(gfs_analysis) if gfs_analysis else None,
            ibi=_normalize_model_row(ibi_analysis) if ibi_analysis else None,
            available=available,
            tide_known=bool((sf_data.get("tide") or {}).get("events")),
        )
        score = _consensus_score(
            sf_score,
            om_score,
            ibi_score,
            surfline_score=surfline_score,
            windguru_score=windguru_score,
            gfs_score=gfs_score,
            weights=weights,
        )
        confidence = _confidence(
            sf_score,
            om_score,
            ibi_score,
            gfs_score=gfs_score,
            weights=weights,
            surfline_score=surfline_score,
            windguru_score=windguru_score,
        )
        confidence_detail = _confidence_detail(
            sf_score,
            om_score,
            ibi_score,
            gfs_score=gfs_score,
            weights=weights,
            surfline_score=surfline_score,
            windguru_score=windguru_score,
            rows=[
                row
                for row in (
                    _normalize_model_row(surfline_analysis) if surfline_analysis else None,
                    _normalize_model_row(windguru_analysis) if windguru_analysis else None,
                    _normalize_model_row(om_analysis) if om_analysis else None,
                    _normalize_model_row(gfs_analysis) if gfs_analysis else None,
                    _normalize_model_row(ibi_analysis) if ibi_analysis else None,
                )
                if row
            ],
        )

        tier = _tier_for_score(score, hard_gate, has_om=bool(available - {"sf"}))
        decision = _decision_for_tier(tier)
        windows = find_next_windows(
            sf_data.get("rating_timeline", []),
            om_hourly or [],
            spot,
            sf_data.get("now_utc") or sf_data.get("fetched_at"),
            tide=sf_data.get("tide"),
            gfs_hourly=gfs_hourly or [],
            ibi_hourly=ibi_hourly or [],
            surfline_hourly=surfline_hourly or [],
            windguru_hourly=windguru_hourly or [],
            level=level,
        )
        reason = _decision_reason(
            sf_data,
            om_analysis,
            hard_gate,
            score,
            best_window=windows.get("best_window"),
        )

        sources_used = sorted(_blend_inputs(
            sf_score,
            om_score,
            ibi_score,
            gfs_score,
            weights,
            surfline_score=surfline_score,
            windguru_score=windguru_score,
        ).keys())

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
            "top_windows": windows.get("top_windows", []),
            "gold_count_7d": windows.get("gold_count_7d", 0),
            "score": round(score, 1) if score is not None else None,
            "confidence": confidence,
            "confidence_detail": confidence_detail,
            "decision_reason": reason,
            "level": level,
            "sources_used": sources_used,
            "source_scores": {
                "sf":  round(sf_score, 1)  if sf_score  is not None else None,
                "surfline": round(surfline_score, 1) if surfline_score is not None else None,
                "windguru": round(windguru_score, 1) if windguru_score is not None else None,
                "om":  round(om_score, 1)  if om_score  is not None else None,
                "gfs": round(gfs_score, 1) if gfs_score is not None else None,
                "ibi": round(ibi_score, 1) if ibi_score is not None else None,
            },
            "weights": weights,
            "factor_scores": {
                "surfline": _model_factor_scores(surfline_analysis, spot, level, tide_color=tide_color),
                "windguru": _model_factor_scores(windguru_analysis, spot, level, tide_color=tide_color),
                "om": _model_factor_scores(om_analysis, spot, level, tide_color=tide_color),
                "gfs": _model_factor_scores(gfs_analysis, spot, level, tide_color=tide_color),
                "ibi": _model_factor_scores(ibi_analysis, spot, level, tide_color=tide_color),
                "tide": tide_suitability(tide_color),
            },
            "hard_gate_detail": hard_gate,
            "scoring_model": "doctrine_v2_geometric_suitability",
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
            "top_windows": [],
            "gold_count_7d": 0,
            "score": None,
            "confidence": "unknown",
            "confidence_detail": {
                "source_count": 0,
                "source_score_spread": 0.0,
                "missing_sources": list(BASE_WEIGHTS),
                "raw_variable_spread": {},
                "confidence_score_0_1": 0.0,
            },
            "decision_reason": "There is not enough clean data to make a confident call.",
            "level": level,
            "sources_used": [],
            "source_scores": {"sf": None, "surfline": None, "windguru": None, "om": None, "gfs": None, "ibi": None},
            "weights": {"sf": 0.0, "surfline": 0.0, "windguru": 0.0, "om": 0.0, "gfs": 0.0, "ibi": 0.0},
            "factor_scores": {},
            "hard_gate_detail": {"blocked": False, "reason": None, "source": None},
            "scoring_model": "doctrine_v2_geometric_suitability",
        }
