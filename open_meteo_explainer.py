"""
Surf-quality interpretation engine driven by Open-Meteo Marine data.

Mirrors the structure of explainer.py but with richer inputs:
- Exact wind speed (km/h) and direction (degrees), not just "offshore"
- Primary + secondary swell components, not one aggregated height
- Wind-wave component separately (swell purity)
- Hourly resolution for trend analysis

Pure functions — no I/O, stdlib only.
"""
import math
from datetime import datetime, timezone

VALID_LEVELS = ("beginner", "improver", "intermediate", "advanced")
DEFAULT_LEVEL = "improver"


def _normalize_level(level):
    return level if level in VALID_LEVELS else DEFAULT_LEVEL


def _bearing_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


# ---------------------------------------------------------------------------
# Height — level-aware (uses OM swell_height, which is the primary swell only)
# ---------------------------------------------------------------------------

def _grade_height_beginner(h):
    if h < 0.5:
        return ("yellow",
                f"Only {h}m of swell — basically flat. You'll be paddling for ripples "
                f"that fizzle out. Fine for pop-up practice on the whitewash, but not "
                f"a real surf day.")
    if h < 0.8:
        return ("yellow",
                f"{h}m is small — knee-to-waist. Gentle enough, but waves break weakly "
                f"and don't carry you far. Useful for building fundamentals, nothing more.")
    if h <= 1.5:
        return ("green",
                f"{h}m — chest-high groundswell, exactly your range. Enough push to "
                f"ride properly, paddle-out is manageable, getting caught inside isn't "
                f"a crisis. This is the size to be learning on.")
    if h <= 2.0:
        return ("yellow",
                f"{h}m is overhead and getting serious. Doable on a clean day, but "
                f"waves break harder and paddle-outs take real effort. Any other red "
                f"signal today means skip.")
    return ("red",
            f"{h}m is well overhead for your level. You won't reliably make it "
            f"past the impact zone, and if you do, getting back is harder. "
            f"Watch from the beach today.")


def _grade_height_improver(h):
    if h < 0.4:
        return ("yellow",
                f"{h}m is barely a ripple. Even a forgiving mid-length needs something "
                f"to glide on. Paddle-fitness day.")
    if h < 0.6:
        return ("yellow",
                f"{h}m — knee-to-thigh. A mid-length will still trim, so it's not a "
                f"total write-off, but don't expect much.")
    if h <= 1.7:
        return ("green",
                f"{h}m — waist-to-overhead, your range. Plenty to catch, paddle-out "
                f"manageable, mistakes recoverable. This is where you progress.")
    if h <= 2.2:
        return ("yellow",
                f"{h}m is overhead+ and getting honest. Workable if everything else "
                f"lines up, but duck-dives won't go fully clean yet and getting caught "
                f"inside costs you. Pick your moments.")
    return ("red",
            f"{h}m is well overhead at your experience level. The paddle-out is the "
            f"hard part, and a 7ft board won't reliably get you under sets. Skip it.")


def _grade_height_intermediate(h):
    if h < 0.5:
        return ("yellow",
                f"{h}m is mostly fitness paddling — nothing for a performance board to "
                f"plane on. Skip unless you're on a longboard.")
    if h < 0.8:
        return ("yellow",
                f"{h}m is small but rideable if shape is clean. Bring volume, don't "
                f"expect to throw turns.")
    if h <= 2.5:
        return ("green",
                f"{h}m — squarely in your range. Plenty of push, faces hold, sections "
                f"to work. Get out there.")
    if h <= 3.0:
        return ("yellow",
                f"{h}m is solidly overhead. Workable when period and wind align — "
                f"if anything else is compromised the wave count drops fast and the "
                f"paddle-out hurts.")
    return ("red",
            f"{h}m is double-overhead+. Only paddle out if you've consistently surfed "
            f"this size before — it's big-wave territory.")


def _grade_height_advanced(h):
    if h < 0.6:
        return ("yellow",
                f"{h}m is barely anything on a shortboard. Fine for rail work on gutless "
                f"waves, but don't expect real surfing.")
    if h < 1.0:
        return ("yellow",
                f"{h}m is small. Rideable, but a performance board needs more juice to "
                f"project. Good for working technique on weak waves.")
    if h <= 3.5:
        return ("green",
                f"{h}m — your range. Enough face to generate speed, link turns, and "
                f"find sections. Get out there.")
    if h <= 4.5:
        return ("yellow",
                f"{h}m is solid overhead-plus. You can handle it, but commit fully — "
                f"hesitation at this size is punished. Check period and wind first.")
    return ("red",
            f"{h}m is big-wave territory. Specialised equipment and safety plan required.")


_HEIGHT_GRADERS = {
    "beginner":     _grade_height_beginner,
    "improver":     _grade_height_improver,
    "intermediate": _grade_height_intermediate,
    "advanced":     _grade_height_advanced,
}


def grade_height_om(h, level=DEFAULT_LEVEL):
    if h is None:
        return ("unknown", "Swell height not available from Open-Meteo.")
    return _HEIGHT_GRADERS[_normalize_level(level)](h)


# ---------------------------------------------------------------------------
# Period — level-aware (OM gives exact swell period in seconds)
# ---------------------------------------------------------------------------

