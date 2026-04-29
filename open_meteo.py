"""
Open-Meteo Marine + Weather API client.
Stdlib only: urllib.request, json, datetime.
"""
import json
import urllib.request
from datetime import datetime, timezone, timedelta

_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

_MARINE_VARS = ",".join([
    "wave_height", "wave_direction", "wave_period",
    "swell_wave_height", "swell_wave_direction", "swell_wave_period", "swell_wave_peak_period",
    "secondary_swell_wave_height", "secondary_swell_wave_direction", "secondary_swell_wave_period",
    "wind_wave_height", "wind_wave_direction", "wind_wave_period",
])
_WEATHER_VARS = "wind_speed_10m,wind_direction_10m,wind_gusts_10m,temperature_2m"


def _get(url: str, params: dict) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    full_url = f"{url}?{query}"
    with urllib.request.urlopen(full_url, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _zip_hourly(marine: dict, weather: dict) -> list[dict]:
    m = marine.get("hourly", {})
    w = weather.get("hourly", {})
    times = m.get("time", [])
    rows = []
    for i, t in enumerate(times):
        def mv(key, d=m, idx=i):
            v = d.get(key, [])
            return v[idx] if idx < len(v) else None
        def wv(key, d=w, idx=i):
            v = d.get(key, [])
            return v[idx] if idx < len(v) else None

        rows.append({
            "timestamp_utc": t + ":00+00:00" if len(t) == 16 else t,
            "wave_height":       mv("wave_height"),
            "wave_period":       mv("wave_period"),
            "wave_direction":    mv("wave_direction"),
            "swell_height":      mv("swell_wave_height"),
            "swell_period":      mv("swell_wave_period"),
            "swell_direction":   mv("swell_wave_direction"),
            "swell_peak_period": mv("swell_wave_peak_period"),
            "swell2_height":     mv("secondary_swell_wave_height"),
            "swell2_period":     mv("secondary_swell_wave_period"),
            "swell2_direction":  mv("secondary_swell_wave_direction"),
            "wind_wave_height":  mv("wind_wave_height"),
            "wind_wave_period":  mv("wind_wave_period"),
            "wind_wave_direction": mv("wind_wave_direction"),
            "wind_speed":        wv("wind_speed_10m"),
            "wind_direction":    wv("wind_direction_10m"),
            "wind_gusts":        wv("wind_gusts_10m"),
            "air_temp":          wv("temperature_2m"),
        })
    return rows


def _find_current(hourly: list[dict], now: datetime) -> dict | None:
    if not hourly:
        return None
    best = None
    best_diff = None
    for h in hourly:
        try:
            ts = datetime.fromisoformat(h["timestamp_utc"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            diff = abs((ts - now).total_seconds())
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best = h
        except (ValueError, KeyError):
            continue
    return best


def _today_hours(hourly: list[dict], now: datetime) -> list[dict]:
    today_date = now.date()
    result = []
    for h in hourly:
        try:
            ts = datetime.fromisoformat(h["timestamp_utc"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts.date() == today_date:
                result.append(h)
        except (ValueError, KeyError):
            continue
    return result


def fetch(lat: float, lon: float, now_utc: datetime | None = None) -> dict:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    common = {"latitude": lat, "longitude": lon, "timezone": "UTC", "forecast_days": 7}

    marine_raw = _get(_MARINE_URL, {**common, "hourly": _MARINE_VARS})
    weather_raw = _get(_WEATHER_URL, {**common, "hourly": _WEATHER_VARS, "wind_speed_unit": "kmh"})

    hourly = _zip_hourly(marine_raw, weather_raw)
    current = _find_current(hourly, now_utc)
    today = _today_hours(hourly, now_utc)

    return {
        "fetched_at": now_utc.isoformat(),
        "current": current,
        "today_hours": today,
        "hourly": hourly,
    }
