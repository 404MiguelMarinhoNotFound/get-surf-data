"""
Copernicus Marine IBI Wave Forecast client.

Iberia-Biscay-Ireland regional MFWAM, ECMWF wind-forced. Hourly grid at ~1/36 deg.
Product: IBI_ANALYSISFORECAST_WAV_005_005

We hit the WMTS GetFeatureInfo endpoint over HTTPS with HTTP Basic Auth, one
request per layer/time. Returns small JSON/XML payloads so it fits the stdlib
runtime without NetCDF/GRIB parsing.

Auth via env vars: COPERNICUS_USER, COPERNICUS_PASS. If unset, fetch returns
None and the rest of the system carries on with the other sources.
"""
import base64
import json
import math
import os
import re
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone


_WMTS_BASE = "https://wmts.marine.copernicus.eu/teroWmts"
_PRODUCT = "IBI_ANALYSISFORECAST_WAV_005_005"
_DATASET = "cmems_mod_ibi_wav_anfc_0.027deg_PT1H-i_202411"
_STYLE = "cmap:amp"
_TMS = "EPSG:4326"
_ZOOM = 6
_TILE_PX = 256

_LAYERS = {
    "wave_height":      "VHM0",
    "wave_peak_period": "VTPK",
    "wave_direction":   "VMDR",
    "swell_height":     "VHM0_SW1",
    "swell_period":     "VTM01_SW1",
    "swell_direction":  "VMDR_SW1",
    "wind_wave_height": "VHM0_WW",
}

_TIMEOUT_S = 12
_DEFAULT_DAYS = 7
_MAX_HOURLY_WORKERS = 24
_HOURLY_BUDGET_S = 8


def _auth_header():
    user = os.environ.get("COPERNICUS_USER")
    pwd = os.environ.get("COPERNICUS_PASS")
    if not user or not pwd:
        return None
    token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _round_to_hour(dt):
    return dt.replace(minute=0, second=0, microsecond=0)


