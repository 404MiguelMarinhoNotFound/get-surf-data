# Standardize Window Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize all recommendation windows to fixed local 3-hour blocks, show up to 10 next best windows in the hero arrow selector, and keep hero selection synchronized with the rolling predictor detail below.

**Architecture:** Build one backend window primitive for local 3-hour forecast blocks and derive both `top_windows` and `predictor_windows` from it. `predictor_windows` remains chronological lineage; `top_windows` becomes the next best eligible 3-hour windows sorted by score, capped at 10, with no flexible 2-4 hour sessions. Frontend state stores one selected window identity and maps it across hero carousel and predictor ribbon so arrow navigation and bar selection update the same detailed rolling-window payload.

**Tech Stack:** Stdlib Python, `unittest`, vanilla JavaScript in `public/index.html`, no build step.

---

## Confirmed Architecture Decisions

1. `top_windows` shows the next best future fixed 3-hour windows, score-ranked, capped at 10.
   - "Next" means inside the future 7-day forecast horizon.
   - "Best" means eligible/decent windows sorted by score descending.
   - No silent fallback: if fewer than 10 eligible blocks exist, the UI counter shows the actual count, not padded fake windows.

2. Remove the current AM/PM dedupe.
   - Current behavior: after ranking candidates, backend keeps only one window per local date + AM/PM bucket.
   - Problem: `05:00-08:00` and `08:00-11:00` can both be valid next-best windows, but AM/PM dedupe hides one of them.
   - New behavior: distinct fixed 3-hour windows can both appear if both qualify.

3. Keep `top_windows` as eligible/decent windows only.
   - `top_windows` remains a recommendation surface.
   - `predictor_windows` remains the full explanation surface and includes low or blocked scored fixed blocks.

4. Sync hero selector and rolling predictor detail by stable `starts_at`, not array index.
   - `top_windows` is score-ranked.
   - `predictor_windows` is chronological.
   - Index sync would select the wrong detailed block.

5. `best_window` stays as an alias of `top_windows[0]`.
   - This preserves API compatibility.
   - It now means "best fixed 3-hour eligible window" instead of "best flexible 2-4 hour session".

6. `next_gold_window` also standardizes to fixed 3-hour blocks.
   - No multiple-window path keeps flexible 2-4 hour session logic.

## Visual Sketch

```text
Hero recommendation
┌──────────────────────────────────────────────────────────┐
│ WAIT / GO summary                                        │
│                                                          │
│   ‹  Best fixed 3h window                                │
│      Fri 08:00-11:00     score 7.4/10       3 / 10   ›   │
│                                                          │
│ Rolling 7-day predictor                                  │
│  [05-08][08-11][11-14][14-17][17-20] [next days...]      │
│          ▲ selected by hero starts_at                    │
│                                                          │
│ Detail drawer for selected rolling window                │
│ Fri 08:00-11:00 | confidence | sources | tide | factors  │
└──────────────────────────────────────────────────────────┘
```

## File Structure

- Modify: `unified_explainer.py`
  - Add constants for fixed window hours and hero limit.
  - Add a shared fixed-3-hour block builder.
  - Make `_predictor_windows()` and `_top_windows()` use the shared block builder.
  - Keep `best_window`, `next_decent_window`, `next_gold_window`, and `gold_count_7d` backward-compatible.

- Modify: `public/index.html`
  - Rename/retune carousel copy from "Best surf windows" to "Next best 3-hour windows".
  - Store and sync selected window identity with `data-selected-window-start`.
  - Make hero arrow navigation select the matching predictor bar/detail by `starts_at`.
  - Make predictor bar clicks update hero carousel when the selected predictor window exists in `top_windows`.

- Modify: `tests/test_top_windows.py`
  - Replace flexible-session expectations with fixed 3-hour window expectations.
  - Assert `top_windows` cap is 10.
  - Assert all hero windows have exactly 3 hours duration.
  - Assert `top_windows` can include multiple blocks from the same AM/PM if they are distinct fixed windows.

- Modify: `tests/test_unified_windows.py`
  - Update long-run trimming test from flexible 4-hour session behavior to fixed 3-hour behavior.

- Modify: `tests/test_mobile_html.py`
  - Assert the frontend contains stable timestamp sync helpers and the 10-window selector language.

