"""Scrape surf-forecast.com break pages for current conditions.

Stdlib-only. Pulls the human-readable summary sentence (most reliable)
and the sea temperature line. Returns a normalized dict.
"""
import json
import re
import urllib.request
import html as html_lib
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)

DIRECTION_MAP = {
    "north": "N",
    "north-northeast": "NNE",
    "northeast": "NE",
    "east-northeast": "ENE",
    "east": "E",
    "east-southeast": "ESE",
    "southeast": "SE",
    "south-southeast": "SSE",
    "south": "S",
    "south-southwest": "SSW",
    "southwest": "SW",
    "west-southwest": "WSW",
    "west": "W",
    "west-northwest": "WNW",
    "northwest": "NW",
    "north-northwest": "NNW",
}

TIMEZONE_OFFSETS = {
    "UTC": 0,
    "GMT": 0,
    "WET": 0,
    "WEST": 1,
}


def fetch_html(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def strip_tags(html):
    """Remove tags + scripts/styles, decode common entities, collapse whitespace."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_summary(text):
    """Extract the key parameters from the rendered text."""
    out = {}

    # e.g. "...is: 2.3m 14s primary swell from a West-northwest direction"
    m = re.search(
        r"is:\s*([\d.]+)\s*m\s+(\d+)\s*s\s+primary\s+swell\s+from\s+a\s+([A-Za-z-]+)\s+direction",
        text,
        re.IGNORECASE,
    )
    if m:
        out["height_m"] = float(m.group(1))
        out["period_s"] = int(m.group(2))
        word = m.group(3).lower()
        out["swell_direction"] = DIRECTION_MAP.get(word, word.upper())

    # "wind direction is predicted to be cross-offshore"
    m = re.search(
        r"wind\s+direction\s+is\s+predicted\s+to\s+be\s+([\w-]+)",
        text,
        re.IGNORECASE,
    )
    if m:
        out["wind_state"] = m.group(1).lower()

    # "swell rating is 11"
    m = re.search(r"swell\s+rating\s+is\s+(\d+)", text, re.IGNORECASE)
    if m:
        out["rating"] = int(m.group(1))

    # "sea temperature is 14.0 C" or "sea temperature is 14.0° C"
    m = re.search(
        r"sea\s+temperature\s+is\s+([\d.]+)\s*(?:\u00b0|\u00c2\u00b0)?\s*C",
        text,
        re.IGNORECASE,
    )
    if m:
        out["sea_temp_c"] = float(m.group(1))

    return out


def parse_upstream_issued_at(text):
    """Return the surf-forecast issue timestamp as an ISO string, when present."""
    m = re.search(
        r"\bissued\s+(\d{1,2})\s*(am|pm)\s+"
        r"([A-Za-z]+)\s+(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\s+"
        r"(UTC|GMT|WET|WEST)\b",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None

    hour = int(m.group(1))
    meridiem = m.group(2).lower()
    day = int(m.group(4))
    month = m.group(5)[:3].title()
    year = int(m.group(6))
    tz_name = m.group(7).upper()

    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0

    tz = timezone(timedelta(hours=TIMEZONE_OFFSETS.get(tz_name, 0)), tz_name)
    issued = datetime.strptime(f"{day} {month} {year} {hour}", "%d %b %Y %H")
    return issued.replace(tzinfo=tz).isoformat()


def parse_today_slots(text):
    """Return today's Morning/Afternoon/Evening forecast blocks with height and period."""
    raw = re.findall(
        r'(Morning|Afternoon|Evening)\s*(?:\([^)]*\))?\s*'
        r'(?:(\d+\.?\d*)m\s+\(\d+\.?\d*ft\)\s+(\d+)s|(-)\s*-)',
        text,
        re.IGNORECASE,
    )
    slots = []
    for label, h_str, p_str, dash in raw:
        slots.append({
            "label": label.capitalize(),
            "height_m": float(h_str) if h_str else None,
            "period_s": int(p_str) if p_str else None,
        })
    return slots or None


def _hour24_from_label(time_str):
    """Convert "7AM"/"12PM" to 0..23."""
    hour = int(time_str[:-2])
    is_am = time_str.endswith("AM")
    return (hour % 12) + (0 if is_am else 12)


def _tod_label(hour24):
    if hour24 < 4:
        return "night"
    if hour24 < 8:
        return "dawn patrol"
    if hour24 < 12:
        return "morning"
    if hour24 < 17:
        return "afternoon"
    return "evening"


def _slot_counts_by_day(times, day_count, n_slots):
    """Group a Surf-Forecast time row into days by detecting midnight rollover."""
    counts = []
    current = 0
    previous_hour = None

    for h_str, mer in times[:n_slots]:
        hour = _hour24_from_label(f"{h_str}{mer.upper()}")
        if previous_hour is not None and hour < previous_hour:
            counts.append(current)
            current = 0
        current += 1
        previous_hour = hour

    if current:
        counts.append(current)

    if len(counts) > day_count > 0:
        return counts[:day_count - 1] + [sum(counts[day_count - 1:])]
    return counts


def _last_sunday(year, month):
    d = datetime(year, month, 28)
    while d.weekday() != 6:
        d += timedelta(days=1)
    return d.date()


def _eu_western_offset(now_utc):
    """EU summer-time offset for the WET/WEST zone (Lisbon, Dublin, etc.).

    DST starts last Sunday of March 01:00 UTC, ends last Sunday of October 01:00 UTC.
    Returns +1h during summer, +0h otherwise.
    """
    y = now_utc.year
    start = datetime(y, 3, _last_sunday(y, 3).day, 1, tzinfo=timezone.utc)
    end = datetime(y, 10, _last_sunday(y, 10).day, 1, tzinfo=timezone.utc)
    return timedelta(hours=1 if start <= now_utc < end else 0)


_FALLBACK_TZ_RULES = {
    "Europe/Lisbon": _eu_western_offset,
    "Europe/London": _eu_western_offset,
    "Atlantic/Faroe": _eu_western_offset,
}


def _spot_tz(tz_name, now_utc=None):
    """Return a tzinfo for `tz_name`, falling back when system tzdata is missing.

    Uses zoneinfo when available; otherwise uses a hardcoded DST rule for the
    handful of zones we ship spots for. Returns None when neither path works.
    """
    if not tz_name:
        return None
    if ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    rule = _FALLBACK_TZ_RULES.get(tz_name)
    if rule is None:
        return None
    offset = rule(now_utc or datetime.now(timezone.utc))
    return timezone(offset, tz_name)


def parse_rating_timeline(text, now_utc=None, tz_name=None):
    """Parse the 3-hourly site rating grid and compute a best-window hint.

    Each cell is tagged with `timestamp_utc` when `tz_name` is supplied
    (surf-forecast.com renders times in spot-local tz). The first day in the
    grid is the day of the scrape; subsequent days roll forward.

    Returns {"labeled": [...], "best_window": str|None} or None if not found.
    """
    m = re.search(
        r'((?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+\d+\s*)+)'  # day headers
        r'((?:\d+\s*(?:AM|PM)\s*)+)'                            # time slots
        r'Rating\s*\(10\s*max\)\s*((?:\d+\s*)+)',               # ratings
        text,
        re.IGNORECASE,
    )
    if not m:
        return None

    days = re.findall(r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+(\d+)', m.group(1), re.IGNORECASE)
    times = re.findall(r'(\d+)\s*(AM|PM)', m.group(2), re.IGNORECASE)
    ratings = list(map(int, m.group(3).split()))

    n_slots = min(len(times), len(ratings))
    slots_per_day = _slot_counts_by_day(times, len(days), n_slots)

    spot_tz = _spot_tz(tz_name, now_utc=now_utc)
    base_local_date = None
    if spot_tz is not None:
        anchor = (now_utc or datetime.now(timezone.utc)).astimezone(spot_tz)
        base_local_date = anchor.date()
        # The grid's first day-num matches the spot-local date of the scrape.
        if days:
            first_day_num = int(days[0][1])
            if first_day_num != base_local_date.day:
                # Edge: scrape happened just past midnight upstream — back off a day.
                base_local_date = base_local_date - timedelta(days=1)

    labeled, idx = [], 0
    last_day_num = None
    rolling_date = base_local_date
    for (day_abbr, day_num_str), count in zip(days, slots_per_day):
        day_num = int(day_num_str)
        if rolling_date is not None:
            if last_day_num is not None and day_num != last_day_num:
                rolling_date = rolling_date + timedelta(days=1)
            last_day_num = day_num
        for _ in range(count):
            if idx >= n_slots:
                break
            h_str, mer = times[idx]
            time_label = f"{h_str}{mer.upper()}"
            cell = {
                "day": f"{day_abbr} {day_num}",
                "time": time_label,
                "rating": ratings[idx],
            }
            if rolling_date is not None and spot_tz is not None:
                hour24 = _hour24_from_label(time_label)
                local_dt = datetime(
                    rolling_date.year, rolling_date.month, rolling_date.day,
                    hour24, 0, tzinfo=spot_tz,
                )
                cell["timestamp_utc"] = local_dt.astimezone(timezone.utc).isoformat()
            idx += 1
            labeled.append(cell)

    if not labeled:
        return None

    best_window = pick_best_window(labeled, now_utc=now_utc)
    return {"labeled": labeled, "best_window": best_window}


def pick_best_window(labeled, now_utc=None, min_rating=2):
    """Pick the highest-rated upcoming cell, anchored to UTC `now_utc`.

    A cell is "upcoming" if its `timestamp_utc` is at or after `now_utc - 1h`
    (keeps the in-progress slot in play). When no cell carries a timestamp
    (older payloads / no tz configured), falls back to the global max.
    Returns a string like "Tue 28 morning (7AM, site rating 5/10)" or None.
    """
    if not labeled:
        return None

    now_utc = now_utc or datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=1)

    timestamped = [c for c in labeled if c.get("timestamp_utc")]
    if timestamped:
        future = [
            c for c in timestamped
            if datetime.fromisoformat(c["timestamp_utc"]) >= cutoff
        ]
        pool = future or timestamped[-8:]  # all-past fallback: last day-ish
    else:
        pool = labeled

    max_r = max(c["rating"] for c in pool)
    if max_r < min_rating:
        return None
    best = next(c for c in pool if c["rating"] == max_r)
    tod = _tod_label(_hour24_from_label(best["time"]))
    return f"{best['day']} {tod} ({best['time']}, site rating {max_r}/10)"


def _parse_tide_time(time_str, meridiem):
    hour_str, minute_str = time_str.split(":", 1)
    hour = int(hour_str)
    minute = int(minute_str)
    meridiem = meridiem.upper()
    if meridiem == "PM" and hour != 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    return hour, minute


def _format_duration(minutes):
    minutes = max(0, int(round(minutes)))
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _parse_tide_row(text, kind, base_date, tzinfo):
    row = re.search(
        rf"\b{kind}\s+Tide\s+(.*?)(?=\b(?:High|Low)\s+Tide\b|Weather\s+Surf\s+Details|Sunrise\b|$)",
        text,
        re.IGNORECASE,
    )
    if not row:
        return []

    events = []
    current_date = base_date
    previous_dt = None
    for time_str, meridiem, height_str in re.findall(
        r"(\d{1,2}:\d{2})\s*(AM|PM)\s+([\d.]+)\s*m\b",
        row.group(1),
        re.IGNORECASE,
    ):
        hour, minute = _parse_tide_time(time_str, meridiem)
        event_dt = datetime(
            current_date.year,
            current_date.month,
            current_date.day,
            hour,
            minute,
            tzinfo=tzinfo,
        )
        if previous_dt and event_dt <= previous_dt:
            event_dt += timedelta(days=1)
            current_date = event_dt.date()
        previous_dt = event_dt
        events.append({
            "type": kind.lower(),
            "time": event_dt.isoformat(),
            "height_m": float(height_str),
        })
    return events


def parse_tides(text, now=None):
    """Parse tide turns and estimate the current tide.

    surf-forecast.com exposes this in text like:
    "High Tide 1:06AM 2.57m Low Tide 6:56AM 1.01m".
    The table is sequential but usually omits the date beside each tide, so
    dates are inferred by rolling forward when times wrap past midnight.
    """
    now = now or datetime.now().astimezone()
    base_date = now.date()

    events = (
        _parse_tide_row(text, "High", base_date, now.tzinfo)
        + _parse_tide_row(text, "Low", base_date, now.tzinfo)
    )

    if not events:
        # Fallback for pages that repeat the "High/Low Tide" label before
        # every time/height pair.
        matches = list(re.finditer(
            r"\b(High|Low)\s+Tide\s+(\d{1,2}:\d{2})\s*(AM|PM)\s+([\d.]+)\s*m\b",
            text,
            re.IGNORECASE,
        ))
    else:
        matches = []

    if not events and not matches:
        return None

    if matches:
        current_date = base_date
        previous_dt = None
        for match in matches[:16]:
            kind = match.group(1).lower()
            hour, minute = _parse_tide_time(match.group(2), match.group(3))
            event_dt = datetime(
                current_date.year,
                current_date.month,
                current_date.day,
                hour,
                minute,
                tzinfo=now.tzinfo,
            )
            if previous_dt and event_dt <= previous_dt:
                event_dt += timedelta(days=1)
                current_date = event_dt.date()
            previous_dt = event_dt
            events.append({
                "type": kind,
                "time": event_dt.isoformat(),
                "height_m": float(match.group(4)),
            })

    events.sort(key=lambda event: event["time"])

    if not events:
        return None

    # If the table starts after the current clock time, synthesize a previous
    # turn by moving the first event back one semi-diurnal tide cycle.
    if now < datetime.fromisoformat(events[0]["time"]):
        first = events[0]
        previous_kind = "low" if first["type"] == "high" else "high"
        previous_time = datetime.fromisoformat(first["time"]) - timedelta(hours=6, minutes=12)
        previous = {
            "type": previous_kind,
            "time": previous_time.isoformat(),
            "height_m": first["height_m"],
        }
        events.insert(0, previous)

    previous_event = None
    next_event = None
    for event in events:
        event_dt = datetime.fromisoformat(event["time"])
        if event_dt <= now:
            previous_event = event
        elif next_event is None:
            next_event = event
            break

    if previous_event is None:
        previous_event = events[0]
    if next_event is None:
        return {
            "events": events[:8],
            "summary": "tide table found, but no upcoming turn was available",
        }

    prev_dt = datetime.fromisoformat(previous_event["time"])
    next_dt = datetime.fromisoformat(next_event["time"])
    total_seconds = max(1, (next_dt - prev_dt).total_seconds())
    elapsed_seconds = min(max(0, (now - prev_dt).total_seconds()), total_seconds)
    progress = elapsed_seconds / total_seconds
    prev_h = previous_event["height_m"]
    next_h = next_event["height_m"]
    height_m = prev_h + (next_h - prev_h) * progress
    state = "rising" if next_h > prev_h else "falling"

    low_h = min(prev_h, next_h)
    high_h = max(prev_h, next_h)
    range_m = high_h - low_h
    position = 0.5 if range_m <= 0 else (height_m - low_h) / range_m
    minutes_to_next = (next_dt - now).total_seconds() / 60
    next_type = "high" if next_event["type"] == "high" else "low"

    return {
        "height_m": round(height_m, 2),
        "state": state,
        "position": round(position, 2),
        "previous_turn": previous_event,
        "next_turn": next_event,
        "minutes_to_next_turn": int(round(minutes_to_next)),
        "summary": (
            f"{height_m:.1f}m, {state}, "
            f"{next_type} in {_format_duration(minutes_to_next)}"
        ),
        "events": events[:8],
    }


def annotate_cells_with_tide(labeled, tide_events):
    """Attach a tide_state ("rising"/"falling") and tide_height_m per cell.

    Linear interpolation between bracketing tide events. No-op when either
    `labeled` cells have no `timestamp_utc` or `tide_events` is empty.
    """
    if not labeled or not tide_events:
        return
    parsed_events = []
    for ev in tide_events:
        try:
            dt = datetime.fromisoformat(ev["time"])
        except (KeyError, ValueError):
            continue
        parsed_events.append((dt, ev["type"], float(ev["height_m"])))
    parsed_events.sort(key=lambda x: x[0])
    if len(parsed_events) < 2:
        return

    for cell in labeled:
        ts = cell.get("timestamp_utc")
        if not ts:
            continue
        cell_dt = datetime.fromisoformat(ts)
        prev = next_ = None
        for ev in parsed_events:
            if ev[0] <= cell_dt:
                prev = ev
            elif next_ is None:
                next_ = ev
                break
        if prev is None or next_ is None:
            continue
        prev_dt, _prev_kind, prev_h = prev
        next_dt, next_kind, next_h = next_
        span = max(1.0, (next_dt - prev_dt).total_seconds())
        progress = (cell_dt - prev_dt).total_seconds() / span
        height = prev_h + (next_h - prev_h) * progress
        cell["tide_height_m"] = round(height, 2)
        cell["tide_state"] = "rising" if next_kind == "high" else "falling"


def parse_swell_tooltips(html):
    """Parse per-hour forecast data from data-swell-tooltip JSON attributes.

    Returns a dict keyed by "Day DD_HH(AM|PM)" (e.g. "Tue 28_4PM") with
    primary swell height/period/direction and wind state for each cell.
    """
    out = {}
    for raw in re.findall(r'data-swell-tooltip="([^"]+)"', html):
        try:
            data = json.loads(html_lib.unescape(raw))
        except (ValueError, KeyError):
            continue
        date_str = data.get("date", "")
        m = re.match(r'(\w{3})\w*\s+(\d+)\s+(\d+)\s*(AM|PM)', date_str, re.IGNORECASE)
        if not m:
            continue
        key = f"{m.group(1).title()} {int(m.group(2))}_{m.group(3)}{m.group(4).upper()}"
        swells = [s for s in (data.get("swells") or []) if s]
        primary = swells[0] if swells else None
        if not primary:
            continue
        wind = (data.get("windState") or {}).get("text")
        out[key] = {
            "height_m": primary.get("height"),
            "period_s": primary.get("period"),
            "swell_direction": primary.get("letters"),
            "wind_state": wind,
        }
    return out


def scrape(url, tz_name=None):
    """Fetch a surf-forecast.com break page and return parsed conditions."""
    html = fetch_html(url)
    text = strip_tags(html)
    now_utc = datetime.now(timezone.utc)
    data = {
        "url": url,
        "fetched_at": now_utc.isoformat(),
        "now_utc": now_utc.isoformat(),
    }
    data.update(parse_summary(text))
    issued_at = parse_upstream_issued_at(text)
    if issued_at:
        data["upstream_issued_at"] = issued_at

    today_slots = parse_today_slots(text)
    if today_slots:
        data["today_slots"] = today_slots

    rt = parse_rating_timeline(text, now_utc=now_utc, tz_name=tz_name)
    if rt:
        if rt.get("best_window"):
            data["best_window"] = rt["best_window"]
        data["rating_timeline"] = rt.get("labeled", [])

    tide = parse_tides(text)
    if tide:
        data["tide"] = tide
        annotate_cells_with_tide(data.get("rating_timeline", []), tide.get("events"))

    tooltip_data = parse_swell_tooltips(html)
    if tooltip_data:
        for cell in data.get("rating_timeline", []):
            key = f"{cell['day']}_{cell['time']}"
            td = tooltip_data.get(key)
            if td:
                cell.update({k: v for k, v in td.items() if v is not None})

    return data


if __name__ == "__main__":
    import json
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else \
        "https://www.surf-forecast.com/breaks/Carcavelos/forecasts/latest"
    print(json.dumps(scrape(url), indent=2))
