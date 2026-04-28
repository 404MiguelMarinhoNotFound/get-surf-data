"""Skill-aware rules engine: scraped data -> verdict + explanations.

Four skill tiers — `beginner`, `improver` (default), `intermediate`, `advanced` — each
with its own height and period thresholds and its own explanation templates.
The same wave looks different to each: 1.8m / 13s is "skip" for a beginner
and prime for an intermediate.

Wind grading is currently shared across tiers; equipment-specific grading
(longboard vs shortboard etc.) is a future extension.
"""


VALID_LEVELS = ("beginner", "improver", "intermediate", "advanced")
DEFAULT_LEVEL = "improver"


def _normalize_level(level):
    return level if level in VALID_LEVELS else DEFAULT_LEVEL


# ---------------------------------------------------------------------------
# Height — per-level
# ---------------------------------------------------------------------------

def _grade_height_beginner(h):
    if h < 0.5:
        return ("yellow",
                f"Only {h}m offshore — basically flat. There's no push to catch waves "
                f"with; you'll spend the session paddling for ripples that fizzle out "
                f"under you. Workable for practicing pop-ups, otherwise a slow day.")
    if h < 0.8:
        return ("yellow",
                f"{h}m is small — knee-to-waist high. Gentle, but waves break weakly "
                f"and don't carry you far. Fine for a first-ever session, otherwise a "
                f"slow day.")
    if h <= 1.5:
        return ("green",
                f"{h}m — chest-to-head high, exactly your range. Enough push to ride "
                f"properly, paddle-out is manageable, getting caught inside isn't a "
                f"crisis. This is the size you want.")
    if h <= 2.0:
        return ("yellow",
                f"{h}m is overhead and getting serious. Doable on a clean day, but "
                f"waves break harder, paddle-outs take real effort, and getting caught "
                f"inside means eating sets. If wind and period are perfect, give it a "
                f"shot — if anything else is off, skip.")
    return ("red",
            f"{h}m is well overhead. At your level you won't make it past the impact "
            f"zone, and if you do you can't get back. Watch from the promenade today.")


def _grade_height_improver(h):
    if h < 0.4:
        return ("yellow",
                f"{h}m is barely a ripple. Even a forgiving mid-length needs *something* "
                f"to glide on; today it's a paddle-fitness day, not a surf day.")
    if h < 0.6:
        return ("yellow",
                f"{h}m — knee-to-thigh. A mid-length will still trim on these so it's "
                f"not a wasted trip if you go, but it's small. Good for practicing "
                f"trim and timing without consequence.")
    if h <= 1.7:
        return ("green",
                f"{h}m — waist-to-overhead, your range. Plenty to catch, paddle-out "
                f"manageable, mistakes recoverable. This is the size where you progress.")
    if h <= 2.2:
        return ("yellow",
                f"{h}m is overhead+ and getting honest. Workable if wind and period "
                f"line up, but a hardboard punishes mistakes more than the soft top "
                f"you started on — duck-dives don't go clean yet, and getting caught "
                f"inside costs you. Pick your moments deep.")
    return ("red",
            f"{h}m is well overhead at your experience level. The paddle-out alone is "
            f"the hard part, and a 7ft-class board won't reliably get you under sets. "
            f"Skip — watch the cam and come back when it drops.")


def _grade_height_intermediate(h):
    if h < 0.5:
        return ("yellow",
                f"{h}m is mostly fitness paddling — there's nothing here for a "
                f"performance-board to plane on. Skip unless you're longboarding.")
    if h < 0.8:
        return ("yellow",
                f"{h}m is small but rideable if shape is clean. Bring volume, "
                f"don't expect to throw turns.")
    if h <= 2.5:
        return ("green",
                f"{h}m — squarely in your range. Plenty of push, faces hold, "
                f"sections to work with. Get out there.")
    if h <= 3.0:
        return ("yellow",
                f"{h}m is solidly overhead. Workable if period and wind align — "
                f"if anything else is off, the wave count drops fast and the "
                f"paddle-out hurts.")
    return ("red",
            f"{h}m is double-overhead+. Big-wave territory; only paddle out if "
            f"you've put in the time at this size.")