- Modify: `scripts/print_predictor_sources.py`
  - Print `top_windows` alongside `predictor_windows` so manual diagnosis shows whether hero and rolling windows are aligned.

---

### Task 1: Add Tests For Fixed 3-Hour Backend Windows

**Files:**
- Modify: `tests/test_top_windows.py`
- Modify: `tests/test_unified_windows.py`

- [ ] **Step 1: Update the top-window cap test**

File reference: `C:\Users\Migue\Downloads\get_surf_data\tests\test_top_windows.py`

Replace the assertion in `test_returns_at_most_five` and rename the test to `test_returns_at_most_ten`.

```python
def test_returns_at_most_ten(self):
    sf, om = _build_week("2026-05-01", days=7, sf_rating=6)
    out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")
    self.assertIsInstance(out["top_windows"], list)
    self.assertLessEqual(len(out["top_windows"]), 10)
```

- [ ] **Step 2: Replace AM/PM dedupe test with fixed-neighbor inclusion**

File reference: `C:\Users\Migue\Downloads\get_surf_data\tests\test_top_windows.py`

Remove `test_one_per_halfday_bucket`. Add a test proving two good fixed windows in the same local morning are allowed when both score well.

```python
def test_top_windows_can_include_multiple_fixed_blocks_same_halfday(self):
    sf = [
        _sf_cell("2026-05-01T06:00:00+00:00", 6),
        _sf_cell("2026-05-01T09:00:00+00:00", 6),
        _sf_cell("2026-05-01T12:00:00+00:00", 6),
    ]
    om = [_om_hour(f"2026-05-01T{h:02d}:00:00+00:00") for h in range(4, 13)]

    out = unified.find_next_windows(sf, om, SPOT, "2026-05-01T03:00:00+00:00")
    starts = [window["starts_at"] for window in out["top_windows"]]

    self.assertIn("2026-05-01T04:00:00+00:00", starts)  # local 05:00
    self.assertIn("2026-05-01T07:00:00+00:00", starts)  # local 08:00
```

- [ ] **Step 3: Add exact 3-hour duration assertion for hero windows**

File reference: `C:\Users\Migue\Downloads\get_surf_data\tests\test_top_windows.py`

Add this test to `TopWindowsTests`.

```python
def test_top_windows_are_fixed_three_hour_blocks(self):
    sf, om = _build_week("2026-05-01", days=2, sf_rating=6)
    out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")

    self.assertGreater(len(out["top_windows"]), 0)
    for window in out["top_windows"]:
        start = datetime.fromisoformat(window["starts_at"])
        end = datetime.fromisoformat(window["ends_at"])
        self.assertEqual((end - start).total_seconds() / 3600, 3)
```

- [ ] **Step 4: Add top-window and predictor alignment assertion**

File reference: `C:\Users\Migue\Downloads\get_surf_data\tests\test_top_windows.py`

Add a test that every hero top window is present in the chronological predictor surface by stable `starts_at`.

```python
def test_top_windows_are_subset_of_predictor_windows_by_start_time(self):
    sf, om = _build_week("2026-05-01", days=3, sf_rating=6)
    out = unified.find_next_windows(sf, om, SPOT, "2026-04-30T23:00:00+00:00")

    predictor_starts = {window["starts_at"] for window in out["predictor_windows"]}
    for window in out["top_windows"]:
        self.assertIn(window["starts_at"], predictor_starts)
```

- [ ] **Step 5: Update long-run behavior test**

File reference: `C:\Users\Migue\Downloads\get_surf_data\tests\test_unified_windows.py`

Replace `test_long_good_run_is_trimmed_to_session_length` with fixed-block expectations.

```python
def test_long_good_run_uses_fixed_three_hour_window(self):
    sf = [
        _sf_cell("2026-05-01T08:00:00+00:00", 6),
        _sf_cell("2026-05-01T11:00:00+00:00", 6),
        _sf_cell("2026-05-01T14:00:00+00:00", 6),
        _sf_cell("2026-05-01T17:00:00+00:00", 6),
    ]
    om = [
        _om_hour(f"2026-05-01T{hour:02d}:00:00+00:00")
        for hour in range(4, 19)
    ]

    out = unified.find_next_windows(sf, om, SPOT, "2026-05-01T03:00:00+00:00")
    window = out["best_window"]
    start = datetime.fromisoformat(window["starts_at"])
    end = datetime.fromisoformat(window["ends_at"])

    self.assertEqual((end - start).total_seconds() / 3600, 3)
    self.assertRegex(window["label"], r"(Today|Tomorrow|Fri) \d{2}:00-\d{2}:00")
```

