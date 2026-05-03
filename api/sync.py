import json
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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

ROOT = Path(__file__).resolve().parent.parent
SPOTS = json.loads((ROOT / "spots.json").read_text(encoding="utf-8"))


def _get_spot(spot_id):
    return next((s for s in SPOTS if s["id"] == spot_id), None)


def _sync_spot(spot_id, level=explainer.DEFAULT_LEVEL):
    spot = _get_spot(spot_id)
    if not spot:
        return {"error": f"Unknown spot id: {spot_id}", "spot_id": spot_id}

    if level not in explainer.VALID_LEVELS:
        level = explainer.DEFAULT_LEVEL

    sf_result, om_result, gfs_result, ibi_result = [None], [None], [None], [None]
    surfline_result, windguru_result = [None], [None]
    sf_error, om_error, gfs_error, ibi_error = [None], [None], [None], [None]
    surfline_error, windguru_error = [None], [None]

    def fetch_sf():
        try:
            sf_result[0] = scraper.scrape(spot["url"], tz_name=spot.get("tz"))
        except Exception as e:
            sf_error[0] = str(e)

    def fetch_surfline():
        sl_id = spot.get("surfline_spot_id")
        if not sl_id:
            surfline_error[0] = "No Surfline spot id configured"
            return
        try:
            surfline_result[0] = surfline.fetch(sl_id, source_url=spot.get("surfline_url"))
        except Exception as e:
            surfline_error[0] = str(e)

    def fetch_windguru():
        wg_id = spot.get("windguru_spot_id")
        if not wg_id:
            windguru_error[0] = "No Windguru spot id configured"
            return
        try:
            windguru_result[0] = windguru.fetch(wg_id)
        except Exception as e:
            windguru_error[0] = str(e)

    def fetch_om():
        lat, lon = spot.get("lat"), spot.get("lon")
        if lat is None or lon is None:
            om_error[0] = "No lat/lon configured for spot"
            return
        try:
            om_result[0] = open_meteo.fetch(lat, lon)
        except Exception as e:
            om_error[0] = str(e)

    def fetch_ibi():
        lat, lon = spot.get("lat"), spot.get("lon")
        if lat is None or lon is None:
            ibi_error[0] = "No lat/lon configured for spot"
            return
        try:
            ibi_result[0] = copernicus_ibi.fetch(lat, lon, offshore_bearing=spot.get("offshore_bearing"))
            if ibi_result[0] is None:
                ibi_error[0] = "Copernicus credentials missing or no data returned"
        except Exception as e:
            ibi_error[0] = str(e)

    def fetch_gfs():
        lat, lon = spot.get("lat"), spot.get("lon")
        if lat is None or lon is None:
            gfs_error[0] = "No lat/lon configured for spot"
            return
        try:
            gfs_result[0] = noaa_gfs.fetch(lat, lon)
        except Exception as e:
            gfs_error[0] = str(e)

    threads = [
        threading.Thread(target=fetch_sf),
        threading.Thread(target=fetch_surfline),
        threading.Thread(target=fetch_windguru),
        threading.Thread(target=fetch_om),
        threading.Thread(target=fetch_gfs),
        threading.Thread(target=fetch_ibi),
    ]
    for t in threads:
        t.start()
    threads[0].join(timeout=25)
    threads[1].join(timeout=15)
    threads[2].join(timeout=15)
    threads[3].join(timeout=15)
    threads[4].join(timeout=15)
    threads[5].join(timeout=15)

    if sf_error[0] or sf_result[0] is None:
        return {
            "error": f"Couldn't fetch forecast: {sf_error[0]}",
            "spot_id": spot["id"],
            "spot_name": spot["name"],
            "url": spot["url"],
        }

    data = sf_result[0]
    data["spot_id"] = spot["id"]
    data["spot_name"] = spot["name"]
    data.update(explainer.verdict(data, level, spot))

    # Grade today's M/A/E slots (height+period only; wind unknown per slot).
    for slot in data.get("today_slots", []):
        slot_data = {"height_m": slot.get("height_m"), "period_s": slot.get("period_s")}
        v = explainer.verdict(slot_data, level)
        slot["verdict"] = v["verdict"]

    # Merge Open-Meteo analysis.
    if om_result[0] and not om_error[0]:
        om = om_result[0]
        data["om_analysis"] = open_meteo_explainer.interpret_all(
            current=om.get("current"),
            today_hours=om.get("today_hours", []),
            sf_height_m=data.get("height_m"),
            optimal_bearing=spot.get("optimal_swell_bearing"),
            offshore_bearing=spot.get("offshore_bearing"),
            optimal_label=spot.get("optimal_swell_label"),
            level=level,
        )
        data["om_error"] = None
    else:
        data["om_analysis"] = None
        data["om_error"] = om_error[0] or "Open-Meteo fetch failed"

    om_hourly = om_result[0].get("hourly", []) if om_result[0] else []

    # Merge Surfline analysis.
    if surfline_result[0] and not surfline_error[0]:
        data["surfline_analysis"] = surfline_result[0].get("current")
        data["surfline_hourly"] = surfline_result[0].get("hourly", [])
        data["surfline_error"] = None
    else:
        data["surfline_analysis"] = None
        data["surfline_hourly"] = []
        data["surfline_error"] = surfline_error[0] or "Surfline fetch failed"

    # Merge Windguru analysis.
    if windguru_result[0] and not windguru_error[0]:
        data["windguru_analysis"] = windguru_result[0].get("current")
        data["windguru_hourly"] = windguru_result[0].get("hourly", [])
        data["windguru_error"] = None
        if windguru_result[0].get("sst_c") is not None:
            data["windguru_sst_c"] = windguru_result[0].get("sst_c")
    else:
        data["windguru_analysis"] = None
        data["windguru_hourly"] = []
        data["windguru_error"] = windguru_error[0] or "Windguru fetch failed"

    # Merge NOAA GFS analysis (independent wave + wind model).
    if gfs_result[0] and not gfs_error[0]:
        gfs = gfs_result[0]
        data["gfs_analysis"] = noaa_gfs_explainer.interpret_all(
            current=gfs.get("current"),
            optimal_bearing=spot.get("optimal_swell_bearing"),
            offshore_bearing=spot.get("offshore_bearing"),
            optimal_label=spot.get("optimal_swell_label"),
            level=level,
        )
        data["gfs_error"] = None
    else:
        data["gfs_analysis"] = None
        data["gfs_error"] = gfs_error[0] or "NOAA GFS fetch failed"

    gfs_hourly = gfs_result[0].get("hourly", []) if gfs_result[0] else []

    # Merge Copernicus IBI analysis (third weighted source).
    if ibi_result[0] and not ibi_error[0]:
        data["ibi_analysis"] = copernicus_ibi_explainer.interpret_all(
            current=ibi_result[0].get("current"),
            optimal_bearing=spot.get("optimal_swell_bearing"),
            offshore_bearing=spot.get("offshore_bearing"),
            optimal_label=spot.get("optimal_swell_label"),
            level=level,
        )
        data["ibi_error"] = None
    else:
        data["ibi_analysis"] = None
        data["ibi_error"] = ibi_error[0] or "Copernicus IBI fetch failed"

    data["unified"] = unified_explainer.unify(
        sf_data=data,
        om_analysis=data.get("om_analysis"),
        om_hourly=om_hourly,
        spot=spot,
        level=level,
        ibi_analysis=data.get("ibi_analysis"),
        gfs_analysis=data.get("gfs_analysis"),
        gfs_hourly=gfs_hourly,
        surfline_analysis=data.get("surfline_analysis"),
        surfline_hourly=data.get("surfline_hourly"),
        windguru_analysis=data.get("windguru_analysis"),
        windguru_hourly=data.get("windguru_hourly"),
    )

    return data


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        spot_id = qs.get("spot", [None])[0]
        level = qs.get("level", [explainer.DEFAULT_LEVEL])[0]

        if not spot_id:
            self._send_json({"error": "missing 'spot' query param"}, status=400)
            return

        self._send_json(_sync_spot(spot_id, level))

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, s-maxage=60, stale-while-revalidate=300")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return