def _grade_height_advanced(h):
    if h < 0.6:
        return ("yellow",
                f"{h}m is barely anything. You'll be paddling for close-outs on a "
                f"performance board. Fine for fine-tuning technique, but don't expect "
                f"to surf.")
    if h < 1.0:
        return ("yellow",
                f"{h}m is small. Rideable, but a shortboard needs more juice to project "
                f"off the top. Good for working your rail game on gutless waves.")
    if h <= 3.5:
        return ("green",
                f"{h}m — your range. Enough face to generate speed, link turns, and "
                f"hunt for sections. Get out there.")
    if h <= 4.5:
        return ("yellow",
                f"{h}m is solid overhead-plus. You can handle it, but commit fully — "
                f"hesitation at this size gets punished. Make sure the period and wind "
                f"are clean before paddling out.")
    return ("red",
            f"{h}m is big-wave territory. Unless you've specifically trained at this "
            f"size with the right equipment and a safety plan, sit this one out.")


_HEIGHT_GRADERS = {
    "beginner":     _grade_height_beginner,
    "improver":     _grade_height_improver,
    "intermediate": _grade_height_intermediate,
    "advanced":     _grade_height_advanced,
}


def grade_height(h, level=DEFAULT_LEVEL):
    if h is None:
        return ("unknown",
                "Couldn't read wave height — surf-forecast.com may have changed format.")
    return _HEIGHT_GRADERS[_normalize_level(level)](h)


# ---------------------------------------------------------------------------
# Period — per-level
# ---------------------------------------------------------------------------

def _grade_period_beginner(p):
    if p < 6:
        return ("red",
                f"{p}s is barely a swell — just local wind chop. Nothing to ride, even "
                f"if the height number looks reasonable.")
    if p < 9:
        return ("yellow",
                f"{p}s is wind swell. Waves are bunched up, weak, and often close out "
                f"across the whole face. Mushy and frustrating, but safe — decent for "
                f"white-water practice if you're brand new.")
    if p <= 13:
        return ("green",
                f"{p}s — clean groundswell from a proper storm system. Waves arrive "
                f"organized, evenly spaced, predictable. The forgiving end of the "
                f"spectrum.")
    if p <= 16:
        return ("yellow",
                f"{p}s is long-period groundswell. Same wave height hits noticeably "
                f"harder than a 10s day — faces are steeper, takeoffs faster, "
                f"hold-downs longer. Mentally drop one size category from what you'd "
                f"normally surf.")
    return ("red",
            f"{p}s is extreme long-period swell. Surprise sets pull from much further "
            f"out and a 1.5m wave behaves like 2.5m. Expert territory regardless of "
            f"height.")


def _grade_period_improver(p):
    if p < 5:
        return ("red",
                f"{p}s is wind chop, not swell. Even with a forgiving board there's "
                f"no shape to work with.")
    if p < 8:
        return ("yellow",
                f"{p}s is short-period wind swell — bunched up, mushy, often closing "
                f"out. A mid-length will still glide on this; useful practice but "
                f"don't expect long rides.")
    if p <= 14:
        return ("green",
                f"{p}s — clean groundswell. Organized, evenly spaced, predictable "
                f"sets. The kind of period where you actually get to choose your wave.")
    if p <= 17:
        return ("yellow",
                f"{p}s is long-period. The same height number hits harder — steeper "
                f"faces, faster takeoffs, longer hold-downs. Drop one size tier from "
                f"what you'd normally paddle out for.")
    return ("red",
            f"{p}s is extreme long-period. Sets pull from much further out, surprise "
            f"clean-ups are real, and a 1.5m wave behaves like 2.5m. Above your tier "
            f"regardless of height.")


