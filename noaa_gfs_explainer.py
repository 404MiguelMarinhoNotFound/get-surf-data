"""NOAA GFS Wave + Wind scorer.

Thin wrapper on open_meteo_explainer graders. Unlike IBI, GFS provides full
wind data (speed + direction), so wind grades are fully populated. Produces
an analysis dict shaped like open_meteo_explainer.interpret_all() so the
unifier can blend it without special-casing.
"""
from open_meteo_explainer import (
    DEFAULT_LEVEL,
    _normalize_level,
    grade_height_om,
    grade_period_om,
    grade_wind_om,
    grade_direction_om,
    grade_swell_shape,
    om_verdict,
    swell_purity,
    swell_quality,
    direction_precision,
    swell_energy,
    wind_assessment,
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

    wave_h      = c.get("wave_height")
    wave_p      = c.get("wave_period")
    swell_h     = c.get("swell_height")
    swell_p     = c.get("swell_period")
    swell_d     = c.get("swell_direction")
    wind_wave_h = c.get("wind_wave_height")
    wind_spd    = c.get("wind_speed")
    wind_dir    = c.get("wind_direction")
    wind_gust   = c.get("wind_gusts")
    swell2_h    = c.get("swell2_height")
    swell2_p    = c.get("swell2_period")
    swell2_d    = c.get("swell2_direction")

    height_grade    = grade_height_om(swell_h or wave_h, level)
    period_grade    = grade_period_om(swell_p or wave_p, level)
    wind_grade      = grade_wind_om(wind_spd, wind_dir, offshore_bearing, level)
    shape_grade     = grade_swell_shape(swell_h, swell2_h, swell2_d, swell_d, wind_wave_h, wave_h)
    direction_grade = grade_direction_om(swell_d, optimal_bearing, optimal_label)

    grades = [
        ("Height",    height_grade),
        ("Period",    period_grade),
        ("Wind",      wind_grade),
        ("Shape",     shape_grade),
        ("Direction", direction_grade),
    ]

    verdict = om_verdict(grades, level)

    return {
        "wave_height":          wave_h,
        "wave_period":          wave_p,
        "swell_height":         swell_h,
        "swell_period":         swell_p,
        "swell_direction_deg":  swell_d,
        "swell2_height":        swell2_h,
        "swell2_period":        swell2_p,
        "swell2_direction_deg": swell2_d,
        "wind_wave_height":     wind_wave_h,
        "wind_speed_kmh":       wind_spd,
        "wind_direction_deg":   wind_dir,
        "wind_gusts_kmh":       wind_gust,
        "gfs_verdict":          verdict["om_verdict"],
        "gfs_verdict_text":     verdict["om_verdict_text"].replace("(Open-Meteo)", "(NOAA GFS)"),
        "gfs_details":          verdict["om_details"],
        "swell_purity":         swell_purity(wave_h, wind_wave_h),
        "swell_quality":        swell_quality(swell_p or wave_p),
        "direction_precision":  direction_precision(swell_d, optimal_bearing),
        "wind_assessment":      wind_assessment(wind_spd, wind_dir, offshore_bearing),
        "swell_energy":         swell_energy(swell_h or wave_h, swell_p or wave_p),
        "gfs_fetched_at":       c.get("timestamp_utc"),
    }
