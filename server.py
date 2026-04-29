"""Local HTTP server for Lineup.

Run:  python3 server.py
Open: http://localhost:8765

Stdlib only. Caches scraped data per-spot for 60s so spamming Sync
doesn't hammer the upstream site.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

import scraper
import explainer
import open_meteo
import open_meteo_explainer

ROOT = Path(__file__).resolve().parent
SPOTS = json.loads((ROOT / "spots.json").read_text(encoding="utf-8"))

CACHE = {}            # spot_id -> (epoch_seconds, payload)
CACHE_TTL = 60        # seconds
PORT = 8765
INDEX_FILE = "public/index.html"


def get_spot(spot_id):
    return next((s for s in SPOTS if s["id"] == spot_id), None)


def sync_spot(spot_id, level=explainer.DEFAULT_LEVEL):
    spot = get_spot(spot_id)
    if not spot:
        return {"error": f"Unknown spot id: {spot_id}", "spot_id": spot_id}

    if level not in explainer.VALID_LEVELS:
        level = explainer.DEFAULT_LEVEL

    cache_key = (spot_id, level)
    cached = CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < CACHE_TTL:
        return cached[1]

    sf_result, om_result = [None], [None]
    sf_error, om_error = [None], [None]

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

    t_sf = threading.Thread(target=fetch_sf)
    t_om = threading.Thread(target=fetch_om)
    t_sf.start()
    t_om.start()
    t_sf.join(timeout=25)
    t_om.join(timeout=15)

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
            return self._send_json(sync_spot(spot_id, level))

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