def _grade_period_beginner(p):
    if p < 6:
        return ("red",
                f"{p}s is wind chop, not swell. Nothing to ride even if the height "
                f"number looks reasonable.")
    if p < 9:
        return ("yellow",
                f"{p}s — wind swell. Waves are bunched up, weak, and tend to close "
                f"out. White-water practice is fine, but you won't get proper rides.")
    if p <= 13:
        return ("green",
                f"{p}s — organised groundswell. Waves arrive evenly spaced and "
                f"predictable. Easy to read the sets, good for building timing.")
    if p <= 16:
        return ("yellow",
                f"{p}s is long-period. The same height hits noticeably harder — faces "
                f"are steeper, takeoffs faster, hold-downs longer. Drop one size from "
                f"what you'd normally paddle out for.")
    return ("red",
            f"{p}s is extreme long-period. A 1.5m wave behaves like 2.5m in terms of "
            f"power. Surprise clean-up sets pull from much further out. Expert only.")


def _grade_period_improver(p):
    if p < 5:
        return ("red",
                f"{p}s is wind chop. No shape to work with regardless of height.")
    if p < 8:
        return ("yellow",
                f"{p}s — short-period wind swell. Bunched up and mushy. A mid-length "
                f"will glide on this, but don't expect long rides or proper shape.")
    if p <= 14:
        return ("green",
                f"{p}s — clean groundswell. Organised sets, predictable, evenly spaced. "
                f"The kind of period where you get to choose your wave.")
    if p <= 17:
        return ("yellow",
                f"{p}s is long-period. Same height hits harder — steeper faces, faster "
                f"takeoffs. Drop one size tier from what you'd normally go for.")
    return ("red",
            f"{p}s is extreme long-period. Sets pull from much further out, surprise "
            f"clean-ups are real. Above your tier regardless of height.")


def _grade_period_intermediate(p):
    if p < 5:
        return ("red", f"{p}s is wind chop. Nothing to ride.")
    if p < 7:
        return ("yellow",
                f"{p}s is short and choppy. Workable only if wind is dead-offshore.")
    if p <= 16:
        return ("green",
                f"{p}s — clean groundswell, full performance window. Sets are organised "
                f"and shape holds through the face.")
    if p <= 18:
        return ("yellow",
                f"{p}s is long-period. Steep faces, fast takeoffs, real hold-downs. "
                f"Treat the height as one size up.")
    return ("red",
            f"{p}s is exceptional long-period. Surprise sets, extended lulls, waves "
            f"that punch well above their listed height.")


def _grade_period_advanced(p):
    if p < 5:
        return ("red", f"{p}s is wind chop — no swell energy. Nothing to surf.")
    if p < 7:
        return ("yellow",
                f"{p}s is short-period wind swell. Messy and weak; only workable with "
                f"a generous height number and dead-offshore wind.")
    if p <= 18:
        return ("green",
                f"{p}s — full performance window. Organised sets, predictable takeoffs, "
                f"faces that hold. This is what you came for.")
    if p <= 20:
        return ("yellow",
                f"{p}s is long-period and powerful. Lulls are long, sets are heavy. "
                f"Treat the height as one size up and pick your takeoff spot carefully.")
    return ("red",
            f"{p}s is exceptional long-period. Surprise clean-up sets and extended "
            f"hold-downs. Know your exit before paddling out.")


_PERIOD_GRADERS = {
    "beginner":     _grade_period_beginner,
    "improver":     _grade_period_improver,
    "intermediate": _grade_period_intermediate,
    "advanced":     _grade_period_advanced,
}


def grade_period_om(p, level=DEFAULT_LEVEL):
    if p is None:
        return ("unknown", "Swell period not available from Open-Meteo.")
    return _PERIOD_GRADERS[_normalize_level(level)](p)


# ---------------------------------------------------------------------------
# Wind — precise km/h + exact angle (key advantage over scraper's text labels)
# ---------------------------------------------------------------------------

def grade_wind_om(speed_kmh, wind_dir_deg, offshore_bearing, level=DEFAULT_LEVEL):
    if speed_kmh is None or wind_dir_deg is None or offshore_bearing is None:
        return ("unknown", "Wind data not available from Open-Meteo.")

    level = _normalize_level(level)
    speed = round(speed_kmh)
    angle = round(_bearing_diff(wind_dir_deg, offshore_bearing))

    # Glassy — direction doesn't matter when there's almost no wind
    if speed < 5:
        return ("green",
                f"Virtually no wind ({speed} km/h) — glassy conditions. Surface will "
                f"be mirror-smooth. Drop everything and go.")

    # Classify direction
    if angle <= 30:
        direction = "offshore"
    elif angle <= 60:
        direction = "cross-offshore"
    elif angle <= 120:
        direction = "cross-shore"
    elif angle <= 150:
        direction = "cross-onshore"
    else:
        direction = "onshore"

    if direction == "offshore":
        if speed <= 12:
            return ("green",
                    f"{speed} km/h offshore ({angle}° off) — clean conditions. Wave "
                    f"faces hold up nicely, slight texture at most.")
        if speed <= 22:
            return ("green",
                    f"{speed} km/h offshore ({angle}° off) — solid classic conditions. "
                    f"Faces stand up, surface is clean. Strong enough that paddling "
                    f"into waves takes a bit more effort.")
        return ("yellow",
                f"{speed} km/h offshore ({angle}° off) — heavy offshore. Faces stand "
                f"up very steep and wind holds the lip, but paddling into waves is a "
                f"struggle and it can blow you back. Commit to your takeoff.")

    if direction == "cross-offshore":
        if speed <= 15:
            return ("green",
                    f"{speed} km/h cross-offshore ({angle}° off) — nearly as good as "
                    f"straight offshore. Slight bumpiness on the face but wave shape "
                    f"holds well.")
        return ("yellow",
                f"{speed} km/h cross-offshore ({angle}° off) — some chop on the face "
                f"but waves still hold shape. Manageable, not ideal.")

    if direction == "cross-shore":
        if speed <= 10:
            return ("yellow",
                    f"{speed} km/h cross-shore ({angle}° off) — light but blowing "
                    f"parallel to the beach. Adds inconsistency and occasional chop.")
        return ("yellow",
                f"{speed} km/h cross-shore ({angle}° off) — choppy and inconsistent. "
                f"Wave shape suffers, timing becomes harder.")

    if direction == "cross-onshore":
        if speed <= 10:
            return ("yellow",
                    f"{speed} km/h cross-onshore ({angle}° off) — crumbling the outside "
                    f"of the waves before they wall up properly. Light enough to tolerate.")
        return ("red" if level in ("beginner", "improver") else "yellow",
                f"{speed} km/h cross-onshore ({angle}° off) — waves crumble before "
                f"forming a clean face. Messy takeoffs, poor shape.")

    # Onshore
    if level == "advanced":
        return ("red",
                f"{speed} km/h onshore ({angle}° off) — waves crumble before walling "
                f"up, faces go to mush. Even solid swell is neutered. Find a sheltered "
                f"break or wait it out.")
    return ("red",
            f"{speed} km/h onshore ({angle}° off) — the classic day-killer. Waves "
            f"crumble before breaking properly, surface is choppy, pop-up timing "
            f"becomes guesswork. Even perfect swell gets ruined.")