def _grade_period_intermediate(p):
    if p < 5:
        return ("red",
                f"{p}s is wind chop. No groundswell energy; nothing to ride.")
    if p < 7:
        return ("yellow",
                f"{p}s is short and choppy. Workable if wind is dead-offshore, "
                f"otherwise a writeoff.")
    if p <= 16:
        return ("green",
                f"{p}s — clean groundswell, the full window. Sets are organized, "
                f"shape holds, takeoffs are predictable enough to commit.")
    if p <= 18:
        return ("yellow",
                f"{p}s is long-period. Steep faces, fast takeoffs, real hold-downs. "
                f"Treat it as one size up from the height number.")
    return ("red",
            f"{p}s is exceptional long-period swell. Surprise sets, long lulls, "
            f"and waves that punch well above their listed height.")


def _grade_period_advanced(p):
    if p < 5:
        return ("red",
                f"{p}s is wind chop — no organised swell energy. Nothing to surf.")
    if p < 7:
        return ("yellow",
                f"{p}s is short-period wind swell. Messy and weak; workable only if "
                f"wind is dead-offshore and the height number is generous.")
    if p <= 18:
        return ("green",
                f"{p}s — clean groundswell, full window. Organised sets, predictable "
                f"takeoffs, faces that hold. This is what you came for.")
    if p <= 20:
        return ("yellow",
                f"{p}s is long-period. Powerful and spaced out — lulls are long, sets "
                f"are heavy. Treat the height as one size up and pick your take-off "
                f"spot carefully.")
    return ("red",
            f"{p}s is exceptional long-period. Surprise clean-up sets, extended "
            f"hold-downs, and listed height undersells what you'll face. Know the "
            f"exit before you paddle out.")


_PERIOD_GRADERS = {
    "beginner":     _grade_period_beginner,
    "improver":     _grade_period_improver,
    "intermediate": _grade_period_intermediate,
    "advanced":     _grade_period_advanced,
}


def grade_period(p, level=DEFAULT_LEVEL):
    if p is None:
        return ("unknown",
                "Couldn't read swell period — surf-forecast.com may have changed format.")
    return _PERIOD_GRADERS[_normalize_level(level)](p)


# ---------------------------------------------------------------------------
# Wind — shared across levels (for now)
# ---------------------------------------------------------------------------

def grade_wind(state, level=DEFAULT_LEVEL):
    if state is None:
        return ("unknown",
                "Couldn't read wind state — surf-forecast.com may have changed format.")
    s = state.lower()
    level = _normalize_level(level)

    # Order matters: check compound terms (cross-offshore, cross-onshore)
    # BEFORE the bare "offshore" / "onshore" substring match.
    if "glassy" in s:
        return ("green",
                "Glassy — no wind at all, mirror surface. The dream version of any "
                "swell. Drop everything and go.")
    if "cross-offshore" in s:
        return ("green",
                "Cross-offshore — diagonal from land to sea. Holds wave faces up and "
                "smooths the surface. Slight bumpiness, but still clean.")
    if "cross-onshore" in s:
        return ("yellow",
                "Cross-onshore — diagonal from sea to land. Adds chop and crumbles "
                "wave shape before they break properly. Workable if light, annoying "
                "if not.")
    if "offshore" in s:
        return ("green",
                "Offshore — wind blowing from land out to sea. Cleanest possible "
                "conditions: faces stand up, surface is smooth, takeoffs are "
                "predictable. The day you'd photograph.")
    if "onshore" in s:
        if level == "advanced":
            return ("red",
                    "Onshore — wind blowing from sea toward the beach. Waves crumble "
                    "before they wall up, faces go to mush, and there's nothing to "
                    "generate speed off. Even a solid swell gets neutered. Find a "
                    "sheltered break or wait it out.")
        return ("red",
                "Onshore — wind blowing from sea toward the beach. The classic "
                "day-killer: waves crumble before breaking, surface is choppy, timing "
                "pop-ups becomes guesswork. Even perfect swell gets ruined by this.")
    if "cross-shore" in s or s == "cross":
        return ("yellow",
                "Cross-shore — blowing parallel to the beach. Adds chop and "
                "inconsistent shape. Workable if light, gets messy fast if it picks up.")
    return ("unknown", f"Wind state '{state}' — couldn't classify. Check the page directly.")


