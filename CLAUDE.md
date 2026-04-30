# Lineup - surf forecast app

A personal surf conditions tool for Carcavelos and Costa da Caparica | Praia do CDS (Lisbon area). Blends four data sources - surf-forecast.com (scraped), Open-Meteo Marine, NOAA GFS Wave, and Copernicus Marine IBI - through a weighted-harmonic consensus engine, then serves a dark-mode single-page frontend. Stdlib Python only.

## Live deployment

- **App:** https://getlineup.vercel.app
- **Repo:** https://github.com/404MiguelMarinhoNotFound/get-surf-data
- Every push to `master` auto-deploys via Vercel. No build step.

## Architecture

```
scraper.py                    - fetches + parses surf-forecast.com HTML
explainer.py                  - SF rules engine: raw data -> verdict + rationale
open_meteo.py                 - Open-Meteo Marine + Weather hourly client
open_meteo_explainer.py       - OM scorer + tier-aware graders
noaa_gfs.py                   - NOAA GFS Wave + GFS wind client
noaa_gfs_explainer.py         - GFS scorer (reuses OM graders)
copernicus_ibi.py             - Copernicus Marine IBI WMS client (auth req'd)
copernicus_ibi_explainer.py   - IBI scorer (reuses OM graders)
unified_explainer.py          - N-source weighted harmonic blend + windowing
server.py                     - local dev server (port 8765)
api/spots.py                  - Vercel serverless: GET /api/spots
api/sync.py                   - Vercel serverless: GET /api/sync?spot=<id>&level=<tier>
public/index.html             - single-file frontend (vanilla JS)
spots.json                    - spot config
```

No database. `spots.json` is the only persistent config. All four sources are fetched in parallel on each request; Vercel CDN caches responses for 60 seconds (`s-maxage=60`).

## Data sources & blend weights

| Source | Base weight | Role |
|---|---:|---|
| surf-forecast.com (SF) | 0.40 | Local human-curated rating + spot heuristics |
| Open-Meteo Marine (OM) | 0.30 | Hourly wave/swell partitions + wind/gusts |
| NOAA GFS Wave (GFS) | 0.20 | Independent global wave + wind model, using the 0.16 degree coastal grid |
| Copernicus IBI (IBI) | 0.10 | Regional MFWAM wave model, fused with OM wind |

Weights renormalize pro-rata when a source is unavailable and adapt slightly per hour when richer fields such as numeric wind, gusts, or complete wave partitions are present.

## 2026-04 GFS integration notes

The expansion plan replaced the old IPMA daily envelope with hourly NOAA GFS so the consensus can compare independent wave + wind data at the same cadence as Open-Meteo. The purpose was precision: daily IPMA bounds could only sanity-check broad height/period ranges, while GFS can participate in the weighted harmonic score for each hour.

Important implementation details:

- `noaa_gfs.py` uses Open-Meteo's GFS weather endpoint plus Marine API model `ncep_gfswave016`.
- The 0.16 degree GFS wave grid is intentional. The 0.25 degree grid returned zeroed marine fields for Costa da Caparica during verification.
- IBI remains wave-only via the current Copernicus WMS path, so `unified_explainer.py` fuses IBI wave fields with same-hour OM wind where available.
- Surf-Forecast numeric wind speed is parsed when exposed and is used to soften or harden the SF wind grade.
- Open-Meteo secondary swell and gust fields flow through the hourly rows and scoring metadata.

Verification commands used for this integration:

```bash
python scripts/check_latest_surf_data.py
python scripts/cross_check_sources.py
RUN_LIVE_SURF_TESTS=1 python -m unittest tests.test_live_latest -v
python -m unittest discover -v
```

Expected live caveat: Surf-Forecast may omit the summary-level `rating` value even when the rating timeline parses. That is currently a warning in `check_latest_surf_data.py`, not a sync failure.

### Required env vars (Vercel)

- `COPERNICUS_USER`, `COPERNICUS_PASS` - Copernicus Marine credentials. If unset, IBI fetch returns None and the blend renormalizes to the available sources.

## API

### `GET /api/spots`
Returns the configured spots list.
```json
[{"id": "carcavelos", "name": "Carcavelos", "url": "..."}]
```

### `GET /api/sync?spot=<id>&level=<tier>`
Scrapes and grades one spot. `level` is optional, defaults to `improver`.

Valid levels: `beginner` | `improver` | `intermediate` | `advanced`

Returns: height, period, swell direction, wind state/speed, tide, verdict, wetsuit recommendation, today's M/A/E slot verdicts, 3-hourly rating timeline, marine-source analyses, and the unified consensus.

## Skill tiers (explainer.py)

Each tier has its own height/period thresholds and explanation templates. Same wave, different verdicts:

| Tier | Green height range |
|---|---|
| beginner | 0.8-1.5m |
| improver | 0.6-1.7m |
| intermediate | 0.8-2.5m |
| advanced | 1.0-3.5m |

Verdict logic: any red signal -> `skip`; 2+ yellows -> `maybe`; otherwise -> `go`.
Wind grading uses both Surf-Forecast direction category and numeric wind speed when available. Tide and swell direction use per-spot config from `spots.json`.

## Adding a new spot

Add an entry to `spots.json`:
```json
{
  "id": "your-spot-id",
  "name": "Display Name",
  "url": "https://www.surf-forecast.com/breaks/<Break-Name>/forecasts/latest",
  "tz": "Europe/Lisbon",
  "lat": 38.698,
  "lon": -9.331,
  "offshore_bearing": 10,
  "optimal_swell_bearing": 260,
  "optimal_swell_label": "W-SW",
  "webcam_url": "https://...",
  "tide_window": "mid-to-high"
}
```

No code changes needed.

## Local dev

```bash
python server.py
python -m unittest discover -s tests
python scripts/check_latest_surf_data.py
```

## Deployment

```bash
git push
vercel --prod --yes
```

## Key files

| File | Purpose |
|---|---|
| [`scraper.py`](scraper.py) | HTML fetcher + regex parser |
| [`explainer.py`](explainer.py) | SF rules engine, all four skill tiers |
| [`open_meteo.py`](open_meteo.py) / [`open_meteo_explainer.py`](open_meteo_explainer.py) | OM client + scorer |
| [`noaa_gfs.py`](noaa_gfs.py) / [`noaa_gfs_explainer.py`](noaa_gfs_explainer.py) | NOAA GFS client + scorer |
| [`copernicus_ibi.py`](copernicus_ibi.py) / [`copernicus_ibi_explainer.py`](copernicus_ibi_explainer.py) | IBI client + scorer |
| [`unified_explainer.py`](unified_explainer.py) | N-source blend, weighted harmonic mean, hard gates, windowing |
| [`spots.json`](spots.json) | Spot configuration |
| [`api/sync.py`](api/sync.py) | Main serverless endpoint (4-source fan-out) |
| [`public/index.html`](public/index.html) | Full frontend (vanilla JS, self-contained) |
| [`tests/`](tests/) | Unit tests - run offline |