# ---------------------------------------------------------------------------
# Swell shape — combines purity + secondary swell into one prose explanation
# (unique to OM: SF can't distinguish these)
# ---------------------------------------------------------------------------

def grade_swell_shape(swell_h, swell2_h, swell2_dir, swell1_dir, wind_wave_h, wave_h):
    if wave_h is None or wave_h <= 0:
        return ("unknown", "Swell composition data not available.")

    wind_h = wind_wave_h or 0.0
    purity_ratio = wind_h / wave_h
    has_secondary = swell2_h and swell2_h > 0 and swell1_dir is not None and swell2_dir is not None
    dir_conflict = _bearing_diff(swell1_dir or 0, swell2_dir or 0) > 60 if has_secondary else False
    secondary_ratio = (swell2_h / swell_h) if (has_secondary and swell_h and swell_h > 0) else 0

    # Worst case: wind-dominated + crossed swells
    if purity_ratio > 0.50 and has_secondary and secondary_ratio > 0.40 and dir_conflict:
        return ("red",
                f"A mess: wind sea is {round(purity_ratio*100)}% of total wave energy, and two "
                f"swell systems are crossing from {round(_bearing_diff(swell1_dir, swell2_dir))}° "
                f"apart. Chaotic, unpredictable shape.")

    # Wind-dominated chop
    if purity_ratio > 0.50:
        return ("red",
                f"Wind sea makes up {round(purity_ratio*100)}% of the total wave height — "
                f"choppy, disorganised junk. The swell structure is buried under wind chop.")

    # Crossed swells (significant secondary from different angle)
    if has_secondary and secondary_ratio > 0.40 and dir_conflict:
        return ("yellow",
                f"Two swell systems converging from directions {round(_bearing_diff(swell1_dir, swell2_dir))}° "
                f"apart (secondary at {round(secondary_ratio*100)}% of primary). "
                f"Expect lumpy, unpredictable sets and awkward takeoffs.")

    # Secondary stacking (same window — adds size, not confusion)
    if has_secondary and secondary_ratio > 0.40 and not dir_conflict:
        return ("yellow",
                f"Secondary swell ({round(secondary_ratio*100)}% of primary) arriving from a "
                f"similar angle — adds some size but also some lumpiness between sets.")

    # Mixed (some wind chop but organised swell still dominant)
    if purity_ratio > 0.25:
        return ("yellow",
                f"Organised swell dominant but with some wind chop ({round(purity_ratio*100)}% "
                f"wind sea). Lines will be slightly textured — not pristine.")

    # Clean single swell — the ideal
    if has_secondary and secondary_ratio > 0.20:
        return ("green",
                f"Clean primary swell with a minor secondary ({round(secondary_ratio*100)}% of "
                f"primary). Mostly consistent lines with occasional extra size.")

    return ("green",
            f"Clean organised swell — only {round(purity_ratio*100)}% wind sea. "
            f"Expect consistent, evenly spaced lines with good shape.")


# ---------------------------------------------------------------------------
# Swell direction — degrees precision vs. spot bearing
# ---------------------------------------------------------------------------

def grade_direction_om(swell_dir_deg, optimal_bearing, optimal_label=None):
    if swell_dir_deg is None or optimal_bearing is None:
        return ("unknown", "Swell direction or spot bearing not configured.")

    diff = round(_bearing_diff(swell_dir_deg, optimal_bearing))
    ideal = f"ideal is {optimal_label}" if optimal_label else f"ideal ~{optimal_bearing}°"

    if diff <= 20:
        return ("green",
                f"Swell at {round(swell_dir_deg)}° — nearly perfectly aligned with this "
                f"break ({ideal}). Spot is fully exposed, waves wrap in cleanly.")
    if diff <= 45:
        return ("yellow",
                f"Swell at {round(swell_dir_deg)}° — {diff}° off the ideal angle ({ideal}). "
                f"Waves reach the break but lose some height and shape. "
                f"Expect roughly 80–90% of the forecast size.")
    return ("yellow",
            f"Swell at {round(swell_dir_deg)}° — {diff}° off the ideal ({ideal}). "
            f"Much of the swell energy is blocked or bent around the coast. "
            f"Effective size may be half the model forecast.")


# ---------------------------------------------------------------------------
# Trend analysis — unique to hourly OM data
# ---------------------------------------------------------------------------

