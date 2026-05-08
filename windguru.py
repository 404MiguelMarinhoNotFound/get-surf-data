"""Windguru micro forecast parser.

The main Windguru pages are JS app shells. micro.windguru.cz provides a plain
HTML <pre> forecast that is stable enough to parse with stdlib only.
"""
import html as html_lib
import re
import urllib.request
from datetime import datetime, timedelta, timezone


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)
KTS_TO_KMH = 1.852

_WIND_VARS = "WSPD,WDIRN,WDEG,GUST,TMP"
_WAVE_VARS = (
    "HTSGW,WADIRN,WADEG,PERPW,SWELL1,SWDIRN1,SWDEG1,SWPER1,"
    "SWELL2,SWDIRN2,SWDEG2,SWPER2,WVHGT,WVDIRN,WVDEG,WVPER"
)


def _wind_url(spot_id, model="gfs"):
    return f"https://micro.windguru.cz/?s={spot_id}&m={model}&v={_WIND_VARS}"


def _wave_url(spot_id, model="gfswh"):
    return f"https://micro.windguru.cz/?s={spot_id}&m={model}&v={_WAVE_VARS}"

_ROW_RE = re.compile(r"^\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d+)\.\s+(\d+)h\s+(.+?)\s*$", re.IGNORECASE)


