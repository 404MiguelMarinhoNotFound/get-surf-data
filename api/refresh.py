import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
import forecast_cache


def _header_value(headers, name):
    if headers is None:
        return None
    value = headers.get(name)
    if value is not None:
        return value
    return headers.get(name.lower())


def refresh_auth_result(headers):
    db.load_local_env()
    cron_secret = (os.environ.get("CRON_SECRET") or "").strip()
    if not cron_secret:
        return (
            False,
            {
                "error": "refresh auth is not configured",
                "code": "refresh_auth_not_configured",
            },
            503,
        )
    if _header_value(headers, "Authorization") != f"Bearer {cron_secret}":
        return (
            False,
            {
                "error": "unauthorized",
                "code": "refresh_auth_invalid",
            },
            401,
        )
    return True, None, 200


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._handle_refresh(force=False)

    def do_POST(self):
        qs = parse_qs(urlparse(self.path).query)
        force = qs.get("force", ["0"])[0].lower() in ("1", "true", "yes")
        self._handle_refresh(force=force)

    def _handle_refresh(self, force=False):
        allowed, payload, status = refresh_auth_result(self.headers)
        if not allowed:
            self._send_json(payload, status=status)
            return

        try:
            result = forecast_cache.refresh_cache(force=force)
        except Exception as exc:
            self._send_json(
                {
                    "error": str(exc),
                    "code": "forecast_refresh_failed",
                },
                status=500,
            )
            return

        self._send_json(result)

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return