# ---------------------------------------------------------------------------
# Swell direction × spot orientation
# ---------------------------------------------------------------------------

COMPASS_TO_DEG = {
    "N": 0,   "NNE": 22,  "NE": 45,  "ENE": 67,
    "E": 90,  "ESE": 112, "SE": 135, "SSE": 157,
    "S": 180, "SSW": 202, "SW": 225, "WSW": 247,
    "W": 270, "WNW": 292, "NW": 315, "NNW": 337,
}


def _bearing_diff(a_deg, b_deg):
    d = abs(a_deg - b_deg) % 360
    return min(d, 360 - d)


def grade_direction(swell_dir, optimal_bearing=None, optimal_label=None):
    """Grade how well the swell direction suits this spot.

    Caps at yellow — a bad angle is a 'wrong spot' problem, not a danger.
    Returns unknown when either input is absent.
    """
    if swell_dir is None:
        return ("unknown",
                "Couldn't read swell direction — surf-forecast.com may have changed format.")
    if optimal_bearing is None:
        return ("unknown",
                "No swell window configured for this spot.")

    deg = COMPASS_TO_DEG.get(swell_dir.upper())
    if deg is None:
        return ("unknown",
                f"Couldn't parse swell direction '{swell_dir}'.")

    diff = _bearing_diff(deg, optimal_bearing)
    ideal_str = f"ideal is {optimal_label}" if optimal_label else f"ideal bearing ~{optimal_bearing}°"

    if diff <= 25:
        return ("green",
                f"{swell_dir} swell — ideal angle for this break ({ideal_str}). "
                f"Spot is fully exposed, waves wrap in cleanly.")
    if diff <= 55:
        return ("yellow",
                f"{swell_dir} swell — partial fit ({diff:.0f}° off; {ideal_str}). "
                f"Waves reach the break but lose some height and shape. "
                f"Expect roughly 80–90% of the forecast size.")
    return ("yellow",
            f"{swell_dir} swell — wrong window for this break ({diff:.0f}° off; {ideal_str}). "
            f"Much of the swell energy is blocked or bent. "
            f"Effective height may be half the forecast — try another spot or wait for a better angle.")


def grade_tide(tide, tide_window=None):
    """Grade the current tide against a spot's preferred tide window."""
    if not tide:
        return ("unknown",
                "Couldn't read the tide table from surf-forecast.com.")
    if not tide_window:
        return ("unknown",
                "No tide window configured for this spot.")

    summary = tide.get("summary") or "tide state unavailable"
    state = tide.get("state")
    position = tide.get("position")
    next_turn = tide.get("next_turn") or {}
    next_type = next_turn.get("type")
    minutes = tide.get("minutes_to_next_turn")
    window = str(tide_window).lower()

    if position is None or state not in ("rising", "falling"):
        return ("unknown",
                f"Tide table was found ({summary}), but the current tide couldn't be interpolated.")

    if window in ("any", "all"):
        return ("green",
                f"Tide: {summary}. This spot is not especially tide-sensitive.")

    if window == "mid-to-high":
        if state == "rising" and 0.35 <= position <= 0.90:
            return ("green",
                    f"Tide: {summary}. Mid-to-high and pushing, which is the sweet spot here.")
        if state == "rising" and position < 0.35:
            if next_type == "high" and minutes is not None and minutes <= 90:
                return ("yellow",
                        f"Tide: {summary}. Still a little low, but it is pushing toward the right window.")
            return ("red",
                    f"Tide: {summary}. Too close to low tide for this break; expect shutdowns or weak shape.")
        if state == "falling" and position >= 0.55:
            return ("yellow",
                    f"Tide: {summary}. There is still enough water, but the tide is backing out.")
        if position > 0.90:
            return ("yellow",
                    f"Tide: {summary}. Very high tide can soften or add backwash here.")
        return ("red",
                f"Tide: {summary}. Outside the mid-to-high window this break usually wants.")

    if window == "low-to-mid":
        if position <= 0.60:
            return ("green",
                    f"Tide: {summary}. Low-to-mid is inside this spot's preferred window.")
        if position <= 0.80:
            return ("yellow",
                    f"Tide: {summary}. Getting a little full for this spot.")
        return ("red",
                f"Tide: {summary}. Too full for this spot's preferred low-to-mid window.")

    return ("unknown",
            f"Tide: {summary}. Tide window '{tide_window}' is not recognized.")