- [ ] **Step 6: Run backend window tests and confirm they fail before implementation**

Run:

```powershell
python -m unittest tests.test_top_windows tests.test_unified_windows -v
```

Expected: FAIL because `_top_windows()` still caps at 5, still uses `_session_candidates()` with 2-4 hour flexible blocks, still dedupes AM/PM buckets, and can produce labels such as `09:00-13:00`.

---

### Task 2: Standardize Backend Window Generation At Fixed 3-Hour Blocks

**Files:**
- Modify: `unified_explainer.py:1611-1708`
- Modify: `unified_explainer.py:1961-1973`

- [ ] **Step 1: Add fixed-window constants**

File reference: `C:\Users\Migue\Downloads\get_surf_data\unified_explainer.py`

Add near `SCORE_BEST_WINDOW = 5.0`.

```python
FIXED_WINDOW_HOURS = (5, 8, 11, 14, 17)
FIXED_WINDOW_DURATION_HOURS = 3
TOP_WINDOW_LIMIT = 10
```

- [ ] **Step 2: Add shared fixed block builder**

File reference: `C:\Users\Migue\Downloads\get_surf_data\unified_explainer.py:1658`

Insert this helper before `_top_windows()`.

```python
def _fixed_three_hour_blocks(scored_hours, spot):
    """Return complete local 3-hour daylight blocks, chronological."""
    buckets = {}
    for row in scored_hours:
        if row.get("decider_score") is None:
            continue
        local = _local_dt(row["dt"], spot)
        if local.hour < FIXED_WINDOW_HOURS[0] or local.hour >= 20:
            continue
        bucket_hour = FIXED_WINDOW_HOURS[0] + ((local.hour - FIXED_WINDOW_HOURS[0]) // FIXED_WINDOW_DURATION_HOURS) * FIXED_WINDOW_DURATION_HOURS
        if bucket_hour not in FIXED_WINDOW_HOURS:
            continue
        buckets.setdefault((local.date(), bucket_hour), []).append(row)

    blocks = []
    for key in sorted(buckets):
        rows = sorted(buckets[key], key=lambda row: row["dt"])
        block = []
        for row in rows:
            if block and not _continuous(block[-1], row):
                block = []
            block.append(row)
        if _block_duration_hours(block) >= FIXED_WINDOW_DURATION_HOURS:
            blocks.append(block[:FIXED_WINDOW_DURATION_HOURS])
    return blocks
```

- [ ] **Step 3: Replace `_top_windows()` implementation**

File reference: `C:\Users\Migue\Downloads\get_surf_data\unified_explainer.py:1658`

Replace the flexible session candidate implementation with fixed-block filtering and score sorting.

```python
def _top_windows(scored_hours, predicate, now_dt, spot, limit=TOP_WINDOW_LIMIT):
    candidates = []
    for block in _fixed_three_hour_blocks(scored_hours, spot):
        if not all(predicate(row) for row in block):
            continue
        score = _harmonic_mean(row["decider_score"] for row in block)
        if score is None:
            continue
        candidates.append({"block": block, "score": score})

    candidates.sort(
        key=lambda item: (
            -round(item["score"], 6),
            item["block"][0]["dt"],
        )
    )
    return [item["block"] for item in candidates[:limit]]
```

- [ ] **Step 4: Replace `_predictor_windows()` implementation to reuse shared blocks**

File reference: `C:\Users\Migue\Downloads\get_surf_data\unified_explainer.py:1685`

Replace the current duplicated bucket logic with the shared helper.

```python
def _predictor_windows(scored_hours, now_dt, spot):
    """Return fixed, non-overlapping local forecast blocks for the hero ribbon."""
    payloads = []
    for block in _fixed_three_hour_blocks(scored_hours, spot):
        payload = _window_payload(block, now_dt, spot)
        if payload is not None:
            payloads.append(payload)
    return payloads
```

