# 🏄 Lineup

Local web app that scrapes surf-forecast.com for Carcavelos and Costa da Caparica | Praia do CDS,
extracts the key swell/wind parameters, and gives you a beginner-grade verdict
(🟢 Go / 🟡 Maybe / 🔴 Skip) with plain-English explanations for each parameter.

## Run it

Requires Python 3.7+. No pip install needed — stdlib only.

```bash
cd surf-sync
python3 server.py
```

Then open: <http://localhost:8765>

Click **Sync All**. The browser hits `/api/sync` on the local server, which runs
`scraper.py` against the live forecast pages and returns parsed conditions plus
a verdict from `explainer.py`.

## Test the data pull

Fast parser tests, no network:

```bash
python -m unittest discover -s tests
```

Live freshness canary against surf-forecast.com:

```bash
python scripts/check_latest_surf_data.py
```

The live check fails if required surf fields are missing, outside plausible
ranges, or if surf-forecast.com's own "issued" timestamp is older than 8 hours.
Override that freshness window when needed:

```bash
python scripts/check_latest_surf_data.py --max-age-hours 12
```

To run the same live canary through `unittest`:

```powershell
$env:RUN_LIVE_SURF_TESTS = "1"
python -m unittest tests.test_live_latest -v
Remove-Item Env:\RUN_LIVE_SURF_TESTS
```

## What it does

For each spot:

1. **Scrape** — fetches the latest forecast page, strips HTML, regex-extracts the
   summary sentence (height, period, swell direction, wind state, rating) and the
   sea temperature line.
2. **Grade** — applies hardcoded beginner thresholds:
   - Height: 0.8–1.5m green · 1.5–2.0m yellow · >2.0m red
   - Period: 9–14s green · 6–8s or 15–16s yellow · outside red
   - Wind: offshore/glassy/cross-offshore green · cross-shore/cross-onshore yellow · onshore red
3. **Verdict** — any red → 🔴 Skip · two+ yellows → 🟡 Maybe · otherwise → 🟢 Go.
4. **Explain** — each parameter ships with a "for dummies" sentence explaining
   why it's good or bad.

Results are cached in-memory for 60 seconds so repeated clicks don't hammer the
upstream site.

## Files

```
surf-sync/
├── server.py       # Local HTTP server (stdlib http.server)
├── scraper.py      # Fetches + parses surf-forecast.com pages
├── explainer.py    # Rules engine: parameters → verdict + bullets
├── spots.json      # Add more breaks here
├── index.html      # Single-file UI (CSS + JS inline)
└── README.md       # this
```

## Add a spot

Edit `spots.json`:

```json
{
  "id": "ericeira",
  "name": "Ericeira",
  "url": "https://www.surf-forecast.com/breaks/Ericeira/forecasts/latest"
}
```

Restart the server. New cards appear automatically.

## Tweak the rules

Open `explainer.py`. Each parameter has its own `grade_*` function with the
thresholds inline. Change a number, restart, refresh.

To support intermediate/advanced skill levels later, add a `skill` parameter
to `verdict()` and branch the height thresholds (e.g. up to 2.5m green for
intermediate).

## Notes

- The scraper depends on the rendered text containing the canonical
  *"is: Xm Ys primary swell from a Z direction"* sentence. If surf-forecast.com
  changes that wording, the regexes in `parse_summary()` need a small edit.
- The site rating shown ("X/10") is informational only — the actual verdict
  uses height, period, and wind directly.
- No tracking, no external CSS/JS, runs only on `127.0.0.1` (not exposed to LAN).