def wetsuit_advice(temp_c):
    """Gear advice based on water temperature. Not a verdict input."""
    if temp_c is None:
        return None
    if temp_c < 13:
        return f"Water {temp_c}°C — full 4/3 + booties + maybe a hood. Brain-freeze cold."
    if temp_c < 16:
        return f"Water {temp_c}°C — full 4/3 wetsuit, booties recommended. You'll feel it."
    if temp_c < 19:
        return f"Water {temp_c}°C — 3/2 wetsuit is the sweet spot."
    if temp_c < 22:
        return f"Water {temp_c}°C — 2mm shorty or springsuit. 3/2 if you run cold."
    return f"Water {temp_c}°C — boardshorts. Lucky you."


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

# Per-level headlines so a "skip" message reflects the *user's* range,
# not a generic "out of range" string.
SKIP_HEADLINES = {
    "beginner": {
        "Height":    "the swell is too big for your level today",
        "Period":    "the swell is carrying too much power for your level",
        "Wind":      "the wind is killing wave shape",
        "Direction": "the swell angle is wrong for this break",
        "Tide":      "the tide is outside this break's working window",
    },
    "improver": {
        "Height":    "the swell is bigger than your tier handles cleanly",
        "Period":    "the period is heavier than your tier should paddle into",
        "Wind":      "the wind is killing wave shape",
        "Direction": "the swell angle is wrong for this break",
        "Tide":      "the tide is outside this break's working window",
    },
    "intermediate": {
        "Height":    "the swell is into big-wave territory",
        "Period":    "the period is exceptional and behaves above its size",
        "Wind":      "the wind is killing wave shape",
        "Direction": "the swell angle is wrong for this break",
        "Tide":      "the tide is outside this break's working window",
    },
    "advanced": {
        "Height":    "the swell is into specialised big-wave territory",
        "Period":    "the period is exceptional — this swell punches way above its height",
        "Wind":      "the wind is killing wave shape",
        "Direction": "the swell angle is wrong for this break",
        "Tide":      "the tide is outside this break's working window",
    },
}

WEAK_HEADLINES = {
    "beginner": {
        "Height":    "swell size is on the edge of your range",
        "Period":    "the period is unusual (mushy or unusually heavy)",
        "Wind":      "the wind is messing with the shape",
        "Direction": "the swell angle is off for this break",
        "Tide":      "the tide is not ideal for this break",
    },
    "improver": {
        "Height":    "swell size is on the edge of your tier",
        "Period":    "the period is on the heavy side for your tier",
        "Wind":      "the wind is messing with the shape",
        "Direction": "the swell angle is off for this break",
        "Tide":      "the tide is not ideal for this break",
    },
    "intermediate": {
        "Height":    "swell size is at the upper end of your comfort range",
        "Period":    "the period is heavier than usual",
        "Wind":      "the wind is messing with the shape",
        "Direction": "the swell angle is off for this break",
        "Tide":      "the tide is not ideal for this break",
    },
    "advanced": {
        "Height":    "swell size is pushing into serious overhead-plus territory",
        "Period":    "the period is long — treat it as one size heavier than listed",
        "Wind":      "the wind is messing with the shape",
        "Direction": "the swell angle is off for this break",
        "Tide":      "the tide is not ideal for this break",
    },
}


