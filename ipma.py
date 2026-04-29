"""
IPMA Portugal Oceanography client.

Fetches the official Portuguese daily sea forecast as a sanity envelope for our
blended hourly forecast. IPMA is daily/coarse — we use it ONLY to validate that
our blended Hs / period falls within the country's official daily range. It is
not a weighted score input.

Endpoint: https://api.ipma.pt/open-data/forecast/oceanography/daily/hp-daily-sea-forecast-dayN.json
No auth, free, returns JSON. Stdlib only.
"""
import json
import urllib.request
from datetime import datetime, timezone

_BASE = "https://api.ipma.pt/open-data/forecast/oceanography/daily/hp-daily-sea-forecast-day{}.json"


def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "lineup-surf/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _to_float(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _pick_local(payload, local_id):
    if not isinstance(payload, dict):
        return None
    rows = payload.get("data") or payload.get("forecast") or payload.get("oceanForecast") or []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("globalIdLocal")) == str(local_id) or str(row.get("idLocal")) == str(local_id):
                return row
    return None


def _normalize_day(row):
    if not row:
        return None

    def _f(*keys):
        for k in keys:
            if k in row:
                v = _to_float(row.get(k))
                if v is not None:
                    return v
        return None

    return {
        "wave_height_min_m": _f("waveHighMin", "wavePowerMin", "waveHeightMin", "hMin"),
        "wave_height_max_m": _f("waveHighMax", "wavePowerMax", "waveHeightMax", "hMax"),
        "wave_period_min_s": _f("wavePeriodMin", "tMin"),
        "wave_period_max_s": _f("wavePeriodMax", "tMax"),
        "wave_direction":    row.get("predWaveDir") or row.get("waveDir"),
        "sst_min_c":         _f("sstMin"),
        "sst_max_c":         _f("sstMax"),
    }


def fetch(local_id):
    """Fetch IPMA daily sea forecast for a coastal location.

    Returns: {"today": {...}, "tomorrow": {...}, "fetched_at": iso}
    Any individual day fetch may be None on failure — callers must handle.
    """
    if local_id is None:
        return None

    today = tomorrow = None
    try:
        today = _normalize_day(_pick_local(_get(_BASE.format(0)), local_id))
    except Exception:
        today = None
    try:
        tomorrow = _normalize_day(_pick_local(_get(_BASE.format(1)), local_id))
    except Exception:
        tomorrow = None

    if today is None and tomorrow is None:
        return None

    return {
        "today":      today,
        "tomorrow":   tomorrow,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "local_id":   local_id,
    }


def envelope_check(ipma_today, blended_height_m, blended_period_s, h_tol=0.30, p_tol=0.30):
    """Test whether blended values sit inside IPMA's official daily envelope.

    Returns: {"in_envelope": bool, "height_in_range": bool|None,
              "period_in_range": bool|None, "ipma_height": [min,max]|None,
              "ipma_period": [min,max]|None}

    h_tol/p_tol widen the IPMA range to account for spot-vs-coastal-cell offset
    (e.g. 0.30 = +/-30%). Score is never modified by this check; it only feeds
    the confidence label and a UI badge.
    """
    if not ipma_today:
        return None

    h_min = _to_float(ipma_today.get("wave_height_min_m"))
    h_max = _to_float(ipma_today.get("wave_height_max_m"))
    p_min = _to_float(ipma_today.get("wave_period_min_s"))
    p_max = _to_float(ipma_today.get("wave_period_max_s"))
    blended_h = _to_float(blended_height_m)
    blended_p = _to_float(blended_period_s)

    height_ok = period_ok = None
    h_range = p_range = None

    if h_min is not None and h_max is not None:
        lo = h_min * (1.0 - h_tol)
        hi = h_max * (1.0 + h_tol)
        h_range = [round(h_min, 2), round(h_max, 2)]
        if blended_h is not None:
            height_ok = lo <= blended_h <= hi

    if p_min is not None and p_max is not None:
        lo = p_min * (1.0 - p_tol)
        hi = p_max * (1.0 + p_tol)
        p_range = [round(p_min, 1), round(p_max, 1)]
        if blended_p is not None:
            period_ok = lo <= blended_p <= hi

    checks = [c for c in (height_ok, period_ok) if c is not None]
    in_env = all(checks) if checks else None

    return {
        "in_envelope":     in_env,
        "height_in_range": height_ok,
        "period_in_range": period_ok,
        "ipma_height":     h_range,
        "ipma_period":     p_range,
        "blended_height":  round(blended_h, 2) if blended_h is not None else None,
        "blended_period":  round(blended_p, 1) if blended_p is not None else None,
        "wave_direction":  ipma_today.get("wave_direction"),
        "sst_min_c":       ipma_today.get("sst_min_c"),
        "sst_max_c":       ipma_today.get("sst_max_c"),
    }
