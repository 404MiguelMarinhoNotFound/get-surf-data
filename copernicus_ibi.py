"""
Copernicus Marine IBI Wave Forecast client.

Iberia-Biscay-Ireland regional MFWAM, ECMWF wind-forced. Hourly grid at ~1/36 deg.
Product: IBI_ANALYSISFORECAST_WAV_005_005

We hit the WMS GetFeatureInfo endpoint over HTTPS with HTTP Basic Auth, one request
per layer for the current hour. Returns a small JSON/XML payload per call so it
fits Vercel's stdlib + cold-start budget — no NetCDF/GRIB parsing.

Auth via env vars: COPERNICUS_USER, COPERNICUS_PASS. If unset, fetch returns None
and the rest of the system carries on with SF + Open-Meteo only.
"""
import base64
import json
import math
import os
import re
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Copernicus Marine WMTS endpoint. WMTS GetFeatureInfo returns a small JSON
# payload per layer + tile pixel. Layer IDs include the product / dataset path.
_WMTS_BASE = "https://wmts.marine.copernicus.eu/teroWmts"
_PRODUCT = "IBI_ANALYSISFORECAST_WAV_005_005"
_DATASET = "cmems_mod_ibi_wav_anfc_0.027deg_PT1H-i_202411"
_STYLE = "cmap:amp"
_TMS = "EPSG:4326"
_ZOOM = 6  # ~0.011 deg/pixel — well below the native 0.027 deg grid.
_TILE_PX = 256

# VHM0 (Hs), VTPK (peak period), VMDR (mean direction),
# VHM0_SW1/VTM01_SW1/VMDR_SW1 (primary swell partition), VHM0_WW (wind sea Hs).
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
    n = 2 ** zoom  # tiles tall; tiles wide = 2 * n
    tile_deg = 180.0 / n  # tile spans tile_deg degrees in both lat and lon
    pixel_deg = tile_deg / _TILE_PX

    x = lon + 180.0
    y = 90.0 - lat
    col = int(x // tile_deg)
    row = int(y // tile_deg)
    i = int((x - col * tile_deg) / pixel_deg)
    j = int((y - row * tile_deg) / pixel_deg)
    # Clamp to tile bounds (edge case: lat/lon at exact tile boundary)
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
    """Pull the first numeric value out of a WMS GetFeatureInfo response.

    Copernicus returns JSON when INFO_FORMAT=application/json, but some servers
    fall back to XML/HTML. We try JSON first, then regex-scan for the first
    plausible number.
    """
    if not body:
        return None
    try:
        payload = json.loads(body)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        # GeoJSON FeatureCollection: features[].properties.value is the measurement.
        # We must only read that field — other props (lat, lon) are coords, not data.
        feats = payload.get("features") or []
        for f in feats:
            props = (f or {}).get("properties") or {}
            if "value" not in props:
                continue
            v = props.get("value")
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv == 9999.0 or fv < -9000:
                continue
            return fv
        # Some servers return {"value": x} at the top level.
        if "value" in payload:
            try:
                fv = float(payload["value"])
                if fv != 9999.0 and fv > -9000:
                    return fv
            except (TypeError, ValueError):
                pass
        # JSON parsed cleanly but had no usable value — don't regex-scan keys.
        return None

    # Non-JSON body: regex-scan for a numeric value, after a ">" or whitespace
    # to avoid matching digits embedded inside layer names like "VHM0".
    text = body if isinstance(body, str) else body.decode("utf-8", errors="ignore")
    for m in _NUM_RE.finditer(text):
        # Reject matches that are immediately preceded by a letter (e.g. "VHM0").
        start = m.start()
        if start > 0 and text[start - 1].isalpha():
            continue
        try:
            v = float(m.group(0))
        except ValueError:
            continue
        if v == 9999.0 or v < -9000:
            continue
        return v
    return None


def _shift_seaward(lat, lon, offshore_bearing_deg, dist_km=8.0):
    """Move (lat, lon) ~dist_km away from shore along the seaward direction.
    `offshore_bearing_deg` is the compass bearing pointing inland from the
    break, so the sea is at that bearing + 180."""
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


def fetch(lat, lon, when=None, offshore_bearing=None):
    """Fetch IBI wave variables at (lat, lon) for the given UTC datetime.

    Returns a dict shaped like open_meteo.fetch()'s 'current' so the same scoring
    code can consume it. Returns None if creds are missing or every layer failed.
    """
    headers = _auth_header()
    if headers is None:
        return None

    when = when or datetime.now(timezone.utc)
    when_iso = _round_to_hour(when).strftime("%Y-%m-%dT%H:00:00.000Z")

    def _fan_out(probe_lat, probe_lon):
        out = {}
        threads = []
        for key, layer in _LAYERS.items():
            t = threading.Thread(target=_fetch_layer, args=(layer, probe_lat, probe_lon, when_iso, headers, out, key))
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=_TIMEOUT_S + 2)
        return out

    used_lat, used_lon = lat, lon
    out = _fan_out(used_lat, used_lon)

    # Coastal points often land on grid cells masked as land. If the primary
    # Hs (VHM0) came back null, retry once with a seaward offset.
    if out.get("wave_height") is None and offshore_bearing is not None:
        used_lat, used_lon = _shift_seaward(lat, lon, offshore_bearing)
        out = _fan_out(used_lat, used_lon)

    if all(v is None for v in out.values()):
        return None

    current = {
        "timestamp_utc":     when_iso,
        "wave_height":       out.get("wave_height"),
        "wave_period":       out.get("wave_peak_period"),
        "wave_direction":    out.get("wave_direction"),
        "swell_height":      out.get("swell_height"),
        "swell_period":      out.get("swell_period"),
        "swell_direction":   out.get("swell_direction"),
        "swell_peak_period": out.get("wave_peak_period"),
        "wind_wave_height":  out.get("wind_wave_height"),
        # IBI does not expose wind directly here — leave None so the wind grader
        # falls through to the unknown branch (the OM source covers wind).
        "wind_speed":        None,
        "wind_direction":    None,
        "wind_gusts":        None,
        "air_temp":          None,
    }

    return {
        "current":     current,
        "today_hours": [],
        "hourly":      [],
        "fetched_at":  datetime.now(timezone.utc).isoformat(),
        "probe_point": {"lat": round(used_lat, 4), "lon": round(used_lon, 4),
                        "shifted_seaward": (used_lat, used_lon) != (lat, lon)},
    }