def _tile_coords(lat, lon, zoom=_ZOOM):
    """Convert (lat, lon) to WMTS EPSG:4326 (TileCol, TileRow, I, J)."""
    n = 2 ** zoom
    tile_deg = 180.0 / n
    pixel_deg = tile_deg / _TILE_PX

    x = lon + 180.0
    y = 90.0 - lat
    col = int(x // tile_deg)
    row = int(y // tile_deg)
    i = int((x - col * tile_deg) / pixel_deg)
    j = int((y - row * tile_deg) / pixel_deg)
    i = max(0, min(_TILE_PX - 1, i))
    j = max(0, min(_TILE_PX - 1, j))
    col = max(0, min(2 * n - 1, col))
    row = max(0, min(n - 1, row))
    return col, row, i, j


def _build_url(layer_var, lat, lon, when_iso):
    layer_id = f"{_PRODUCT}/{_DATASET}/{layer_var}"
    col, row, i, j = _tile_coords(lat, lon)
    params = {
        "SERVICE": "WMTS",
        "VERSION": "1.0.0",
        "REQUEST": "GetFeatureInfo",
        "LAYER": layer_id,
        "STYLE": _STYLE,
        "TILEMATRIXSET": _TMS,
        "TILEMATRIX": str(_ZOOM),
        "TILEROW": str(row),
        "TILECOL": str(col),
        "I": str(i),
        "J": str(j),
        "FORMAT": "image/png",
        "INFOFORMAT": "application/json",
        "TIME": when_iso,
    }
    return f"{_WMTS_BASE}?" + urllib.parse.urlencode(params)


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?")


def _extract_value(body):
    """Pull the first measurement value out of a WMTS GetFeatureInfo response."""
    if not body:
        return None
    try:
        payload = json.loads(body)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        feats = payload.get("features") or []
        for feat in feats:
            props = (feat or {}).get("properties") or {}
            if "value" not in props:
                continue
            try:
                value = float(props.get("value"))
            except (TypeError, ValueError):
                continue
            if value != 9999.0 and value > -9000:
                return value
        if "value" in payload:
            try:
                value = float(payload["value"])
            except (TypeError, ValueError):
                return None
            return value if value != 9999.0 and value > -9000 else None
        return None

    text = body if isinstance(body, str) else body.decode("utf-8", errors="ignore")
    for match in _NUM_RE.finditer(text):
        start = match.start()
        if start > 0 and text[start - 1].isalpha():
            continue
        try:
            value = float(match.group(0))
        except ValueError:
            continue
        if value != 9999.0 and value > -9000:
            return value
    return None


def _shift_seaward(lat, lon, offshore_bearing_deg, dist_km=8.0):
    """Move a coastal point seaward from the configured offshore bearing."""
    if offshore_bearing_deg is None:
        return lat, lon
    seaward = math.radians((float(offshore_bearing_deg) + 180.0) % 360.0)
    dlat = (dist_km / 111.0) * math.cos(seaward)
    dlon = (dist_km / (111.0 * max(0.1, math.cos(math.radians(lat))))) * math.sin(seaward)
    return lat + dlat, lon + dlon


def _fetch_layer(layer, lat, lon, when_iso, headers, out, key):
    try:
        req = urllib.request.Request(_build_url(layer, lat, lon, when_iso), headers=headers)
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        out[key] = _extract_value(body)
    except Exception:
        out[key] = None


def _fetch_layers_for_time(lat, lon, when_iso, headers):
    out = {}
    threads = []
    for key, layer in _LAYERS.items():
        thread = threading.Thread(target=_fetch_layer, args=(layer, lat, lon, when_iso, headers, out, key))
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join(timeout=_TIMEOUT_S + 2)
    return out


def _normalize_ibi_row(when_iso, out):
    return {
        "timestamp_utc":     when_iso,
        "wave_height":       out.get("wave_height"),
        "wave_period":       out.get("wave_peak_period"),
        "wave_direction":    out.get("wave_direction"),
        "swell_height":      out.get("swell_height"),
        "swell_period":      out.get("swell_period"),
        "swell_direction":   out.get("swell_direction"),
        "swell_peak_period": out.get("wave_peak_period"),
        "wind_wave_height":  out.get("wind_wave_height"),
        "wind_speed":        None,
        "wind_direction":    None,
        "wind_gusts":        None,
        "air_temp":          None,
    }


def fetch(lat, lon, when=None, offshore_bearing=None, days=_DEFAULT_DAYS):
    """Fetch IBI wave variables at (lat, lon).

    The return shape mirrors open_meteo.fetch(): current plus hourly model rows.
    Hourly rows are best-effort; if credentials are missing or all layers fail,
    returns None so callers can renormalize to the other sources.
    """
    headers = _auth_header()
    if headers is None:
        return None

    when = when or datetime.now(timezone.utc)
    when = _round_to_hour(when)
    when_iso = when.strftime("%Y-%m-%dT%H:00:00.000Z")

    used_lat, used_lon = lat, lon
    out = _fetch_layers_for_time(used_lat, used_lon, when_iso, headers)
    if out.get("wave_height") is None and offshore_bearing is not None:
        used_lat, used_lon = _shift_seaward(lat, lon, offshore_bearing)
        out = _fetch_layers_for_time(used_lat, used_lon, when_iso, headers)

    if all(value is None for value in out.values()):
        return None

    current = _normalize_ibi_row(when_iso, out)
    hourly = [current]
    total_hours = max(0, int(float(days or 0) * 24))
    hour_times = [
        (when + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:00:00.000Z")
        for offset in range(1, total_hours)
    ]

    def _hourly_row(hour_iso):
        hour_out = _fetch_layers_for_time(used_lat, used_lon, hour_iso, headers)
        if all(value is None for value in hour_out.values()):
            return None
        return _normalize_ibi_row(hour_iso, hour_out)

    if hour_times:
        hourly_budget = float(os.environ.get("COPERNICUS_HOURLY_BUDGET_S", _HOURLY_BUDGET_S))
        executor = ThreadPoolExecutor(max_workers=_MAX_HOURLY_WORKERS)
        futures = [executor.submit(_hourly_row, hour_iso) for hour_iso in hour_times]
        try:
            for future in as_completed(futures, timeout=hourly_budget):
                try:
                    row = future.result()
                except Exception:
                    row = None
                if row is not None:
                    hourly.append(row)
        except TimeoutError:
            pass
        finally:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
    hourly.sort(key=lambda row: row.get("timestamp_utc") or "")

    return {
        "current":     current,
        "today_hours": [],
        "hourly":      hourly,
        "fetched_at":  datetime.now(timezone.utc).isoformat(),
        "probe_point": {
            "lat": round(used_lat, 4),
            "lon": round(used_lon, 4),
            "shifted_seaward": (used_lat, used_lon) != (lat, lon),
        },
    }
