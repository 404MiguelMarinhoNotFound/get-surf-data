# Lineup — surf forecast app

A personal surf conditions tool for Carcavelos and Costa da Caparica (Lisbon area). Scrapes surf-forecast.com, runs a skill-aware rules engine, and serves a dark-mode single-page frontend. No external dependencies — stdlib Python only.

## Live deployment

- **App:** https://getsurfdata.vercel.app
- **Repo:** https://github.com/404MiguelMarinhoNotFound/get-surf-data
- Every push to `master` auto-deploys via Vercel. No build step.

## Architecture

```
scraper.py       — fetches + parses surf-forecast.com HTML (regex, stdlib urllib)
explainer.py     — rules engine: raw data → verdict + plain-English rationale
server.py        — local dev server (stdlib http.server, port 8765)
api/spots.py     — Vercel serverless: GET /api/spots
api/sync.py      — Vercel serverless: GET /api/sync?spot=<id>&level=<tier>
public/index.html — single-file frontend (vanilla JS, no framework, no build)
spots.json       — spot config (id, url, tz, swell bearing, tide window, webcam)
```

No database. `spots.json` is the only persistent config. Forecast data is fetched live on each request; Vercel CDN caches responses for 60 seconds (`s-maxage=60`).

## API

### `GET /api/spots`
Returns the configured spots list.
```json
[{"id": "carcavelos", "name": "Carcavelos", "url": "..."}]
```

### `GET /api/sync?spot=<id>&level=<tier>`
Scrapes and grades one spot. `level` is optional, defaults to `improver`.

Valid levels: `beginner` | `improver` | `intermediate` | `advanced`

Returns: height, period, swell direction, wind state, tide, verdict, wetsuit recommendation, today's M/A/E slot verdicts, 3-hourly rating timeline.

## Skill tiers (explainer.py)

Each tier has its own height/period thresholds and explanation templates. Same wave, different verdicts:

| Tier | Green height range |
|---|---|
| beginner | 0.8–1.5m |
| improver | 0.6–1.7m |
| intermediate | 0.8–2.5m |
| advanced | 1.0–3.5m |

Verdict logic: any red signal → `skip`; 2+ yellows → `maybe`; otherwise → `go`.
Wind grading is shared across tiers. Tide and swell direction use per-spot config from `spots.json`.

## Adding a new spot

Add an entry to `spots.json`:
```json
{
  "id": "your-spot-id",
  "name": "Display Name",
  "url": "https://www.surf-forecast.com/breaks/<Break-Name>/forecasts/latest",
  "tz": "Europe/Lisbon",
  "optimal_swell_bearing": 260,
  "optimal_swell_label": "W-SW",
  "webcam_url": "https://...",
  "tide_window": "mid-to-high"
}
```
No code changes needed.

## Local dev

```bash
python server.py        # http://localhost:8765
python -m unittest discover -s tests   # run tests (no network needed)
python scripts/check_latest_surf_data.py  # live data sanity check
```

## Deployment

```bash
git push                # triggers auto-deploy on Vercel
vercel --prod --yes     # manual deploy from CLI
```

## Key files

| File | Purpose |
|---|---|
| [`scraper.py`](scraper.py) | HTML fetcher + regex parser |
| [`explainer.py`](explainer.py) | Rules engine, all four skill tiers |
| [`spots.json`](spots.json) | Spot configuration |
| [`api/sync.py`](api/sync.py) | Main serverless endpoint |
| [`public/index.html`](public/index.html) | Full frontend (1,300 lines, self-contained) |
| [`tests/`](tests/) | Unit tests — run offline |
