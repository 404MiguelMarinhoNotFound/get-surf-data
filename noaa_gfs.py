"""NOAA GFS Wave + Wind via Open-Meteo APIs.

Independent hourly forecast for consensus cross-checking against the default
Open-Meteo ECMWF/Copernicus blend. Uses the same field layout as open_meteo.py.
Stdlib only.
"""
from datetime import datetime, timezone

from open_meteo import _MARINE_URL, _MARINE_VARS, _WEATHER_VARS, _get, _zip_hourly, _find_current, _today_hours

_GFS_WEATHER_URL = "https://api.open-meteo.com/v1/gfs"
# The 0.16 degree grid handles Lisbon's coastal cells better than the 0.25
# degree grid, which can return zeroed wave fields at Caparica.
_GFS_WAVE_MODEL = "ncep_gfswave016"


def fetch(lat: float, lon: float, now_utc: datetime | None = None) -> dict:
    """Fetch NOAA GFS wave + GFS atmospheric wind for the given coordinates.

    Returns same shape as open_meteo.fetch(): {fetched_at, current, today_hours, hourly}.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    common = {"latitude": lat, "longitude": lon, "timezone": "UTC", "forecast_days": 7}
    marine_raw = _get(_MARINE_URL, {**common, "hourly": _MARINE_VARS, "models": _GFS_WAVE_MODEL})
    weather_raw = _get(
        _GFS_WEATHER_URL,
        {**common, "hourly": _WEATHER_VARS, "wind_speed_unit": "kmh", "cell_selection": "sea"},
    )

    hourly = _zip_hourly(marine_raw, weather_raw)
    current = _find_current(hourly, now_utc)
    today = _today_hours(hourly, now_utc)

    return {
        "fetched_at": now_utc.isoformat(),
        "current": current,
        "today_hours": today,
        "hourly": hourly,
        "model": {"marine": _GFS_WAVE_MODEL, "weather": "gfs"},
    }
