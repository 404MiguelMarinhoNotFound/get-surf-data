import argparse
import json
import statistics
import urllib.request


DEFAULT_URL = "http://127.0.0.1:8765/api/sync?spot={spot}&level={level}&refresh=1"


def avg(components, key):
    values = [
        float(component[key])
        for component in components
        if component.get(key) is not None
    ]
    return f"{statistics.mean(values):.1f}" if values else "--"


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def print_spot(url_template, spot, level):
    data = fetch_json(url_template.format(spot=spot, level=level))
    unified = data.get("unified") or {}
    top_windows = unified.get("top_windows") or []
    windows = unified.get("predictor_windows") or []

    print(f"\n=== {spot} ===")
    if data.get("error"):
        print(f"error={data.get('error')}")
    print(f"surfline_error={data.get('surfline_error')}")
    print(f"surfline_hourly_count={len(data.get('surfline_hourly') or [])}")
    print(f"ibi_error={data.get('ibi_error')}")
    print(f"ibi_hourly_count={len(data.get('ibi_hourly') or [])}")
    print(f"sources_used={','.join(unified.get('sources_used') or [])}")
    print(f"top_count={len(top_windows)}")
    print("top idx | label | score | starts_at")
    for idx, win in enumerate(top_windows):
        print(
            f"{idx:02d} | {win.get('label')} | {win.get('score')} | {win.get('starts_at')}"
        )
    print(f"predictor_count={len(windows)}")
    predictor_starts = {win.get("starts_at") for win in windows}
    missing_from_predictor = [
        win.get("starts_at")
        for win in top_windows
        if win.get("starts_at") not in predictor_starts
    ]
    if missing_from_predictor:
        print(f"ERROR top_windows_not_in_predictor={','.join(missing_from_predictor)}")
    print("idx | label | score | missing | SF | Surfline | Windguru | OM | GFS | IBI")

    for idx, win in enumerate(windows):
        components = win.get("score_components") or []
        missing = ",".join((win.get("confidence_detail") or {}).get("missing_sources") or [])
        print(
            f"{idx:02d} | {win.get('label')} | {win.get('score')} | {missing or '-'} | "
            f"{avg(components, 'sf_score')} | "
            f"{avg(components, 'surfline_score')} | "
            f"{avg(components, 'windguru_score')} | "
            f"{avg(components, 'om_score')} | "
            f"{avg(components, 'gfs_score')} | "
            f"{avg(components, 'ibi_score')}"
        )


def main():
    parser = argparse.ArgumentParser(description="Print 7-day predictor source scores from /api/sync.")
    parser.add_argument("--url", default=DEFAULT_URL, help="URL template with {spot} and {level}.")
    parser.add_argument("--level", default="improver")
    parser.add_argument("--spots", nargs="+", default=["carcavelos", "caparica"])
    args = parser.parse_args()

    for spot in args.spots:
        print_spot(args.url, spot, args.level)


if __name__ == "__main__":
    main()
