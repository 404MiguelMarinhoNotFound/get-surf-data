import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import explainer
import forecast_cache
import forecast_sync

scraper = forecast_sync.scraper
open_meteo = forecast_sync.open_meteo
noaa_gfs = forecast_sync.noaa_gfs
copernicus_ibi = forecast_sync.copernicus_ibi
surfline = forecast_sync.surfline
windguru = forecast_sync.windguru


def _sync_spot(spot_id, level=explainer.DEFAULT_LEVEL):
    """Legacy test helper; HTTP requests use the Neon cache only."""
    return forecast_sync.sync_spot(spot_id, level)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        spot_id = qs.get("spot", [None])[0]
        level = qs.get("level", [explainer.DEFAULT_LEVEL])[0]

        if not spot_id:
            self._send_json({"error": "missing 'spot' query param"}, status=400)
            return

        try:
            data = forecast_cache.read_cached_payload(spot_id, level)
        except Exception as exc:
            self._send_json(
                {
                    "error": str(exc),
                    "code": "forecast_cache_unavailable",
                    "spot_id": spot_id,
                    "level": level,
                },
                status=500,
            )
            return

        if data is None:
            self._send_json(forecast_cache.empty_cache_payload(spot_id, level), status=503)
            return

        self._send_json(data)

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