- [ ] **Step 5: Use the shared top-window limit in `find_next_windows()`**

File reference: `C:\Users\Migue\Downloads\get_surf_data\unified_explainer.py:1961`

Replace the call that still passes flexible min/max settings.

```python
top_blocks = _top_windows(scored, _hour_is_decent, now_dt, spot, limit=TOP_WINDOW_LIMIT)
top_windows = [_window_payload(block, now_dt, spot) for block in top_blocks]
best_window = top_windows[0] if top_windows else None
gold_block = _best_session(scored, _hour_is_gold, min_hours=2, max_hours=4)
```

- [ ] **Step 6: Standardize `next_gold_window` to fixed 3-hour**

Use the same fixed block selector for gold windows.

```python
gold_blocks = _top_windows(scored, _hour_is_gold, now_dt, spot, limit=1)
gold_window = _window_payload(gold_blocks[0], now_dt, spot) if gold_blocks else None
```

Then return:

```python
"next_gold_window": gold_window,
```

No silent fallback: do not leave flexible gold behavior in place. Multiple-window logic is fixed 3-hour.

- [ ] **Step 7: Run backend tests**

Run:

```powershell
python -m unittest tests.test_top_windows tests.test_unified_windows tests.test_surfline_best_windows_predictor -v
```

Expected: PASS after updating tests and implementation. If failures mention expected `09:00-13:00`, update tests to fixed 3-hour labels only.

---

### Task 3: Make Hero Arrows Select The Matching Rolling Predictor Detail

**Files:**
- Modify: `public/index.html:2253-2613`
- Modify: `tests/test_mobile_html.py`

- [ ] **Step 1: Add stable window identity helpers**

File reference: `C:\Users\Migue\Downloads\get_surf_data\public\index.html:2495`

Add these helpers before `_heroState(card)`.

```javascript
function windowStartKey(win) {
  return win && typeof win.starts_at === 'string' ? win.starts_at : '';
}

function clampIndex(index, length) {
  if (!length) return 0;
  return Math.max(0, Math.min(Number(index) || 0, length - 1));
}

function findWindowIndexByStart(windows, startsAt) {
  if (!startsAt || !Array.isArray(windows)) return -1;
  return windows.findIndex(win => windowStartKey(win) === startsAt);
}
```

- [ ] **Step 2: Initialize selected start from the first hero window**

File reference: `C:\Users\Migue\Downloads\get_surf_data\public\index.html:2483`

Modify the hero state attributes so the selected window start is explicit.

