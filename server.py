"""Local HTTP server for Lineup.

Run:  python3 server.py
Open: http://localhost:8765

Stdlib only. Caches scraped data per-spot for 60s so spamming Sync
doesn't hammer the upstream site.
"""
import json
import mimetypes
import os
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
import forecast_sync

ROOT = Path(__file__).resolve().parent


def _load_env_file(path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


_load_env_file(ROOT / ".env.local")
_load_env_file(ROOT / ".env.preview.local")

SPOTS = json.loads((ROOT / "spots.json").read_text(encoding="utf-8"))

CACHE = {}            # spot_id -> (epoch_seconds, payload)
CACHE_TTL = 60        # seconds
PORT = 8765
INDEX_FILE = "public/index.html"


def get_spot(spot_id):
    return next((s for s in SPOTS if s["id"] == spot_id), None)


def sync_spot(spot_id, level=explainer.DEFAULT_LEVEL, force=False):
    cache_key = (spot_id, level)
    cached = CACHE.get(cache_key)
    if not force and cached and (time.time() - cached[0]) < CACHE_TTL:
        return cached[1]
    data = forecast_sync.sync_spot(spot_id, level)
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
