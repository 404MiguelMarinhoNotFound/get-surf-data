"""Fetch upstream surf sources and build the existing forecast payload shape."""

import copy
import json
import threading
from pathlib import Path

import scraper
import explainer
import open_meteo
import open_meteo_explainer
import unified_explainer
import copernicus_ibi
import copernicus_ibi_explainer
import noaa_gfs
import noaa_gfs_explainer
import surfline
import windguru


ROOT = Path(__file__).resolve().parent
SPOTS = json.loads((ROOT / "spots.json").read_text(encoding="utf-8"))
ALL_LEVELS = ("beginner", "improver", "intermediate", "advanced")


def get_spot(spot_id):
    return next((s for s in SPOTS if s["id"] == spot_id), None)


def _source(data=None, error=None):
    return {"data": data, "error": error}


def fetch_sources_for_spot(spot):
    """Fetch all upstream sources once for a spot.

    Optional source failures are carried as errors so the existing weighting and
    unavailable-source behavior can continue. Surf-Forecast remains required by
    build_payload because it provides the base response shape.
    """
    results = {
        "sf": _source(),
        "om": _source(),
        "gfs": _source(),
        "ibi": _source(),
        "surfline": _source(),
        "windguru": _source(),
    }

    def fetch_sf():
        try:
            results["sf"] = _source(scraper.scrape(spot["url"], tz_name=spot.get("tz")))
        except Exception as e:
            results["sf"] = _source(error=str(e))

    def fetch_surfline():
        sl_id = spot.get("surfline_spot_id")
        if not sl_id:
            results["surfline"] = _source(error="No Surfline spot id configured")
            return
        try:
            results["surfline"] = _source(surfline.fetch(sl_id, source_url=spot.get("surfline_url")))
        except Exception as e:
            results["surfline"] = _source(error=str(e))

    def fetch_windguru():
        wg_id = spot.get("windguru_spot_id")
        if not wg_id:
            results["windguru"] = _source(error="No Windguru spot id configured")
            return
        try:
            results["windguru"] = _source(windguru.fetch(wg_id))
        except Exception as e:
            results["windguru"] = _source(error=str(e))

    def fetch_om():
        lat, lon = spot.get("lat"), spot.get("lon")
        if lat is None or lon is None:
            results["om"] = _source(error="No lat/lon configured for spot")
            return
        try:
            results["om"] = _source(open_meteo.fetch(lat, lon))
        except Exception as e:
            results["om"] = _source(error=str(e))

    def fetch_ibi():
        lat, lon = spot.get("lat"), spot.get("lon")
        if lat is None or lon is None:
            results["ibi"] = _source(error="No lat/lon configured for spot")
            return
        try:
            data = copernicus_ibi.fetch(lat, lon, offshore_bearing=spot.get("offshore_bearing"))
            if data is None:
                results["ibi"] = _source(error="Copernicus credentials missing or no data returned")
            else:
                results["ibi"] = _source(data)
        except Exception as e:
            results["ibi"] = _source(error=str(e))

    def fetch_gfs():
        lat, lon = spot.get("lat"), spot.get("lon")
        if lat is None or lon is None:
            results["gfs"] = _source(error="No lat/lon configured for spot")
            return
        try:
            results["gfs"] = _source(noaa_gfs.fetch(lat, lon))
        except Exception as e:
            results["gfs"] = _source(error=str(e))

    threads = [
        threading.Thread(target=fetch_sf),
        threading.Thread(target=fetch_surfline),
        threading.Thread(target=fetch_windguru),
        threading.Thread(target=fetch_om),
        threading.Thread(target=fetch_gfs),
        threading.Thread(target=fetch_ibi),
    ]
    for thread in threads:
        thread.start()
    for thread, timeout in zip(threads, (25, 15, 15, 15, 15, 15)):
        thread.join(timeout=timeout)

    return results