```javascript
const selectedStart = topWindows.length ? windowStartKey(topWindows[0]) : '';
const heroState = JSON.stringify({ windows: topWindows, predictorWindows, currentWindowText });
return `<div class="hero-card tier-${escapeHtml(tier)}" data-hero-state="${escapeHtml(heroState)}" data-hero-index="0" data-predictor-index="0" data-selected-window-start="${escapeHtml(selectedStart)}">
```

- [ ] **Step 3: Sync `_renderHeroSlot()` from selected start**

File reference: `C:\Users\Migue\Downloads\get_surf_data\public\index.html:2503`

Replace index lookup in `_renderHeroSlot()` with timestamp sync.

```javascript
function _renderHeroSlot(card) {
  const state = _heroState(card);
  const windows = Array.isArray(state.windows) ? state.windows : [];
  const predictorWindows = Array.isArray(state.predictorWindows) ? state.predictorWindows : [];
  const slot = card.querySelector('.hero-window-slot');
  const predictorSlot = card.querySelector('.hero-predictor-slot');
  const selectedStart = card.getAttribute('data-selected-window-start') || '';

  if (slot) {
    let idx = findWindowIndexByStart(windows, selectedStart);
    if (idx === -1) idx = clampIndex(card.getAttribute('data-hero-index'), windows.length);
    card.setAttribute('data-hero-index', String(idx));
    if (windows.length) {
      slot.innerHTML = renderHeroWindowCarousel(windows, idx, state.currentWindowText || '');
    } else {
      slot.innerHTML = renderHeroWindow(null, 'No clean window found in the next 7 days.', state.currentWindowText || '');
    }
  }

  if (predictorSlot) {
    let predictorIdx = findWindowIndexByStart(predictorWindows, selectedStart);
    if (predictorIdx === -1) predictorIdx = clampIndex(card.getAttribute('data-predictor-index'), predictorWindows.length);
    card.setAttribute('data-predictor-index', String(predictorIdx));
    predictorSlot.innerHTML = renderPredictorRibbon(predictorWindows, predictorIdx);
  }

  const carousel = slot && slot.querySelector('.hero-window-carousel');
  if (carousel && card.dataset.heroFocusPending === '1') {
    carousel.focus({ preventScroll: true });
    card.dataset.heroFocusPending = '0';
  }

  const predictor = predictorSlot && predictorSlot.querySelector('.hero-predictor-bar[aria-pressed="true"]');
  if (predictor && card.dataset.predictorFocusPending === '1') {
    predictor.focus({ preventScroll: true });
    predictor.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    card.dataset.predictorFocusPending = '0';
  }
}
```

- [ ] **Step 4: Update hero arrow stepping to set selected start**

File reference: `C:\Users\Migue\Downloads\get_surf_data\public\index.html:2539`

Replace `_heroStep()`.

```javascript
function _heroStep(card, delta) {
  const state = _heroState(card);
  const windows = Array.isArray(state.windows) ? state.windows : [];
  if (windows.length <= 1) return;
  const cur = clampIndex(card.getAttribute('data-hero-index'), windows.length);
  const next = clampIndex(cur + delta, windows.length);
  if (next === cur) return;
  card.setAttribute('data-hero-index', String(next));
  card.setAttribute('data-selected-window-start', windowStartKey(windows[next]));
  card.dataset.heroFocusPending = '1';
  _renderHeroSlot(card);
}
```

- [ ] **Step 5: Update predictor stepping and clicks to sync hero when possible**

File reference: `C:\Users\Migue\Downloads\get_surf_data\public\index.html:2551`

Replace `_predictorStep()`.

```javascript
function _predictorStep(card, delta) {
  const state = _heroState(card);
  const windows = Array.isArray(state.predictorWindows) ? state.predictorWindows : [];
  if (windows.length <= 1) return;
  const cur = clampIndex(card.getAttribute('data-predictor-index'), windows.length);
  const next = clampIndex(cur + delta, windows.length);
  if (next === cur) return;
  card.setAttribute('data-predictor-index', String(next));
  card.setAttribute('data-selected-window-start', windowStartKey(windows[next]));
  const heroIdx = findWindowIndexByStart(state.windows || [], windowStartKey(windows[next]));
  if (heroIdx !== -1) card.setAttribute('data-hero-index', String(heroIdx));
  card.dataset.predictorFocusPending = '1';
  _renderHeroSlot(card);
}
```

Then update the predictor click handler.

```javascript
const idx = clampIndex(bar.dataset.index, (state.predictorWindows || []).length);
const selected = state.predictorWindows[idx];
heroCard.setAttribute('data-predictor-index', String(idx));
heroCard.setAttribute('data-selected-window-start', windowStartKey(selected));
const heroIdx = findWindowIndexByStart(state.windows || [], windowStartKey(selected));
if (heroIdx !== -1) heroCard.setAttribute('data-hero-index', String(heroIdx));
heroCard.dataset.predictorFocusPending = '1';
_renderHeroSlot(heroCard);
```

- [ ] **Step 6: Retune selector language for 10 windows**

File reference: `C:\Users\Migue\Downloads\get_surf_data\public\index.html:2258`

Change the ARIA label so this UI is not described as generic "best surf windows".

```javascript
return `<div class="hero-window-carousel" role="region" aria-live="polite" aria-label="Next best 3-hour surf windows" tabindex="0">
```

- [ ] **Step 7: Add HTML static assertions**

File reference: `C:\Users\Migue\Downloads\get_surf_data\tests\test_mobile_html.py`

Extend `test_predictor_ribbon_markup_and_handlers`.

```python
for required in (
    "function windowStartKey",
    "function findWindowIndexByStart",
    "data-selected-window-start",
    "Next best 3-hour surf windows",
    "card.setAttribute('data-selected-window-start'",
):
    self.assertIn(required, self.html)
```

- [ ] **Step 8: Run frontend static tests**

Run:

```powershell
python -m unittest tests.test_mobile_html -v
```

Expected: PASS.

---

