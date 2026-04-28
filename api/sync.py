import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scraper
import explainer

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

    try:
        data = scraper.scrape(spot["url"], tz_name=spot.get("tz"))
    except Exception as e:
        return {
            "error": f"Couldn't fetch forecast: {e}",
            "spot_id": spot["id"],
            "spot_name": spot["name"],
            "url": spot["url"],
        }

    data["spot_id"] = spot["id"]
    data["spot_name"] = spot["name"]
    data.update(explainer.verdict(data, level, spot))

    # Grade today's M/A/E slots (height+period only; wind unknown per slot).
    for slot in data.get("today_slots", []):
        slot_data = {"height_m": slot.get("height_m"), "period_s": slot.get("period_s")}
        v = explainer.verdict(slot_data, level)
        slot["verdict"] = v["verdict"]

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
