import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import surfline  # noqa: E402


SPOTS = json.loads((ROOT / "spots.json").read_text(encoding="utf-8"))
DEBUG_HEADERS = dict(surfline.DEFAULT_HEADERS)


def _shape(payload, kind):
    if not isinstance(payload, dict):
        return "payload=dict:False data=False"
    data = payload.get("data")
    rows = None
    if isinstance(data, dict):
        key = "tides" if kind == "tides" else kind
        rows = data.get(key)
    return (
        f"payload=dict:True data={isinstance(data, dict)} "
        f"rows={len(rows) if isinstance(rows, list) else 'n/a'}"
    )


def fetch_debug(url, kind):
    req = urllib.request.Request(url, headers=DEBUG_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
            print(f"OK {resp.status} {resp.headers.get('content-type')} {len(body)} bytes")
            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                print(f"JSON_ERROR {exc}")
                print(body[:300].decode("utf-8", errors="replace"))
                return None
            print(_shape(payload, kind))
            return payload
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP_ERROR {exc.code} {exc.reason}")
        print(f"content-type={exc.headers.get('content-type')}")
        print(body[:300])
        return None
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}")
        return None


def inspect_public_page(url):
    print(f"\nINSPECT PUBLIC PAGE: {url}")
    if not url:
        print("No Surfline page URL configured")
        return
    req = urllib.request.Request(url, headers=DEBUG_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        print(f"page_bytes={len(html)}")
        for needle in ["x-api-key", "apiKey", "clientId", "kbyg", "__NEXT_DATA__"]:
            print(f"{needle}: {'FOUND' if needle in html else 'missing'}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP_ERROR {exc.code} {exc.reason}")
        print(f"content-type={exc.headers.get('content-type')}")
        print(body[:300])
    except Exception as exc:
        print(f"ERROR {type(exc).__name__}: {exc}")


def _print_hourly_sample(payload):
    hourly = payload.get("hourly", []) if isinstance(payload, dict) else []
    print(f"hourly_count={len(hourly)}")
    for row in hourly[:5]:
        print(json.dumps({
            "timestamp_utc": row.get("timestamp_utc"),
            "wave_height": row.get("wave_height"),
            "swell_height": row.get("swell_height"),
            "swell_period": row.get("swell_period"),
            "swell_direction": row.get("swell_direction"),
            "wind_speed": row.get("wind_speed"),
            "wind_direction": row.get("wind_direction"),
            "surfline_optimal_score": row.get("surfline_optimal_score"),
        }, sort_keys=True))


def main():
    for spot in SPOTS:
        spot_id = spot.get("surfline_spot_id")
        if not spot_id:
            continue
        print(f"\n=== {spot.get('id')} | {spot.get('name')} ===")
        print(f"spot_id={spot_id}")
        print(f"surfline_url={spot.get('surfline_url')}")

        report_url = surfline.REPORT_URL.format(spot_id=spot_id)
        print(f"\nFETCH reports: {report_url}")
        fetch_debug(report_url, "reports")

        for kind in ["wave", "wind", "tides", "weather"]:
            url = surfline.FORECAST_URL.format(kind=kind, spot_id=spot_id, days=7)
            print(f"\nFETCH {kind}: {url}")
            fetch_debug(url, kind)

        print("\nNORMALIZED FETCH")
        try:
            payload = surfline.fetch(spot_id, source_url=spot.get("surfline_url"))
            _print_hourly_sample(payload)
        except Exception as exc:
            print(f"NORMALIZED_ERROR {type(exc).__name__}: {exc}")
            inspect_public_page(spot.get("surfline_url"))


if __name__ == "__main__":
    main()
