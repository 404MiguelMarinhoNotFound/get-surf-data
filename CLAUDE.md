# Lineup — surf forecast app

A personal surf conditions tool for Carcavelos and Costa da Caparica | Praia do CDS (Lisbon area). Blends four data sources — surf-forecast.com (scraped), Open-Meteo Marine, Copernicus Marine IBI, and IPMA Portugal Oceanography — through a weighted-harmonic consensus engine, then serves a dark-mode single-page frontend. Stdlib Python only.

## Live deployment

- **App:** https://getsurfdata.vercel.app
- **Repo:** https://github.com/404MiguelMarinhoNotFound/get-surf-data
- Every push to `master` auto-deploys via Vercel. No build step.

## Architecture

```
scraper.py                    — fetches + parses surf-forecast.com HTML
explainer.py                  — SF rules engine: raw data → verdict + rationale
open_meteo.py                 — Open-Meteo Marine + Weather hourly client
open_meteo_explainer.py       — OM scorer + tier-aware graders
copernicus_ibi.py             — Copernicus Marine IBI WMS client (auth req'd)
copernicus_ibi_explainer.py   — IBI scorer (reuses OM graders)
ipma.py                       — IPMA Portugal daily sea-forecast client + envelope
unified_explainer.py          — N-source weighted harmonic blend, IPMA sanity layer
server.py                     — local dev server (port 8765)
api/spots.py                  — Vercel serverless: GET /api/spots
api/sync.py                   — Vercel serverless: GET /api/sync?spot=<id>&level=<tier>
public/index.html             — single-file frontend (vanilla JS)
spots.json                    — spot config
```

No database. `spots.json` is the only persistent config. All four sources are fetched in parallel on each request; Vercel CDN caches responses for 60 seconds (`s-maxage=60`).

## Data sources & blend weights

| Source | Weight | Role |
|---|---|---|
| surf-forecast.com (SF) | 0.40 | Local human-curated rating + spot heuristics |
| Open-Meteo Marine (OM) | 0.30 | Hourly wave/swell partitions + wind |
| Copernicus IBI (IBI)   | 0.30 | Regional MFWAM, ECMWF wind-forced |
| IPMA daily             | —    | Sanity envelope (Hs/period bounds — no score weight) |

Weights renormalize pro-rata when a source is unavailable. The IPMA layer never modifies score; if blended Hs/period sits outside Portugal's official daily range it drops the confidence label one tier and flags the UI.

### Required env vars (Vercel)

- `COPERNICUS_USER`, `COPERNICUS_PASS` — Copernicus Marine credentials. If unset, IBI fetch returns None and the blend renormalizes to SF + OM.

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
  "tide_window": "mid-to-high",
  "ipma_local_id": 1110600
}
```
`ipma_local_id` is IPMA's `globalIdLocal` for the nearest coastal forecast cell (used only for the daily envelope sanity check). No code changes needed.

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
| [`explainer.py`](explainer.py) | SF rules engine, all four skill tiers |
| [`open_meteo.py`](open_meteo.py) / [`open_meteo_explainer.py`](open_meteo_explainer.py) | OM client + scorer |
| [`copernicus_ibi.py`](copernicus_ibi.py) / [`copernicus_ibi_explainer.py`](copernicus_ibi_explainer.py) | IBI client + scorer |
| [`ipma.py`](ipma.py) | IPMA daily forecast + envelope check |
| [`unified_explainer.py`](unified_explainer.py) | N-source blend, weighted harmonic mean, hard gates, windowing |
| [`spots.json`](spots.json) | Spot configuration |
| [`api/sync.py`](api/sync.py) | Main serverless endpoint (4-source fan-out) |
| [`public/index.html`](public/index.html) | Full frontend (vanilla JS, self-contained) |
| [`tests/`](tests/) | Unit tests — run offline |