def _wind_class(h: dict, offshore_bearing: float) -> int:
    """0=offshore, 1=cross-offshore, 2=cross-shore, 3=cross-onshore, 4=onshore"""
    wd = h.get("wind_direction")
    if wd is None:
        return 2
    diff = _bearing_diff(wd, offshore_bearing)
    if diff <= 30:   return 0
    if diff <= 60:   return 1
    if diff <= 120:  return 2
    if diff <= 150:  return 3
    return 4


def _ts(h: dict) -> datetime | None:
    try:
        dt = datetime.fromisoformat(h["timestamp_utc"])
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return None


def wind_trend(today_hours: list[dict], offshore_bearing: float | None) -> dict:
    """Classify how wind quality changes through today's hours."""
    if not today_hours or offshore_bearing is None:
        return {"label": "Unknown", "detail": "Wind trend data not available."}

    now_utc = datetime.now(timezone.utc)
    future = [h for h in today_hours if (_ts(h) or now_utc) >= now_utc]
    if len(future) < 3:
        future = today_hours

    classes = [_wind_class(h, offshore_bearing) for h in future]
    speeds  = [h.get("wind_speed") or 0 for h in future]

    first_class = classes[0]
    last_class  = classes[-1]
    delta = last_class - first_class

    def _time_label(h):
        ts = _ts(h)
        return ts.strftime("%H:%M") if ts else "later"

    if delta <= -1:
        # Getting better (lower class = more offshore)
        turning_h = next((h for h, c in zip(future, classes) if c < first_class), future[-1])
        return {
            "label": "Improving",
            "detail": f"Wind is improving through the day — turning more favourable from {_time_label(turning_h)}.",
        }

    if delta >= 1:
        # Getting worse
        turning_h = next((h for h, c in zip(future, classes) if c > first_class), future[-1])
        spd = round(speeds[-1]) if speeds else "?"
        return {
            "label": "Worsening",
            "detail": (f"Wind deteriorates from {_time_label(turning_h)} "
                       f"(building to ~{spd} km/h). Get out early."),
        }

    # Stable — note if speed changes significantly
    if speeds and max(speeds) > 0 and (max(speeds) - min(speeds)) > 10:
        return {
            "label": "Variable",
            "detail": f"Wind direction stays similar but speed varies {round(min(speeds))}–{round(max(speeds))} km/h through the day.",
        }

    return {"label": "Stable", "detail": "Wind is expected to remain consistent through the day."}


def swell_trend(today_hours: list[dict]) -> dict:
    """Is swell building, peaking, or dropping through today."""
    if not today_hours:
        return {"label": "Unknown", "detail": "Swell trend data not available."}

    heights = [(h, h.get("swell_height") or h.get("wave_height") or 0) for h in today_hours]
    valid = [(h, v) for h, v in heights if v > 0]
    if len(valid) < 4:
        return {"label": "Stable", "detail": "Insufficient hourly data to detect a swell trend."}

    peak_h, peak_v = max(valid, key=lambda x: x[1])
    first_v = valid[0][1]
    last_v  = valid[-1][1]
    peak_idx = valid.index((peak_h, peak_v))
    total = len(valid)

    def _time_label(h):
        ts = _ts(h)
        return ts.strftime("%H:%M") if ts else ""

    if peak_idx == 0 or peak_idx < total * 0.25:
        return {
            "label": "Dropping",
            "detail": f"Swell is dropping through the day (peaked at {round(peak_v, 1)}m). Go now.",
        }
    if peak_idx >= total * 0.75:
        return {
            "label": "Building",
            "detail": f"Swell building through the day — expected to peak around {_time_label(peak_h)} at ~{round(peak_v, 1)}m.",
        }
    if (last_v / first_v if first_v > 0 else 1) < 0.80:
        return {
            "label": "Peaking then dropping",
            "detail": f"Swell peaks around {_time_label(peak_h)} at {round(peak_v, 1)}m, then drops.",
        }
    return {
        "label": "Stable",
        "detail": f"Swell is fairly consistent through the day, around {round(sum(v for _, v in valid)/len(valid), 1)}m.",
    }


# ---------------------------------------------------------------------------
# OM verdict — synthesises OM grades into GO / MAYBE / SKIP + plain-English
# ---------------------------------------------------------------------------

_SKIP_REASONS = {
    "Height":    "the swell is outside your safe range",
    "Period":    "the period carries more power than your level handles",
    "Wind":      "the wind is killing wave shape",
    "Shape":     "the swell is too messy to surf productively",
    "Direction": "the swell angle is wrong for this break",
}

_WEAK_REASONS = {
    "Height":    "swell size is on the edge of your range",
    "Period":    "the period is pushing the boundaries of your tier",
    "Wind":      "the wind is adding chop and inconsistency",
    "Shape":     "the swell shape is compromised",
    "Direction": "the swell angle is off for this break",
}