def build_payload(spot, sources, level=explainer.DEFAULT_LEVEL):
    if level not in explainer.VALID_LEVELS:
        level = explainer.DEFAULT_LEVEL

    sf = sources.get("sf", {})
    if sf.get("error") or sf.get("data") is None:
        return {
            "error": f"Couldn't fetch forecast: {sf.get('error')}",
            "spot_id": spot["id"],
            "spot_name": spot["name"],
            "url": spot["url"],
        }

    data = copy.deepcopy(sf["data"])
    data["spot_id"] = spot["id"]
    data["spot_name"] = spot["name"]
    data.update(explainer.verdict(data, level, spot))

    for slot in data.get("today_slots", []):
        slot_data = {"height_m": slot.get("height_m"), "period_s": slot.get("period_s")}
        verdict = explainer.verdict(slot_data, level)
        slot["verdict"] = verdict["verdict"]

    om = sources.get("om", {})
    om_data = om.get("data")
    if om_data and not om.get("error"):
        data["om_analysis"] = open_meteo_explainer.interpret_all(
            current=om_data.get("current"),
            today_hours=om_data.get("today_hours", []),
            sf_height_m=data.get("height_m"),
            optimal_bearing=spot.get("optimal_swell_bearing"),
            offshore_bearing=spot.get("offshore_bearing"),
            optimal_label=spot.get("optimal_swell_label"),
            level=level,
        )
        data["om_error"] = None
    else:
        data["om_analysis"] = None
        data["om_error"] = om.get("error") or "Open-Meteo fetch failed"
    om_hourly = om_data.get("hourly", []) if om_data else []

    surfline_source = sources.get("surfline", {})
    surfline_data = surfline_source.get("data")
    if surfline_data and not surfline_source.get("error"):
        data["surfline_analysis"] = surfline_data.get("current")
        data["surfline_hourly"] = surfline_data.get("hourly", [])
        data["surfline_error"] = None
    else:
        data["surfline_analysis"] = None
        data["surfline_hourly"] = []
        data["surfline_error"] = surfline_source.get("error") or "Surfline fetch failed"

    windguru_source = sources.get("windguru", {})
    windguru_data = windguru_source.get("data")
    if windguru_data and not windguru_source.get("error"):
        data["windguru_analysis"] = windguru_data.get("current")
        data["windguru_hourly"] = windguru_data.get("hourly", [])
        data["windguru_error"] = None
        if windguru_data.get("sst_c") is not None:
            data["windguru_sst_c"] = windguru_data.get("sst_c")
    else:
        data["windguru_analysis"] = None
        data["windguru_hourly"] = []
        data["windguru_error"] = windguru_source.get("error") or "Windguru fetch failed"

    gfs = sources.get("gfs", {})
    gfs_data = gfs.get("data")
    if gfs_data and not gfs.get("error"):
        data["gfs_analysis"] = noaa_gfs_explainer.interpret_all(
            current=gfs_data.get("current"),
            optimal_bearing=spot.get("optimal_swell_bearing"),
            offshore_bearing=spot.get("offshore_bearing"),
            optimal_label=spot.get("optimal_swell_label"),
            level=level,
        )
        data["gfs_error"] = None
    else:
        data["gfs_analysis"] = None
        data["gfs_error"] = gfs.get("error") or "NOAA GFS fetch failed"
    gfs_hourly = gfs_data.get("hourly", []) if gfs_data else []

    ibi = sources.get("ibi", {})
    ibi_data = ibi.get("data")
    if ibi_data and not ibi.get("error"):
        data["ibi_analysis"] = copernicus_ibi_explainer.interpret_all(
            current=ibi_data.get("current"),
            optimal_bearing=spot.get("optimal_swell_bearing"),
            offshore_bearing=spot.get("offshore_bearing"),
            optimal_label=spot.get("optimal_swell_label"),
            level=level,
        )
        data["ibi_error"] = None
    else:
        data["ibi_analysis"] = None
        data["ibi_error"] = ibi.get("error") or "Copernicus IBI fetch failed"
    ibi_hourly = ibi_data.get("hourly", []) if ibi_data else []
    data["ibi_hourly"] = ibi_hourly

    data["unified"] = unified_explainer.unify(
        sf_data=data,
        om_analysis=data.get("om_analysis"),
        om_hourly=om_hourly,
        spot=spot,
        level=level,
        ibi_analysis=data.get("ibi_analysis"),
        ibi_hourly=ibi_hourly,
        gfs_analysis=data.get("gfs_analysis"),
        gfs_hourly=gfs_hourly,
        surfline_analysis=data.get("surfline_analysis"),
        surfline_hourly=data.get("surfline_hourly"),
        windguru_analysis=data.get("windguru_analysis"),
        windguru_hourly=data.get("windguru_hourly"),
    )

    return data


def sync_spot(spot_id, level=explainer.DEFAULT_LEVEL):
    spot = get_spot(spot_id)
    if not spot:
        return {"error": f"Unknown spot id: {spot_id}", "spot_id": spot_id}
    return build_payload(spot, fetch_sources_for_spot(spot), level=level)


def build_all_level_payloads(spot, sources):
    payloads = {}
    for level in ALL_LEVELS:
        payloads[level] = build_payload(spot, sources, level=level)
    return payloads