def verdict(data, level=DEFAULT_LEVEL, spot=None):
    """Grade conditions for a given skill level and (optionally) spot config.

    spot dict may contain optimal_swell_bearing, optimal_swell_label, and tide_window.
    """
    level = _normalize_level(level)
    spot = spot or {}
    grades = [
        ("Height",    grade_height(data.get("height_m"), level)),
        ("Period",    grade_period(data.get("period_s"), level)),
        ("Wind",      grade_wind(data.get("wind_state"), level)),
        ("Direction", grade_direction(
            data.get("swell_direction"),
            spot.get("optimal_swell_bearing"),
            spot.get("optimal_swell_label"),
        )),
        ("Tide",      grade_tide(data.get("tide"), spot.get("tide_window"))),
    ]

    colors  = [color for _, (color, _) in grades]
    reds    = [label for label, (color, _) in grades if color == "red"]
    yellows = [label for label, (color, _) in grades if color == "yellow"]

    skip_headlines = SKIP_HEADLINES[level]
    weak_headlines = WEAK_HEADLINES[level]

    if reds:
        overall = "skip"
        primary = reds[0]
        headline = skip_headlines.get(primary, f"{primary.lower()} is out of range")
        if len(reds) > 1:
            verdict_text = (
                f"🔴 SKIP — {headline}, and {' / '.join(r.lower() for r in reds[1:])} "
                f"compound the problem. Don't paddle out today."
            )
        else:
            verdict_text = (
                f"🔴 SKIP — {headline}. Don't paddle out — find another spot, "
                f"watch from the beach, or save it for another day."
            )
    elif len(yellows) >= 2:
        overall = "maybe"
        problems = " and ".join(y.lower() for y in yellows[:2])
        verdict_text = (
            f"🟡 MAYBE — {problems} are both compromised. Workable but not great. "
            f"Check the webcam before driving down; if the lineup looks clean, "
            f"give it an hour."
        )
    elif yellows:
        overall = "go"
        weak = yellows[0]
        headline = weak_headlines.get(weak, f"{weak.lower()} is the weak link")
        verdict_text = f"🟢 GO — mostly clean, but {headline}. Read the bullet below before paddling out."
    elif colors.count("unknown") == len(colors):
        overall = "empty"
        verdict_text = (
            "⚪ Couldn't read any parameters from the page. Either surf-forecast.com "
            "is down or they changed their HTML. Try again in a few minutes."
        )
    else:
        overall = "go"
        verdict_text = "🟢 GO — clean conditions across the board. Get out there."

    out = {
        "verdict": overall,
        "verdict_text": verdict_text,
        "level": level,
        "details": [
            {"label": label, "color": color, "explanation": explanation}
            for label, (color, explanation) in grades
        ],
    }
    wet = wetsuit_advice(data.get("sea_temp_c"))
    if wet:
        out["wetsuit"] = wet
    return out


# ---------------------------------------------------------------------------
# Manual smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    scenarios = {
        "1.8m_13s_offshore": {
            "height_m": 1.8, "period_s": 13, "swell_direction": "WNW",
            "wind_state": "offshore", "rating": 8, "sea_temp_c": 16.0,
        },
        "perfect_small_day": {
            "height_m": 1.0, "period_s": 11, "swell_direction": "W",
            "wind_state": "offshore", "rating": 7, "sea_temp_c": 17.0,
        },
        "trash_onshore": {
            "height_m": 1.2, "period_s": 7, "swell_direction": "WNW",
            "wind_state": "onshore", "rating": 2, "sea_temp_c": 16.0,
        },
        "scraper_failed": {
            "height_m": None, "period_s": None, "wind_state": None,
        },
    }

    for level in VALID_LEVELS:
        for name, data in scenarios.items():
            print(f"\n=== [{level}] {name} ===")
            print(json.dumps(verdict(data, level), indent=2))