def om_verdict(grades: list[tuple], level: str = DEFAULT_LEVEL) -> dict:
    """
    grades: list of (label, (color, explanation)) tuples.
    Returns verdict dict matching explainer.py's output format.
    """
    level = _normalize_level(level)
    reds    = [label for label, (color, _) in grades if color == "red"]
    yellows = [label for label, (color, _) in grades if color == "yellow"]
    all_unknown = all(c == "unknown" for _, (c, _) in grades)

    if all_unknown:
        return {
            "om_verdict": "empty",
            "om_verdict_text": "Could not assess conditions from Open-Meteo data.",
            "om_details": [],
        }

    if reds:
        overall = "skip"
        primary = reds[0]
        headline = _SKIP_REASONS.get(primary, f"{primary.lower()} is out of range")
        if len(reds) > 1:
            other_reasons = " and ".join(
                _SKIP_REASONS.get(r, f"{r.lower()} is a problem") for r in reds[1:]
            )
            verdict_text = (
                f"SKIP (Open-Meteo) — {headline}. {other_reasons.capitalize()} too. "
                f"Don't paddle out today."
            )
        else:
            verdict_text = (
                f"SKIP (Open-Meteo) — {headline}. "
                f"Find another spot, watch from the beach, or wait for it to change."
            )
    elif len(yellows) >= 2:
        overall = "maybe"
        problems = " and ".join(y.lower() for y in yellows[:2])
        verdict_text = (
            f"MAYBE (Open-Meteo) — {problems} are both compromised. "
            f"Workable but not great. Check the webcam before driving; "
            f"if the lineup looks clean, give it an hour."
        )
    elif yellows:
        overall = "go"
        weak = yellows[0]
        headline = _WEAK_REASONS.get(weak, f"{weak.lower()} is the weak link")
        verdict_text = (
            f"GO (Open-Meteo) — mostly clean, but {headline}. "
            f"Read the detail below before paddling out."
        )
    else:
        overall = "go"
        verdict_text = "GO (Open-Meteo) — clean conditions across the board. Get out there."

    return {
        "om_verdict": overall,
        "om_verdict_text": verdict_text,
        "om_details": [
            {"label": label, "color": color, "explanation": explanation}
            for label, (color, explanation) in grades
        ],
    }


# ---------------------------------------------------------------------------
# Session narrative — 2-3 sentence synthesis for a surf-buddy feel
# ---------------------------------------------------------------------------

