# Lineup - surf forecast app

A personal surf conditions tool for Carcavelos and Costa da Caparica | Praia do CDS (Lisbon area). Blends four data sources - surf-forecast.com (scraped), Open-Meteo Marine, NOAA GFS Wave, and Copernicus Marine IBI - through the doctrine V2 geometric suitability engine, then serves a dark-mode single-page frontend. Stdlib Python only.

## Live deployment

- **App:** https://getlineup.vercel.app
- **Repo:** https://github.com/404MiguelMarinhoNotFound/get-surf-data
- Every push to `master` auto-deploys via Vercel. No build step.

## Architecture

```
scraper.py                    - fetches + parses surf-forecast.com HTML
explainer.py                  - SF rules engine: raw data -> verdict + rationale
open_meteo.py                 - Open-Meteo Marine + Weather hourly client
open_meteo_explainer.py       - OM scorer + tier-aware doctrine V2 suitability factors
noaa_gfs.py                   - NOAA GFS Wave + GFS wind client
noaa_gfs_explainer.py         - GFS scorer (reuses OM graders)
copernicus_ibi.py             - Copernicus Marine IBI WMS client (auth req'd)
copernicus_ibi_explainer.py   - IBI scorer (reuses OM graders)
unified_explainer.py          - N-source geometric blend, confidence, hard gates + windowing
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
| surf-forecast.com (SF) | 0.25 | Local human-curated rating + spot heuristics |
| Open-Meteo Marine (OM) | 0.35 | Hourly wave/swell partitions + wind/gusts |
| NOAA GFS Wave (GFS) | 0.25 | Independent global wave + wind model, using the 0.16 degree coastal grid |
| Copernicus IBI (IBI) | 0.15 | Regional MFWAM wave model, fused with OM wind |

Weights renormalize pro-rata when a source is unavailable and adapt slightly per hour when richer fields such as numeric wind, gusts, or complete wave partitions are present. These are temporary reliability priors, not calibrated final weights.

## 2026-05 SF gold-star awareness

Surf-Forecast renders each 3-hour rating cell with a colored SVG star. **Gold** = SF's full predictor stack flags the cell as a strong local fit (right tide/direction/period for the break); **white** = mediocre. The star color is the strongest local-curation tell the page exposes — a "3-gold" is genuinely a good cell, while a "3-white" is just mid-low. Treating both identically caused good model windows to be vetoed when SF gave a low number for spot-curation reasons.

Pipeline:

- [`scraper.parse_rating_star_states(html)`](scraper.py) finds the `<tr data-row="rating">` block and extracts each cell's `<use fill="hsl(...)">` plus `star-rating__rating--N` digit.
- [`scraper.classify_star_fill(fill, rating)`](scraper.py) classifies by HSL meaning (not exact string — SF varies gold lightness with rating): `hue 45-65 + sat>=80` → `gold`; `sat<=5 + light>=90` → `white`; `rating==0` → `zero`; else `unknown`.
- `scrape()` merges results into each `rating_timeline` cell as `sf_star_state` and `sf_is_gold_star`. This is **source data**, intentionally distinct from the app's derived `TIER_GOLD` ([`unified_explainer._tier_for_score`](unified_explainer.py)).

Scoring:

- [`unified_explainer._SF_QUALITY_CURVE_GOLD`](unified_explainer.py) is a second curve with a lifted floor. `_sf_quality_score(rating, is_gold_star=False)` picks the curve. Examples — rating 3: plain → 4.8, gold → 6.8. Rating 5: plain → 6.8, gold → 8.2. Rating 2: plain → 3.5, gold → 5.5.
- The `sf_low_rating` window-eligibility gate now requires SF≤2 **and** non-gold **and** (OM missing or OM<5.5). A "2-gold" cell or a "2-white but OM=7.0" cell is no longer vetoed from `top_windows`. A "2-white with OM=4.0" still gates out.

Source weights were rebalanced from 0.40/0.30/0.20/0.10 to 0.25/0.35/0.25/0.15. SF's *informational* contribution now lives in the curve choice rather than dominating the geometric mean. Geometric blend example with SF=4.8, OM=7.5, GFS=7.0 (no IBI): old ≈ 5.97 → new ≈ 6.34. Same hour with gold-star (SF=6.8): ≈ 7.10.

## 2026-05 top-5 windows carousel

The hero card now shows up to 5 best surf windows over the next 7 days, navigable via left/right arrows (keyboard `ArrowLeft`/`ArrowRight` also work). The stepper always renders — during flat swells it shows "1 / 1" with both arrows disabled so the count is still visible.

Implementation details:

- `unified_explainer._top_windows()` reuses `_session_candidates()`, sorts by score, then deduplicates by `(local_date, AM/PM)` bucket using the spot's timezone. Caps at 5 results.
- `find_next_windows()` returns `top_windows: [...]`; `best_window` aliases `top_windows[0]` for backwards compatibility.
- Frontend: `renderHeroWindowCarousel()` wraps the existing `renderHeroWindow` in a `role="region" aria-live="polite"` container. State (windows list + current index) lives on the `.hero-card` element via `data-hero-state` / `data-hero-index` attributes so re-renders don't reset it.
- No database needed — OM and GFS already deliver 7 days of hourly data; `find_next_windows()` already iterated the full 7-day horizon before this change.

## 2026-05 doctrine V2 scoring notes

The scoring engine now follows the research doctrine in `C:/Users/Migue/Downloads/surf_decider_research_doctrine.md`.

Important implementation details:

- `open_meteo_explainer._hour_score()` no longer uses the old linear formula (`height*0.30 + period*0.25 + purity*0.20 + direction*0.15 + wind*0.10`).
- Model hour scores are now a weighted geometric aggregation of 0-1 suitability factors:
  - height suitability,
  - wave power (`height^2 * period`),
  - period suitability,
  - wind direction/speed suitability,
  - wind-sea/chop suitability,
  - swell-direction suitability,
  - secondary-swell interference,
  - tide suitability.
- Suitability is tier-aware for `beginner`, `improver`, `intermediate`, and `advanced`. Larger or longer-period surf is no longer automatically better for every level.
- `unified_explainer._consensus_score()` now uses `_weighted_geometric()` across source scores. `_weighted_harmonic()` remains only as a legacy helper and is not the production consensus path.
- Source disagreement is represented in `confidence` and `confidence_detail`, not subtracted from the surf quality score.
- Duplicate post-consensus direction and yellow-tide penalties were removed. Direction and tide now affect factor/source scores directly.
- Hard gates are narrower:
  - keep true no-surf / flat surf,
  - keep extreme tier-danger power,
  - keep red spot-specific tide shutdown,
  - keep severe blown-out wind only when meaningful onshore component and wind-sea/chop are both present.
  - light onshore wind should lower score, not instantly force skip.
- Low Surf-Forecast timeline ratings (`<=2`) still suppress future model-only hero windows, so model optimism cannot override clearly poor local SF context.

The unified payload preserves existing fields and adds optional diagnostics:

```json
{
  "scoring_model": "doctrine_v2_geometric_suitability",
  "confidence_detail": {
    "source_count": 3,
    "source_score_spread": 6.5,
    "missing_sources": ["ibi"],
    "raw_variable_spread": {
      "height_m": 0.12,
      "period_s": 2.75,
      "wind_speed_kmh": 0.2,
      "wind_direction_deg": 8.0
    },
    "confidence_score_0_1": 0.49
  },
  "factor_scores": {
    "om": {"height": 1.0, "power": 1.0, "period": 1.0, "wind": 0.44},
    "gfs": {"height": 1.0, "power": 1.0, "period": 1.0, "wind": 0.61},
    "ibi": null,
    "tide": 0.75
  },
  "hard_gate_detail": {"blocked": false, "reason": null, "source": null}
}
```

## 2026-04 GFS integration notes

The expansion plan replaced the old IPMA daily envelope with hourly NOAA GFS so the consensus can compare independent wave + wind data at the same cadence as Open-Meteo. The purpose was precision: daily IPMA bounds could only sanity-check broad height/period ranges, while GFS can participate in the geometric suitability score for each hour.

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

Returns: height, period, swell direction, wind state/speed, tide, verdict, wetsuit recommendation, today's M/A/E slot verdicts, 3-hourly rating timeline, marine-source analyses, and the unified consensus. The unified object includes backwards-compatible decision fields plus doctrine V2 diagnostics such as `scoring_model`, `confidence_detail`, `factor_scores`, and `hard_gate_detail`.

Key unified fields for the hero card:

| Field | Type | Description |
|---|---|---|
| `best_window` | object\|null | Top-ranked decent window (alias of `top_windows[0]`) |
| `top_windows` | array | Up to 5 best non-overlapping windows over 7 days, ranked by score |
| `next_gold_window` | object\|null | Best gold-tier (≥7.5) window |
| `gold_count_7d` | int | Number of gold blocks in the next 7 days |
| `current_window_ends` | ISO string\|null | When the current green window closes (if decision is `go`) |

`top_windows` deduplicates by local AM/PM half-day so results spread across the week rather than clustering on one swell event. `best_window` and `next_decent_window` remain for backwards compatibility.

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

The doctrine V2 model scoring path also uses skill tiers numerically. Height, period, and power suitability curves differ by skill level, so the same raw model row can produce a different source score for `beginner` than for `advanced`.

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
python scripts/cross_check_sources.py
```

