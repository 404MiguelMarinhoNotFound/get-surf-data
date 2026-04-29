"""
Copernicus IBI scorer.

IBI returns the same field names as Open-Meteo (wave_height, swell_period,
swell_direction, ...), so we reuse open_meteo_explainer's per-hour scoring and
graders directly. This module is just a thin wrapper that produces an analysis
dict shaped like open_meteo_explainer.interpret_all() — symmetric so the
unifier can blend it without special-casing.

IBI does NOT provide wind data via our WMS path, so wind grades default to
"unknown" (Open-Meteo handles wind authoritatively).
"""
from open_meteo_explainer import (
    DEFAULT_LEVEL,
    _normalize_level,
    grade_height_om,
    grade_period_om,
    grade_direction_om,
    grade_swell_shape,
    om_verdict,
    swell_purity,
    swell_quality,
    direction_precision,
    swell_energy,
)


def interpret_all(
    current,
    optimal_bearing=None,
    offshore_bearing=None,
    optimal_label=None,
    level=DEFAULT_LEVEL,
):
    level = _normalize_level(level)
    c = current or {}

    wave_h    = c.get("wave_height")
    wave_p    = c.get("wave_period")
    swell_h   = c.get("swell_height")
    swell_p   = c.get("swell_period")
    swell_d   = c.get("swell_direction")
    wind_wave_h = c.get("wind_wave_height")

    height_grade    = grade_height_om(swell_h or wave_h, level)
    period_grade    = grade_period_om(swell_p or wave_p, level)
    shape_grade     = grade_swell_shape(swell_h, None, None, swell_d, wind_wave_h, wave_h)
    direction_grade = grade_direction_om(swell_d, optimal_bearing, optimal_label)

    grades = [
        ("Height",    height_grade),
        ("Period",    period_grade),
        ("Shape",     shape_grade),
        ("Direction", direction_grade),
    ]

    verdict = om_verdict(grades, level)

    return {
        "wave_height":         wave_h,
        "wave_period":         wave_p,
        "swell_height":        swell_h,
        "swell_period":        swell_p,
        "swell_direction_deg": swell_d,
        "wind_wave_height":    wind_wave_h,
        "ibi_verdict":         verdict["om_verdict"],
        "ibi_verdict_text":    verdict["om_verdict_text"].replace("(Open-Meteo)", "(Copernicus IBI)"),
        "ibi_details":         verdict["om_details"],
        "swell_purity":        swell_purity(wave_h, wind_wave_h),
        "swell_quality":       swell_quality(swell_p or wave_p),
        "direction_precision": direction_precision(swell_d, optimal_bearing),
        "swell_energy":        swell_energy(swell_h or wave_h, swell_p or wave_p),
        "ibi_fetched_at":      c.get("timestamp_utc"),
    }