def fetch_text(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _pre_text(html):
    m = re.search(r"<pre[^>]*>(.*?)</pre>", html, re.IGNORECASE | re.DOTALL)
    raw = m.group(1) if m else html
    return html_lib.unescape(raw).replace("\r\n", "\n")


def _num(value):
    if value in (None, "-", ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value, ndigits=2):
    value = _num(value)
    return None if value is None else round(value, ndigits)


def _model_init(text):
    m = re.search(r"\(init:\s*(\d{4})-(\d{2})-(\d{2})\s+(\d{2})\s+UTC\)", text)
    if not m:
        return None
    y, mo, d, h = map(int, m.groups())
    return datetime(y, mo, d, h, tzinfo=timezone.utc)


def _utc_offset(text):
    m = re.search(r"\(UTC([+-]\d+)\)", text)
    return int(m.group(1)) if m else 0


def _sst(text):
    m = re.search(r"\bSST:\s*([\d.]+)\s*C\b", text, re.IGNORECASE)
    return _round(m.group(1), 1) if m else None


def _anchor_date(init_dt, first_day_num, offset_hours):
    if init_dt is None:
        init_dt = datetime.now(timezone.utc)
    local = init_dt.astimezone(timezone(timedelta(hours=offset_hours)))
    date = local.date()
    for delta in range(0, 35):
        candidate = date + timedelta(days=delta)
        if candidate.day == first_day_num:
            return candidate
    return date


def _parse_rows(text, columns):
    text = _pre_text(text)
    init_dt = _model_init(text)
    offset_hours = _utc_offset(text)
    rows = []
    parsed = []
    for line in text.splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        _dow, day_num, hour, rest = m.groups()
        parsed.append((int(day_num), int(hour), rest.split()))
    if not parsed:
        return [], {"model_init_utc": init_dt.isoformat() if init_dt else None, "sst_c": _sst(text)}

    current_date = _anchor_date(init_dt, parsed[0][0], offset_hours)
    previous_day = parsed[0][0]
    local_tz = timezone(timedelta(hours=offset_hours))
    for day_num, hour, values in parsed:
        if day_num != previous_day:
            current_date = current_date + timedelta(days=1)
            previous_day = day_num
        local_dt = datetime(
            current_date.year, current_date.month, current_date.day,
            hour, 0, tzinfo=local_tz,
        )
        row = {
            "timestamp_utc": local_dt.astimezone(timezone.utc).isoformat(),
            "windguru_local_day": day_num,
            "windguru_local_hour": hour,
        }
        for key, value in zip(columns, values):
            row[key] = value
        rows.append(row)

    meta = {
        "model_init_utc": init_dt.isoformat() if init_dt else None,
        "sst_c": _sst(text),
        "utc_offset_hours": offset_hours,
    }
    return rows, meta


def parse_wind(text):
    rows, meta = _parse_rows(text, ["wspd_kts", "wdirn", "wdeg", "gust_kts", "tmp_c"])
    out = []
    for row in rows:
        wspd = _num(row.get("wspd_kts"))
        gust = _num(row.get("gust_kts"))
        parsed = {
            "timestamp_utc": row["timestamp_utc"],
            "wind_speed_kmh": _round(wspd * KTS_TO_KMH if wspd is not None else None, 2),
            "wind_direction": row.get("wdirn") if row.get("wdirn") != "-" else None,
            "wind_direction_deg": _round(row.get("wdeg"), 1),
            "wind_gusts_kmh": _round(gust * KTS_TO_KMH if gust is not None else None, 2),
            "temperature_c": _round(row.get("tmp_c"), 1),
        }
        out.append({k: v for k, v in parsed.items() if v is not None})
    return out, meta


def parse_wave(text):
    rows, meta = _parse_rows(text, [
        "htsgw", "wadirn", "wadeg", "perpw",
        "swell1", "swdirn1", "swdeg1", "swper1",
        "swell2", "swdirn2", "swdeg2", "swper2",
        "wvhgt", "wvdirn", "wvdeg", "wvper",
    ])
    out = []
    for row in rows:
        parsed = {
            "timestamp_utc": row["timestamp_utc"],
            "wave_height": _round(row.get("htsgw"), 2),
            "wave_period": _round(row.get("perpw"), 1),
            "wave_direction": _round(row.get("wadeg"), 1),
            "swell_height": _round(row.get("swell1"), 2),
            "swell_period": _round(row.get("swper1"), 1),
            "swell_direction": _round(row.get("swdeg1"), 1),
            "swell2_height": _round(row.get("swell2"), 2),
            "swell2_period": _round(row.get("swper2"), 1),
            "swell2_direction": _round(row.get("swdeg2"), 1),
            "wind_wave_height": _round(row.get("wvhgt"), 2),
            "wind_wave_period": _round(row.get("wvper"), 1),
            "wind_wave_direction": _round(row.get("wvdeg"), 1),
        }
        out.append({k: v for k, v in parsed.items() if v is not None})
    return out, meta


def _merge_by_time(wind_rows, wave_rows):
    rows = {}
    for row in wave_rows:
        rows.setdefault(row["timestamp_utc"], {}).update(row)
    for row in wind_rows:
        rows.setdefault(row["timestamp_utc"], {}).update(row)
    return [rows[k] for k in sorted(rows)]


def _nearest(rows, now_utc):
    best = None
    best_diff = None
    for row in rows or []:
        try:
            dt = datetime.fromisoformat(row["timestamp_utc"])
        except (KeyError, ValueError):
            continue
        diff = abs((dt - now_utc).total_seconds())
        if best_diff is None or diff < best_diff:
            best = row
            best_diff = diff
    return best


def parse(wind_html, wave_html, now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    wind_rows, wind_meta = parse_wind(wind_html)
    wave_rows, wave_meta = parse_wave(wave_html)
    hourly = _merge_by_time(wind_rows, wave_rows)
    current = dict(_nearest(hourly, now_utc) or {})
    if current:
        current["windguru_fetched_at"] = now_utc.isoformat()
    return {
        "fetched_at": now_utc.isoformat(),
        "model_init_utc": wave_meta.get("model_init_utc") or wind_meta.get("model_init_utc"),
        "sst_c": wave_meta.get("sst_c") if wave_meta.get("sst_c") is not None else wind_meta.get("sst_c"),
        "current": current,
        "hourly": hourly,
    }


def fetch(spot_id, now_utc=None, wind_model="gfs", wave_model="gfswh", source_name="windguru"):
    wind_html = fetch_text(_wind_url(spot_id, wind_model))
    wave_html = fetch_text(_wave_url(spot_id, wave_model))
    payload = parse(wind_html, wave_html, now_utc=now_utc)
    payload["source"] = source_name
    payload["model"] = {"wind": wind_model, "wave": wave_model}
    return payload
