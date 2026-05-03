"""Local HTTP server for Lineup.

Run:  python3 server.py
Open: http://localhost:8765

Stdlib only. Caches scraped data per-spot for 60s so spamming Sync
doesn't hammer the upstream site.
"""
import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
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

CACHE = {}            # spot_id -> (epoch_seconds, payload)
CACHE_TTL = 60        # seconds
PORT = 8765
INDEX_FILE = "public/index.html"


def get_spot(spot_id):
    return next((s for s in SPOTS if s["id"] == spot_id), None)


def sync_spot(spot_id, level=explainer.DEFAULT_LEVEL, force=False):
    spot = get_spot(spot_id)
    if not spot:
        return {"error": f"Unknown spot id: {spot_id}", "spot_id": spot_id}

    if level not in explainer.VALID_LEVELS:
        level = explainer.DEFAULT_LEVEL

    cache_key = (spot_id, level)
    cached = CACHE.get(cache_key)
    if not force and cached and (time.time() - cached[0]) < CACHE_TTL:
        return cached[1]

    sf_result, om_result, gfs_result, ibi_result = [None], [None], [None], [None]
    surfline_result, windguru_result = [None], [None]
    sf_error, om_error, gfs_error, ibi_error = [None], [None], [None], [None]
    surfline_error, windguru_error = [None], [None]

    def fetch_sf():
        try:
            sf_result[0] = scraper.scrape(spot["url"], tz_name=spot.get("tz"))
        except Exception as e:
            sf_error[0] = str(e)

    def fetch_om():
        lat, lon = spot.get("lat"), spot.get("lon")
        if lat is None or lon is None:
            om_error[0] = "No lat/lon configured for spot"
            return
        try:
            om_result[0] = open_meteo.fetch(lat, lon)
        except Exception as e:
            om_error[0] = str(e)

    def fetch_surfline():
        spot_id = spot.get("surfline_spot_id")
        if not spot_id:
            surfline_error[0] = "No Surfline spot id configured for spot"
            return
        try:
            surfline_result[0] = surfline.fetch(spot_id, source_url=spot.get("surfline_url"))
        except Exception as e:
            surfline_error[0] = str(e)

    def fetch_windguru():
        spot_id = spot.get("windguru_spot_id")
        if not spot_id:
            windguru_error[0] = "No Windguru spot id configured for spot"
            return
        try:
            windguru_result[0] = windguru.fetch(spot_id)
        except Exception as e:
            windguru_error[0] = str(e)

    def fetch_gfs():
        lat, lon = spot.get("lat"), spot.get("lon")
        if lat is None or lon is None:
            gfs_error[0] = "No lat/lon configured for spot"
            return
        try:
            gfs_result[0] = noaa_gfs.fetch(lat, lon)
        except Exception as e:
            gfs_error[0] = str(e)

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

    if surfline_result[0] and not surfline_error[0]:
        data["surfline_analysis"] = surfline_result[0].get("current")
        data["surfline_hourly"] = surfline_result[0].get("hourly", [])
        data["surfline_error"] = None
    else:
        data["surfline_analysis"] = None
        data["surfline_hourly"] = []
        data["surfline_error"] = surfline_error[0] or "Surfline fetch failed"

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

    CACHE[cache_key] = (time.time(), data)
    return data


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)

        if url.path in ("/", "/index.html", f"/{INDEX_FILE}"):
            return self._serve_file(INDEX_FILE, "text/html; charset=utf-8")

        static_response = self._serve_public_asset(url.path)
        if static_response:
            return

        if url.path == "/api/spots":
            return self._send_json(
                [{"id": s["id"], "name": s["name"], "url": s["url"]} for s in SPOTS]
            )

        if url.path == "/api/sync":
            qs = parse_qs(url.query)
            spot_id = qs.get("spot", [None])[0]
            level = qs.get("level", [explainer.DEFAULT_LEVEL])[0]
            if not spot_id:
                return self._send_json({"error": "missing 'spot' query param"}, status=400)
            force = "_" in qs or qs.get("refresh", ["0"])[0] in ("1", "true", "yes")
            return self._send_json(sync_spot(spot_id, level, force=force))

        self.send_error(404, "Not Found")

    def _serve_file(self, name, content_type):
        path = ROOT / name
        if not path.exists():
            return self.send_error(404, f"Missing {name}")
        body = path.read_bytes()
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_public_asset(self, url_path):
        relative = url_path.lstrip("/")
        if not relative or relative.startswith("api/"):
            return False

        public_root = (ROOT / "public").resolve()
        path = (public_root / relative).resolve()
        if not path.is_file() or not path.is_relative_to(public_root):
            return False

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._serve_file(str(path.relative_to(ROOT)), content_type)
        return True

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")

    def log_message(self, fmt, *args):
        # Quieter logs — only show failures.
        return


def main():
    print(f"Lineup running at http://localhost:{PORT}")
    print(f"    Working dir: {ROOT}")
    print(f"    Press Ctrl+C to stop.")
    try:
        HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
