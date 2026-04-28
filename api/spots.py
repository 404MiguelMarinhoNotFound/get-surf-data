import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scraper  # noqa: F401 — ensures scraper module is bundled
import explainer  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
SPOTS = json.loads((ROOT / "spots.json").read_text(encoding="utf-8"))


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(
            [{"id": s["id"], "name": s["name"], "url": s["url"]} for s in SPOTS]
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, s-maxage=3600")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return