## Deployment

```bash
git push
vercel --prod --yes
```

If the global Vercel CLI fails on Windows with `node.exe: Access is denied`, run the installed Vercel CLI script with the bundled Codex Node runtime:

```powershell
& 'C:\Users\Migue\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' 'C:\Users\Migue\AppData\Roaming\npm\node_modules\vercel\dist\vc.js' --prod --yes
```

Production smoke checks:

```powershell
Invoke-WebRequest -Uri 'https://getlineup.vercel.app/api/spots' -UseBasicParsing
Invoke-WebRequest -Uri 'https://getlineup.vercel.app/api/sync?spot=carcavelos&level=improver' -UseBasicParsing
```

## Key files

| File | Purpose |
|---|---|
| [`scraper.py`](scraper.py) | HTML fetcher + regex parser |
| [`explainer.py`](explainer.py) | SF rules engine, all four skill tiers |
| [`open_meteo.py`](open_meteo.py) / [`open_meteo_explainer.py`](open_meteo_explainer.py) | OM client + doctrine V2 factor scorer |
| [`noaa_gfs.py`](noaa_gfs.py) / [`noaa_gfs_explainer.py`](noaa_gfs_explainer.py) | NOAA GFS client + scorer |
| [`copernicus_ibi.py`](copernicus_ibi.py) / [`copernicus_ibi_explainer.py`](copernicus_ibi_explainer.py) | IBI client + scorer |
| [`unified_explainer.py`](unified_explainer.py) | N-source geometric blend, confidence detail, hard gates, windowing |
| [`spots.json`](spots.json) | Spot configuration |
| [`api/sync.py`](api/sync.py) | Main serverless endpoint (4-source fan-out) |
| [`public/index.html`](public/index.html) | Full frontend (vanilla JS, self-contained) |
| [`tests/`](tests/) | Unit tests - run offline |
