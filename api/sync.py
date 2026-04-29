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
import ipma

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

    sf_result, om_result, ibi_result, ipma_result = [None], [None], [None], [None]
    sf_error, om_error, ibi_error, ipma_error = [None], [None], [None], [None]

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

    def fetch_ipma():
        local_id = spot.get("ipma_local_id")
        if not local_id:
            ipma_error[0] = "No ipma_local_id configured for spot"
            return
        try:
            ipma_result[0] = ipma.fetch(local_id)
        except Exception as e:
            ipma_error[0] = str(e)

    threads = [
        threading.Thread(target=fetch_sf),
        threading.Thread(target=fetch_om),
        threading.Thread(target=fetch_ibi),
        threading.Thread(target=fetch_ipma),
    ]
    for t in threads:
        t.start()
    threads[0].join(timeout=25)
    threads[1].join(timeout=15)
    threads[2].join(timeout=15)
    threads[3].join(timeout=8)

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

    # IPMA daily envelope (sanity layer, not weighted).
    ipma_envelope = None
    if ipma_result[0] and not ipma_error[0]:
        data["ipma_data"] = ipma_result[0]
        # Use OM swell height as the canonical "blended" probe (highest hourly
        # resolution); fall back to SF height if OM is missing.
        om = data.get("om_analysis") or {}
        probe_h = om.get("swell_height") or om.get("wave_height") or data.get("height_m")
        probe_p = om.get("swell_period") or om.get("wave_period") or data.get("period_s")
        ipma_envelope = ipma.envelope_check(
            ipma_result[0].get("today"),
            probe_h,
            probe_p,
        )
        data["ipma_error"] = None
    else:
        data["ipma_data"] = None
        data["ipma_error"] = ipma_error[0] or "IPMA fetch failed"

    data["unified"] = unified_explainer.unify(
        sf_data=data,
        om_analysis=data.get("om_analysis"),
        om_hourly=om_hourly,
        spot=spot,
        level=level,
        ibi_analysis=data.get("ibi_analysis"),
        ipma_envelope=ipma_envelope,
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