def session_narrative(
    overall: str,
    grades: list[tuple],
    wind_tr: dict,
    swell_tr: dict,
    best_window: dict | None,
    level: str,
    swell_h: float | None,
    swell_p: float | None,
    wind_speed: float | None,
    wind_label: str | None,
) -> str:
    level = _normalize_level(level)

    # Find the primary driving factor (first red, or first yellow, or first green)
    primary_color = "unknown"
    primary_explanation = ""
    for _, (color, explanation) in grades:
        if color != "unknown":
            if primary_color == "unknown" or (color == "red" and primary_color != "red") or (color == "yellow" and primary_color == "green"):
                primary_color = color
                primary_explanation = explanation

    parts = []

    # --- Opening sentence ---
    if overall == "skip":
        red_grades = [(l, e) for l, (c, e) in grades if c == "red"]
        if red_grades:
            _, explanation = red_grades[0]
            # Split on ". " (period + space) to avoid breaking on decimals like 2.2m
            import re as _re
            sentences = _re.split(r'\.\s+', explanation)
            lead = sentences[0].rstrip(".")
            parts.append(lead + ".")
        else:
            parts.append("Conditions aren't looking good today.")

    elif overall == "maybe":
        yellow_grades = [(l, e) for l, (c, e) in grades if c == "yellow"]
        if yellow_grades:
            labels = " and ".join(l.lower() for l, _ in yellow_grades[:2])
            parts.append(f"The {labels} are the weak links today — not great, not terrible.")
        else:
            parts.append("Mixed signals today.")

    else:  # go
        # Build a positive opening using the best signals
        if swell_h is not None and swell_p is not None:
            size_word = (
                "small" if swell_h < 0.7 else
                "fun-sized" if swell_h < 1.2 else
                "solid" if swell_h < 2.0 else
                "punchy"
            )
            period_word = (
                "clean groundswell" if swell_p >= 12 else
                "organised swell" if swell_p >= 9 else
                "wind swell"
            )
            wind_note = f" with {round(wind_speed or 0)} km/h {wind_label or 'wind'}" if wind_label and wind_label not in ("No wind data",) else ""
            parts.append(
                f"A {size_word} {period_word} at {swell_h}m / {swell_p}s{wind_note} — "
                f"{'good shape and manageable conditions' if level in ('beginner','improver') else 'proper surf today'}."
            )
        else:
            parts.append("Conditions look clean based on Open-Meteo data.")

    # --- Middle sentence: timing / trend ---
    trend_detail = None
    if wind_tr and wind_tr.get("label") == "Worsening":
        trend_detail = wind_tr["detail"]
    elif swell_tr and swell_tr.get("label") in ("Dropping", "Building"):
        trend_detail = swell_tr["detail"]
    elif wind_tr and wind_tr.get("label") == "Improving":
        trend_detail = wind_tr["detail"]

    if trend_detail:
        parts.append(trend_detail)

    # --- Closing: best window or level-specific tip ---
    if best_window and overall in ("go", "maybe"):
        parts.append(f"Best window today: {best_window['label']}.")
    elif overall == "skip":
        if level in ("beginner", "improver"):
            parts.append("Use this as a beach observation day — watch how sets arrive and where other surfers paddle out.")
        else:
            parts.append("Check back later — conditions may shift.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Legacy badge functions (kept for backward compatibility with frontend badges)
# ---------------------------------------------------------------------------

def swell_purity(wave_height, wind_wave_height):
    if not wave_height or wave_height <= 0:
        return {"score": None, "label": "No wave data", "color": "unknown"}
    wind_h = wind_wave_height or 0.0
    ratio = wind_h / wave_height
    if ratio < 0.25:   label, color = "Clean swell", "green"
    elif ratio <= 0.50: label, color = "Mixed", "yellow"
    else:               label, color = "Wind-dominated chop", "red"
    return {"score": round(ratio, 2), "label": label, "color": color}


def swell_quality(period_s):
    if period_s is None:
        return {"label": "No period data", "color": "unknown"}
    if period_s < 8:     label, color = "Short-period chop", "red"
    elif period_s <= 11: label, color = "Medium-period swell", "yellow"
    elif period_s <= 15: label, color = "Quality groundswell", "green"
    else:                label, color = "Long-period groundswell", "green"
    return {"label": label, "color": color}


def direction_precision(swell_dir_deg, optimal_bearing):
    if swell_dir_deg is None or optimal_bearing is None:
        return {"diff_deg": None, "label": "No direction data", "color": "unknown"}
    diff = int(round(_bearing_diff(swell_dir_deg, optimal_bearing)))
    if diff <= 20:   label, color = "On target", "green"
    elif diff <= 45: label, color = "Slightly off", "yellow"
    else:            label, color = "Wrong direction", "red"
    return {"diff_deg": diff, "label": label, "color": color}


def wind_assessment(wind_speed_kmh, wind_dir_deg, offshore_bearing):
    if wind_dir_deg is None or offshore_bearing is None:
        return {"angle_deg": None, "angle_label": "No wind data", "speed_label": "", "color": "unknown", "summary": "No wind data"}
    angle = int(round(_bearing_diff(wind_dir_deg, offshore_bearing)))
    if angle <= 30:    angle_label, color = "Offshore", "green"
    elif angle <= 60:  angle_label, color = "Cross-offshore", "green"
    elif angle <= 120: angle_label, color = "Cross-shore", "yellow"
    elif angle <= 150: angle_label, color = "Cross-onshore", "yellow"
    else:              angle_label, color = "Onshore", "red"
    speed = wind_speed_kmh or 0.0
    if speed < 10:      speed_label = "Light"
    elif speed <= 20:   speed_label = "Moderate"
    elif speed <= 30:   speed_label = "Fresh"
    elif speed <= 40:   speed_label = "Strong"
    else:               speed_label = "Gale"
    summary = f"{round(speed)} km/h {angle_label} ({angle}deg off)"
    return {"angle_deg": angle, "angle_label": angle_label, "speed_label": speed_label, "color": color, "summary": summary}


def secondary_swell_interference(swell1_height, swell2_height, swell1_dir, swell2_dir):
    if not swell1_height or swell1_height <= 0 or not swell2_height:
        return {"flag": False, "label": "Clean dominant swell", "color": "green"}
    ratio = swell2_height / swell1_height
    dir_diff = _bearing_diff(swell1_dir or 0, swell2_dir or 0) if (swell1_dir is not None and swell2_dir is not None) else 0
    if ratio > 0.40 and dir_diff > 60:
        return {"flag": True, "label": "Confused/crossed seas", "color": "red"}
    if ratio > 0.40:
        return {"flag": False, "label": "Secondary swell stacking", "color": "yellow"}
    return {"flag": False, "label": "Clean dominant swell", "color": "green"}


def _hour_score(h, optimal_bearing, offshore_bearing, level=DEFAULT_LEVEL, spot=None, tide_color=None):
    factors = hour_factor_scores(
        h,
        optimal_bearing,
        offshore_bearing,
        level=level,
        spot=spot,
        tide_color=tide_color,
    )
    return _score_from_factors(factors)


def best_hourly_window(today_hours, optimal_bearing, offshore_bearing):
    if not today_hours:
        return None
    scores = [_hour_score(h, optimal_bearing, offshore_bearing) for h in today_hours]
    scores = [score if score is not None else 0.0 for score in scores]
    best_start, best_sum = 0, -1.0
    for i in range(max(1, len(scores) - 2)):
        window_sum = sum(scores[i:i+3])
        if window_sum > best_sum:
            best_sum = window_sum
            best_start = i
    avg_score = round(best_sum / min(3, len(scores)), 1)
    hours_subset = today_hours[best_start:best_start + 3]

    def _hour_str(h):
        ts = _ts(h)
        return ts.strftime("%H:%M") if ts else h.get("timestamp_utc", "?")[11:16]

    start_str = _hour_str(hours_subset[0])
    end_h = today_hours[min(best_start + 3, len(today_hours) - 1)]
    end_str = _hour_str(end_h)
    return {
        "best_start_hour": best_start,
        "hours": list(range(best_start, best_start + 3)),
        "label": f"{start_str}-{end_str} (score {avg_score}/10)",
        "score": avg_score,
    }


def data_confidence(om_swell_height, sf_height_m):
    if om_swell_height is None or sf_height_m is None or sf_height_m == 0:
        return {"label": "Insufficient data", "color": "unknown", "divergence_pct": None}
    divergence = abs(om_swell_height - sf_height_m) / sf_height_m
    div_pct = round(divergence * 100, 1)
    if divergence < 0.20:    label, color = "High confidence", "green"
    elif divergence <= 0.40: label, color = "Moderate confidence", "yellow"
    else:                    label, color = "Low confidence — models disagree", "red"
    return {"label": label, "color": color, "divergence_pct": div_pct}


def swell_energy(height_m, period_s):
    if not height_m or not period_s:
        return None
    return round(height_m ** 2 * period_s, 1)


# ---------------------------------------------------------------------------
# Doctrine V2 suitability scoring
# ---------------------------------------------------------------------------

_FACTOR_WEIGHTS = {
    "height": 0.24,
    "power": 0.14,
    "period": 0.12,
    "wind": 0.18,
    "chop": 0.12,
    "direction": 0.08,
    "secondary": 0.06,
    "tide": 0.06,
}

_HEIGHT_SUITABILITY = {
    "beginner":     (0.25, 0.80, 1.50, 2.40),
    "improver":     (0.25, 0.60, 1.70, 2.60),
    "intermediate": (0.35, 0.80, 2.50, 3.50),
    "advanced":     (0.45, 1.00, 3.50, 5.00),
}

_PERIOD_SUITABILITY = {
    "beginner":     (5.0, 9.0, 13.0, 17.0),
    "improver":     (5.0, 8.0, 14.0, 18.0),
    "intermediate": (5.0, 7.0, 16.0, 20.0),
    "advanced":     (5.0, 7.0, 18.0, 22.0),
}

_POWER_SUITABILITY = {
    "beginner":     (2.0, 7.0, 24.0, 45.0),
    "improver":     (1.5, 5.0, 40.0, 70.0),
    "intermediate": (2.0, 7.0, 110.0, 180.0),
    "advanced":     (3.0, 10.0, 220.0, 360.0),
}


def _clamp01(value):
    if value is None:
        return None
    return max(0.0, min(1.0, value))


def _as_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ramp(value, lo, full_lo, full_hi, hi, floor=0.05):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value <= lo or value >= hi:
        return floor
    if full_lo <= value <= full_hi:
        return 1.0
    if value < full_lo:
        return max(floor, (value - lo) / max(full_lo - lo, 0.001))
    return max(floor, (hi - value) / max(hi - full_hi, 0.001))


def _piecewise(value, points, floor=0.05):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    points = sorted(points)
    if value <= points[0][0]:
        return max(floor, points[0][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if value <= x1:
            span = max(x1 - x0, 0.001)
            t = (value - x0) / span
            return max(floor, y0 + (y1 - y0) * t)
    return max(floor, points[-1][1])


def height_suitability(height_m, level=DEFAULT_LEVEL):
    level = _normalize_level(level)
    return _ramp(height_m, *_HEIGHT_SUITABILITY[level])


def period_suitability(period_s, level=DEFAULT_LEVEL, height_m=None):
    level = _normalize_level(level)
    score = _ramp(period_s, *_PERIOD_SUITABILITY[level])
    if score is None:
        return None
    height = height_m or 0.0
    # Long-period swell hits harder; power_suitability carries most of that,
    # but this small taper prevents 17s+ learner surf from looking perfect.
    if level in ("beginner", "improver") and period_s and period_s > _PERIOD_SUITABILITY[level][2]:
        score *= 0.85 if height < _HEIGHT_SUITABILITY[level][2] else 0.75
    return _clamp01(score)


def power_suitability(power_index, level=DEFAULT_LEVEL):
    level = _normalize_level(level)
    return _ramp(power_index, *_POWER_SUITABILITY[level])


def wind_suitability(speed_kmh, wind_dir_deg, offshore_bearing):
    if speed_kmh is None:
        return None
    try:
        speed = float(speed_kmh)
    except (TypeError, ValueError):
        return None
    if speed < 5:
        return 1.0
    if wind_dir_deg is None or offshore_bearing is None:
        return _piecewise(speed, [(5, 0.85), (15, 0.70), (25, 0.45), (40, 0.20)])

    angle = _bearing_diff(float(wind_dir_deg), float(offshore_bearing))
    if angle <= 30:
        return _piecewise(speed, [(5, 1.00), (12, 1.00), (22, 0.90), (35, 0.60), (45, 0.35)])
    if angle <= 60:
        return _piecewise(speed, [(5, 0.90), (15, 0.88), (25, 0.65), (40, 0.35)])
    if angle <= 120:
        return _piecewise(speed, [(5, 0.75), (10, 0.65), (20, 0.45), (35, 0.22)])
    if angle <= 150:
        return _piecewise(speed, [(5, 0.60), (10, 0.50), (18, 0.30), (30, 0.12)])
    return _piecewise(speed, [(5, 0.55), (10, 0.42), (15, 0.25), (30, 0.08)])


def chop_suitability(windsea_ratio):
    return _piecewise(windsea_ratio, [(0.00, 1.00), (0.15, 1.00), (0.25, 0.85), (0.50, 0.40), (0.70, 0.12)])


def direction_suitability(swell_dir_deg, optimal_bearing):
    if swell_dir_deg is None or optimal_bearing is None:
        return None
    diff = _bearing_diff(float(swell_dir_deg), float(optimal_bearing))
    return _piecewise(diff, [(0, 1.00), (20, 1.00), (45, 0.75), (90, 0.40), (140, 0.15), (180, 0.08)])


def secondary_suitability(swell1_height, swell2_height, swell1_dir, swell2_dir):
    if not swell1_height or swell1_height <= 0 or not swell2_height:
        return None
    ratio = swell2_height / swell1_height
    if ratio <= 0.20:
        return 0.95
    if swell1_dir is None or swell2_dir is None:
        return _piecewise(ratio, [(0.20, 0.95), (0.40, 0.75), (0.70, 0.45)])
    cross_angle = _bearing_diff(swell1_dir, swell2_dir)
    if cross_angle > 60:
        return _piecewise(ratio, [(0.20, 0.90), (0.40, 0.55), (0.70, 0.20)])
    return _piecewise(ratio, [(0.20, 0.95), (0.40, 0.70), (0.70, 0.45)])


def tide_suitability(tide_color):
    if tide_color is None:
        return None
    if tide_color == "red":
        return 0.15
    if tide_color == "yellow":
        return 0.75
    return 1.0


def _weighted_factor_geometric(factors, weights=None, epsilon=0.05):
    weights = weights or _FACTOR_WEIGHTS
    available = {
        key: _clamp01(value)
        for key, value in factors.items()
        if value is not None and key in weights
    }
    if not available:
        return None
    total = sum(weights[key] for key in available)
    if total <= 0:
        return None
    product = 1.0
    for key, value in available.items():
        product *= max(value, epsilon) ** (weights[key] / total)
    return product


def hour_factor_scores(h, optimal_bearing, offshore_bearing, level=DEFAULT_LEVEL, spot=None, tide_color=None):
    h = h or {}
    level = _normalize_level(level)
    wave_h = h.get("swell_height") if h.get("swell_height") is not None else h.get("wave_height")
    period = h.get("swell_period") if h.get("swell_period") is not None else h.get("wave_period")
    wind_h = h.get("wind_wave_height")
    swell_dir = h.get("swell_direction")
    wind_dir = h.get("wind_direction")
    wind_speed = h.get("wind_speed")
    swell2_h = h.get("swell2_height")
    swell2_dir = h.get("swell2_direction")

    wave_h_float = _as_float(wave_h)
    period_float = _as_float(period)
    wind_h_float = _as_float(wind_h)
    swell2_h_float = _as_float(swell2_h)
    power_index = (wave_h_float ** 2 * period_float) if wave_h_float is not None and period_float is not None else None
    windsea_ratio = (wind_h_float / wave_h_float) if wind_h_float is not None and wave_h_float and wave_h_float > 0 else None

    return {
        "height": height_suitability(wave_h_float, level),
        "power": power_suitability(power_index, level),
        "period": period_suitability(period_float, level, wave_h_float),
        "wind": wind_suitability(wind_speed, wind_dir, offshore_bearing),
        "chop": chop_suitability(windsea_ratio),
        "direction": direction_suitability(swell_dir, optimal_bearing),
        "secondary": secondary_suitability(wave_h_float, swell2_h_float, swell_dir, swell2_dir),
        "tide": tide_suitability(tide_color),
    }


def _score_from_factors(factors):
    if all(factors.get(key) is None for key in ("height", "power", "period")):
        return None
    quality = _weighted_factor_geometric(factors)
    return None if quality is None else quality * 10.0


# ---------------------------------------------------------------------------
# Top-level aggregator
# ---------------------------------------------------------------------------

def interpret_all(
    current: dict | None,
    today_hours: list[dict],
    sf_height_m: float | None,
    optimal_bearing: float | None,
    offshore_bearing: float | None,
    optimal_label: str | None = None,
    level: str = DEFAULT_LEVEL,
) -> dict:
    level = _normalize_level(level)
    c = current or {}

    wave_h    = c.get("wave_height")
    wave_p    = c.get("wave_period")
    wave_d    = c.get("wave_direction")
    swell_h   = c.get("swell_height")
    swell_p   = c.get("swell_period")
    swell_d   = c.get("swell_direction")
    swell_pk  = c.get("swell_peak_period")
    swell2_h  = c.get("swell2_height")
    swell2_p  = c.get("swell2_period")
    swell2_d  = c.get("swell2_direction")
    wind_wave_h = c.get("wind_wave_height")
    wind_spd  = c.get("wind_speed")
    wind_dir  = c.get("wind_direction")
    wind_gust = c.get("wind_gusts")
    air_t     = c.get("air_temp")

    # --- Level-aware grades for the verdict engine ---
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

    # --- Trend analysis ---
    wind_tr  = wind_trend(today_hours, offshore_bearing)
    swell_tr = swell_trend(today_hours)

    # --- Best window ---
    bw = best_hourly_window(today_hours, optimal_bearing, offshore_bearing)

    # --- Narrative ---
    wa = wind_assessment(wind_spd, wind_dir, offshore_bearing)
    narrative = session_narrative(
        overall=verdict["om_verdict"],
        grades=grades,
        wind_tr=wind_tr,
        swell_tr=swell_tr,
        best_window=bw,
        level=level,
        swell_h=swell_h,
        swell_p=swell_p or wave_p,
        wind_speed=wind_spd,
        wind_label=wa.get("angle_label"),
    )

    return {
        # Raw values
        "wave_height":       wave_h,
        "wave_period":       wave_p,
        "wave_direction":    wave_d,
        "swell_height":      swell_h,
        "swell_period":      swell_p,
        "swell_direction_deg": swell_d,
        "swell_peak_period": swell_pk,
        "swell2_height":     swell2_h,
        "swell2_period":     swell2_p,
        "swell2_direction_deg": swell2_d,
        "wind_wave_height":  wind_wave_h,
        "wind_speed_kmh":    wind_spd,
        "wind_direction_deg": wind_dir,
        "wind_gusts_kmh":    wind_gust,
        "air_temp_c":        air_t,
        # Verdict + narrative (new, primary output)
        "om_verdict":        verdict["om_verdict"],
        "om_verdict_text":   verdict["om_verdict_text"],
        "om_details":        verdict["om_details"],
        "session_narrative": narrative,
        "wind_trend":        wind_tr,
        "swell_trend":       swell_tr,
        # Legacy badges (backward compat)
        "swell_purity":       swell_purity(wave_h, wind_wave_h),
        "swell_quality":      swell_quality(swell_p or wave_p),
        "direction_precision": direction_precision(swell_d, optimal_bearing),
        "wind_assessment":    wa,
        "secondary_swell":    secondary_swell_interference(swell_h, swell2_h, swell_d, swell2_d),
        "best_hourly_window": bw,
        "data_confidence":    data_confidence(swell_h, sf_height_m),
        "swell_energy":       swell_energy(swell_h or wave_h, swell_p or wave_p),
        "om_fetched_at":      c.get("timestamp_utc"),
    }