### Task 4: Update Diagnostic Script To Compare Hero And Predictor Windows

**Files:**
- Modify: `scripts/print_predictor_sources.py`

- [ ] **Step 1: Print top windows before predictor windows**

File reference: `C:\Users\Migue\Downloads\get_surf_data\scripts\print_predictor_sources.py:27`

Modify `print_spot()`.

```python
top_windows = unified.get("top_windows") or []
windows = unified.get("predictor_windows") or []

print(f"top_count={len(top_windows)}")
print("top idx | label | score | starts_at")
for idx, win in enumerate(top_windows):
    print(
        f"{idx:02d} | {win.get('label')} | {win.get('score')} | {win.get('starts_at')}"
    )
```

- [ ] **Step 2: Add alignment warning with no fallback**

File reference: `C:\Users\Migue\Downloads\get_surf_data\scripts\print_predictor_sources.py:27`

After printing counts, compare starts.

```python
predictor_starts = {win.get("starts_at") for win in windows}
missing_from_predictor = [
    win.get("starts_at")
    for win in top_windows
    if win.get("starts_at") not in predictor_starts
]
if missing_from_predictor:
    print(f"ERROR top_windows_not_in_predictor={','.join(missing_from_predictor)}")
```

- [ ] **Step 3: Run script against local server after server verification**

Run after `python server.py` is running:

```powershell
python scripts/print_predictor_sources.py --spots carcavelos caparica --level improver
```

Expected: each spot prints `top_count<=10`, `predictor_count>top_count` in normal data, and no `ERROR top_windows_not_in_predictor` line.

---

### Task 5: Full Verification

**Files:**
- No new files.
- Verify all modified files.

- [ ] **Step 1: Run focused tests**

```powershell
python -m unittest tests.test_top_windows tests.test_unified_windows tests.test_surfline_best_windows_predictor tests.test_mobile_html -v
```

Expected: PASS.

- [ ] **Step 2: Run full offline suite**

```powershell
python -m unittest discover -v
```

Expected: PASS.

- [ ] **Step 3: Start local server**

```powershell
python server.py
```

Expected: local app available on `http://127.0.0.1:8765`.

- [ ] **Step 4: Smoke API for both spots**

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/sync?spot=carcavelos&level=improver&refresh=1' -UseBasicParsing
Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/sync?spot=caparica&level=improver&refresh=1' -UseBasicParsing
```

Expected: HTTP 200 and JSON payloads with `unified.top_windows`, `unified.predictor_windows`, and `best_window`.

- [ ] **Step 5: Run diagnostic script**

```powershell
python scripts/print_predictor_sources.py --spots carcavelos caparica --level improver
```

Expected:
- `top_count` is never greater than `10`.
- Every `top_windows[*].starts_at` exists in `predictor_windows[*].starts_at`.
- No line starts with `ERROR top_windows_not_in_predictor=`.

- [ ] **Step 6: Browser verification**

Open `http://127.0.0.1:8765` and verify:
- Hero carousel counter can show values up to `10 / 10` when enough eligible blocks exist.
- Right arrow changes the hero window.
- Right arrow also moves the highlighted predictor bar and detail drawer to the matching `starts_at`.
- Clicking a predictor bar updates the detail drawer.
- Clicking a predictor bar that also exists in `top_windows` updates the hero carousel counter to that matching hero window.
- Keyboard `ArrowLeft` and `ArrowRight` work in both the hero carousel and predictor ribbon.

## Commit Plan

Commit after verification:

```powershell
git add unified_explainer.py public/index.html tests/test_top_windows.py tests/test_unified_windows.py tests/test_mobile_html.py scripts/print_predictor_sources.py docs/superpowers/plans/2026-05-05-standardize-window-selector.md
git commit -m "fix: standardize surf window selection"
```

## Self-Review

- Spec coverage: fixed 3-hour standardization is covered in Tasks 1-2; arrow-oriented next-best selector up to 10 windows is covered in Tasks 2-3; selector sync to rolling-window details is covered in Task 3; diagnostic visibility is covered in Task 4.
- Placeholder scan: no `TBD`, `TODO`, "fill in", or silent fallback instructions remain.
- Type consistency: sync uses `starts_at` consistently across backend payloads, hero windows, and predictor windows.
