# Evidence-Based Surf Decider Scoring Doctrine

**Project:** Surf Decider scoring-methodology research  
**Phase:** Research report only — no code changes  
**Prepared for:** `unified_explainer.py`, `open_meteo_explainer.py`, `noaa_gfs_explainer.py`, `copernicus_ibi_explainer.py`  
**Date:** 2026-05-01  

---

## 0. Executive Finding

The strongest conclusion from the available research is that **a surf-quality decider should not be a simple linear score plus a separate stack of duplicate penalties**. The current design has useful ingredients — height, period, wind, direction, shape, tide, multiple forecast sources, and hard gates — but the evidence points toward a cleaner architecture:

1. **Predict the physical surf state first**: breaking height, wave power/energy, period, swell direction, wind direction/speed, wind-sea/chop ratio, secondary-swell interference, and tide state.
2. **Convert each physical variable into a smooth, spot- and skill-specific suitability function**, mostly on a 0–1 scale.
3. **Aggregate suitability factors with a calibrated multiplicative/geometric or fuzzy-logic method**, using hard gates only for truly impossible/dangerous/no-surf cases.
4. **Use source spread as forecast confidence, not as another quality penalty**, unless historical validation proves that disagreement systematically lowers realized surf quality.
5. **Replace fixed source weights with source-skill weights** learned from historical error by spot, forecast horizon, and condition regime.
6. **Derive tier thresholds empirically** from ground-truth labels using ROC/precision-recall/calibration, rather than treating 5.0 / 6.2 / 7.5 as universal constants.

The current formula likely double-counts failure modes. For example, poor swell direction lowers the source score, may trigger a source verdict, contributes to spread, and can also trigger a separate direction penalty. Onshore/choppy wind similarly affects wind score, purity score, model verdict, hard-gate shape blocks, and sometimes final penalties. That makes the final score hard to calibrate and can create pessimistic outputs even when a human forecaster would say “marginal but surfable.”

The research does **not** reveal a public, peer-reviewed universal 0–10 surf-quality scoring formula with accepted coefficients. Instead, the evidence converges around: skill-specific height/period suitability, wave power rather than height alone, wind/cleanliness as a first-class factor, spot-specific direction and bathymetry, tide as a local modifier, and validation against observations rather than hand-picked weights.

---

## 1. Research Scope and Method

This doctrine executed the planned streams against public academic, industry, and government/operational sources. Sources were prioritized in this order:

1. Peer-reviewed coastal-engineering / surf-science literature.
2. Operational wave-forecast verification and ensemble post-processing literature.
3. Official surf-forecast company documentation and technical blogs.
4. Government / institutional data documentation for validation datasets.
5. Decision-science literature on weighted indices, additive aggregation, and non-compensatory rules.

### Limitations

- Surfline, MagicSeaweed, Spitcast, and other industry products do not publicly disclose complete scoring algorithms or coefficients.
- Peer-reviewed surf-science papers usually study **surf-break morphology and wave quality mechanics**, not consumer-facing “go/maybe/skip” classifiers.
- Published ML wave papers often predict physical wave variables, not surfer-rated session quality.
- Lisbon-specific ground truth is not fully public in one source; a validation dataset will need to be assembled.

These limitations are important because they mean the next scoring model should be treated as a **calibrated decision system**, not as a formula copied from a known public standard.

---

## 2. Current Formula Diagnosis

### 2.1 Existing design being evaluated

The current system does the following:

- Converts four sources into 0–10 source scores:
  - Surf-Forecast.com: 40% base weight.
  - Open-Meteo Marine: 30% base weight.
  - NOAA GFS Wave: 20% base weight.
  - Copernicus IBI: 10% base weight.
- Scores OM/GFS/IBI using a linear weighted formula:

```text
score = Height*0.30 + Period*0.25 + Purity*0.20 + SwellDirection*0.15 + Wind*0.10
```

- Blends available source scores with a weighted harmonic mean.
- Subtracts:
  - spread penalty up to 1.0,
  - direction penalty up to 1.5,
  - tide penalty 0.6.
- Applies several hard gates before final tiering.
- Uses fixed cutoffs:
  - Gold: ≥ 7.5 plus model data.
  - Green: ≥ 6.2.
  - Yellow: ≥ 5.0.
  - Red: < 5.0 or hard gate.

### 2.2 Main failure modes suggested by research

#### A. Double-counting

A single physical problem can reduce the score multiple times. Example: onshore wind can lower wind score, lower purity/shape, cause a source verdict to skip, trigger a hard gate, create source spread, and subtract a final direction/shape penalty. Decision-science literature warns that additive composite indicators become unstable when criteria are not independent and when the same phenomenon appears in multiple terms.

#### B. Monotonic height and period assumptions

The current model gives height a linear increase until 3 m and gives periods >15 s a perfect 10. Research and industry guidance do not support that as universal. Long-period swell increases power and can turn moderate open-ocean height into heavy, risky surf. Suitability should be skill- and spot-specific, often bell-shaped or trapezoidal rather than monotonic.

#### C. Wind likely underweighted

Industry systems repeatedly emphasize wind direction and speed as core determinants of surface quality. Surfline’s model rating documentation says its model factors are breaking wave height plus wind speed/direction; Surf-Forecast says onshore wind drops the star rating in proportion to wind speed. In the current `_hour_score`, wind direction has only 10%, while purity partly proxies wind chop. This split can work only if wind-chop ratio is reliable; otherwise true local wind effect is underrepresented.

#### D. Harmonic mean is probably too punitive as a default source blend

The weighted harmonic mean is defensible when all sources are measuring the same utility and one low source should veto the result. But wave-forecast ensemble literature typically uses bias correction, model output statistics, Bayesian model averaging, ensemble post-processing, or skill-weighted averaging — not a harmonic mean of subjective quality scores. A bad source should reduce confidence unless validation shows it reliably detects true failures.

#### E. Spread penalty mixes uncertainty with quality

Source disagreement means “less certain,” not necessarily “worse surf.” A spread penalty can make the decider pessimistic in conditions where one model has a local bias or where a regional model resolves nearshore transformation better than a global model. Forecast spread should primarily be exposed as confidence.

#### F. Hard gates are too broad

Hard gates should encode physical impossibility, safety, or known local non-working states. Some current gates look like ordinary “bad but maybe surfable” factors. For example, “wind ≥5 km/h and onshore by >150°” is likely too low for an instant shape block; 5 km/h is very light wind. Industry descriptions support proportional onshore degradation, with flat/blown-out/very strong wind producing the lowest ratings.

---

## 3. Stream 1 — Academic Literature on Surf-Quality Scoring

### 3.1 What academic surf science actually studies

The core surf-science literature does not usually publish a consumer-style 0–10 score. Instead, it identifies the physical components of surf quality:

- wave height at breaking,
- wave period / energy,
- peel angle,
- breaking intensity,
- wave type: spilling, plunging, collapsing, surging,
- seabed gradient and bathymetry,
- swell direction relative to contours,
- focus/shadowing/refraction effects,
- consistency of takeoff point,
- skill-level suitability.

The practical implication is that the scoring model should not assume all breaks share one universal function. A point break, reef, and beach break can have very different responses to the same offshore Hs/Tp/direction.

### 3.2 Skill-specific surfability is research-supported

Hutt, Black, and Mead’s classification work is directly relevant because it links surf-break characteristics to surfing skill. The important product implication is: **beginner/improver/intermediate/advanced tiers are not just UI personalization; they are physically meaningful.** A single score should not be universal across skill levels.

The current system already acknowledges skill in narrative terms, but `_hour_score()` itself uses generic height and period scoring. The next version should move skill-tier logic into the scoring function itself.

Recommended interpretation:

- Beginner scoring should peak at small-to-moderate, low-risk, slower waves.
- Advanced scoring can reward larger and longer-period conditions, but should still penalize extreme energy, closing out, or dangerous wind/tide combinations.
- Long-period swell should not simply receive a 10.0 for every tier.

### 3.3 Wave quality depends on peel and breaking mechanics, not just offshore wave statistics

Mead and Black’s work on functional components and breaking intensity emphasizes that good surfing waves require a surfable breaking pattern, not just height and period. Breaking intensity, peel angle, and seabed gradient are central to whether a wave can be ridden.

This creates a practical issue: most API sources provide offshore or nearshore wave parameters, not peel angle or seabed gradient. Therefore the decider should use spot metadata to approximate missing local physics:

- spot type: beach / point / reef / jetty,
- optimal swell direction window,
- accepted tide window,
- known shelter from wind-wave directions,
- known closeout height or power,
- known minimum period / direction response.

### 3.4 Important surf-science variables missing or underdeveloped in the current score

| Variable | Why it matters | Current treatment | Recommended change |
|---|---|---|---|
| Breaking height, not just offshore wave height | Surfers experience the broken-wave face height at the break, not raw model Hs. | Height uses `wave_h / 3m * 10`. | Estimate breaking/surf height with spot coefficient, bathymetry/exposure, and period/direction amplification. |
| Wave power / energy | Combines height and period; energy scales roughly with height squared and period. | Height and period are separate linear/step factors. | Add power/energy suitability, not just height + period. |
| Skill-specific optimum range | Good for one skill level can be dangerous or boring for another. | Mostly separate from `_hour_score`. | Use tier-specific height/power membership functions. |
| Peel angle / breaker type | Determines rideability, not just size. | Not directly represented. | Approximate with spot type, swell direction, tide, and known closeout/shelter metadata. |
| Seabed gradient / bathymetry | Controls breaking intensity and whether waves spill, plunge, or surge. | Not directly represented. | Add spot metadata where available; otherwise use conservative priors by break type. |
| Secondary swell interference | Crossed swells can degrade shape despite good primary swell. | Mentioned in factors but not clearly in `_hour_score`. | Add explicit secondary-interference factor. |
| Tide modulation | Often local and nonlinear. | Late penalty and hard gates. | Treat as spot-specific suitability multiplier/gate, not generic subtraction. |

### 3.5 Stream 1 conclusion

The academic surf-science literature supports the current input set but not the current linear scoring form. It suggests moving from generic weighted sums toward **spot- and skill-specific suitability curves** with local metadata. The most important change is to replace monotonic “bigger/longer is better” functions with a physically grounded, tier-specific suitability model.

---

## 4. Stream 2 — Multi-Source / Ensemble Forecast Blending

### 4.1 Wave-model verification standards

Operational wave-model verification commonly evaluates physical variables against observations using:

- mean error / bias,
- RMSE,
- scatter index,
- correlation coefficient,
- sometimes slope/intercept or additional reliability metrics.

The WMO wave-analysis guide emphasizes ongoing verification against in-situ measurements, especially buoys, and reports metrics for wind speed, wave height, and peak period. This implies that source weights should be based on **measured performance**, not field completeness alone.

### 4.2 Ensemble post-processing is standard; harmonic mean is not

Roulston et al. (2005) show that post-processing ECMWF ensemble wave forecasts improves reliability and expected-error prediction for significant wave height. Raftery et al. (2005) establish Bayesian Model Averaging as a principled way to combine ensemble forecasts with performance-based weights.

Operational meteorology generally handles model disagreement through:

- bias correction,
- ensemble Model Output Statistics / EMOS,
- Bayesian Model Averaging / BMA,
- regime-dependent weighting,
- probabilistic calibration,
- spread-skill relationships.

There is no strong evidence that a harmonic mean of quality scores is a preferred method for blending independent wave models.

### 4.3 Recommended source-blending doctrine

#### Preferred long-term approach

Blend the **raw physical variables**, then compute the surf score from the blended state.

Example:

```text
For each source i and forecast horizon h:
  bias_correct_i(variable, spot, h, regime)
  estimate source error_i(variable, spot, h, regime)

For each variable V:
  V_consensus = skill_weighted_average(V_i)
  V_uncertainty = spread/error estimate

Score = surf_suitability(V_consensus, spot, skill)
Confidence = f(V_uncertainty, source_count, data_completeness)
```

This is better than blending already-compressed 0–10 source scores because it preserves information. For instance, two sources can both score 6.0 for different reasons — one due to poor period, another due to onshore wind. Blending raw variables avoids losing that diagnostic structure.

#### Good short-term approach

If code constraints require keeping source scores, replace harmonic mean with either:

1. **Calibrated weighted arithmetic mean** plus separate confidence, or
2. **Weighted geometric mean** of normalized 0–1 source scores.

The geometric mean is a reasonable compromise because it is non-compensatory enough to punish one bad source, but less extreme and more interpretable than harmonic mean near low scores.

```text
score_consensus = 10 * Π(max(score_i / 10, ε) ^ w_i)
```

Use `ε` to avoid total collapse when a source is available but noisy. Keep true hard gates separate.

### 4.4 Source weights should be dynamic

Current adaptive weights nudge sources based on available fields. Completeness is useful, but it is not the same as accuracy. A source can be complete and wrong, or incomplete but locally skillful for a critical variable.

Recommended dynamic reliability weight:

```text
error_i = rolling RMSE or MAE of source i against ground truth
raw_weight_i = prior_weight_i * exp(-lambda * error_i)
w_i = raw_weight_i / Σ raw_weight_i
```

Use separate weights by:

- spot,
- forecast horizon,
- season,
- swell direction regime,
- wave-height regime,
- variable type.

Example: IBI may deserve a higher weight for nearshore/regional wave transformation if validated locally, while GFS may deserve more weight for open-ocean swell timing or wind in certain regimes.

### 4.5 Spread should become confidence

Source spread is valuable. But it should usually affect **confidence**, not surf quality.

Recommended output model:

```text
quality_score = estimated surf quality if forecast verifies
confidence_score = certainty that conditions will match estimate
```

Example user-facing outputs:

- “GO — score 7.1, confidence high.”
- “MAYBE — score 6.4, confidence low because OM/GFS disagree on wind.”

A small quality penalty for uncertainty can remain, but it should be calibrated and much smaller than the current independent spread penalty unless validation shows otherwise.

---

## 5. Stream 3 — Industry Forecasting Systems

### 5.1 Surfline

Surfline documentation indicates several important design principles:

- Model ratings update hourly and are driven by LOTUS.
- LOTUS model ratings use breaking wave height plus wind speed/direction.
- Model ratings do not include tide or wave shape in the simplified rating explanation.
- Forecaster-observed ratings include full ocean state: size, shape, ocean surface, tide, wind.
- Surfline uses decades of observations and forecaster input to train ML systems.
- Good/Epic ratings are rare and require human forecaster observation.

Doctrine implication:

- Separate **model potential** from **observed/forecaster override**.
- Use ML/calibration on historical observations where possible.
- Treat “Good/Epic/Gold” as a high-precision class, not just score ≥ threshold.
- Do not attempt to encode every local effect as a generic penalty; use observational corrections.

### 5.2 Surf-Forecast.com

Surf-Forecast’s FAQ is one of the clearest public statements of a star-rating concept. It says:

- Rating is 1–10.
- It is based on swell size and character.
- Bigger swell and longer period increase rating.
- Onshore wind reduces rating in proportion to wind speed.
- Flat conditions, blown-out onshore waves, or very strong winds in any direction can produce 0.
- Wave energy can be a useful guide because it combines wave size and period.
- Multiple significant swells can degrade the session through short gaps and lumps.
- Wind waves can ruin shape, depending on direction and shelter.

Doctrine implication:

- SF rating should not be converted and then punished again for the same wind/direction/shape issues.
- Add wave energy/power as a feature.
- Model secondary swell and wind-wave interference explicitly.

### 5.3 MagicSeaweed

MagicSeaweed’s exact star formula is no longer officially public after shutdown/acquisition. A peer-reviewed survey of surfer-facing meteorological services reports that MagicSeaweed used NOAA WAVEWATCH III and PROTEUS GLOBAL and exposed surf height, wind gusts, wave direction, wind intensity/direction, tides, quality rating, and primary/secondary swell information.

Doctrine implication:

- It is reasonable to include secondary swell and quality rating as distinct displayed factors.
- It is not evidence for a precise weight vector.

### 5.4 Stormglass

Stormglass exposes wave height/direction, swell height/direction, secondary swell/direction, wind-wave height/direction, tide, and many meteorological fields. It is a data provider rather than a transparent surf-score methodology.

Doctrine implication:

- The data schema itself reflects important variables: primary swell, secondary swell, wind waves, tide, wind.
- A complete scoring model should use partitions, not just total wave height.

### 5.5 Spitcast

Public API docs indicate Spitcast outputs wave height and a shape-quality value:

- 0.0 = Poor,
- 0.5 = Poor-Fair,
- 1.0 = Fair,
- >1.0 = Good.

Doctrine implication:

- Separating height and shape is an industry pattern.
- Shape should be its own score/multiplier rather than being scattered across wind, purity, verdicts, and final penalties.

### 5.6 Windy / Windguru / forecast aggregators

Windy and similar tools expose model comparison and raw variables rather than fully transparent surf scoring. The survey literature notes these tools focus on wave height, wave period, wind, direction, tide, primary/secondary swell, and model comparisons.

Doctrine implication:

- Users benefit from seeing raw factors and confidence/disagreement, not just a single compressed score.
- The decider can keep a headline but should preserve factor diagnostics.

---

## 6. Stream 4 — Predictor-Importance Evidence

### 6.1 Best-evidence predictor ranking

This ranking combines academic surf science, operational forecasting practice, and industry documentation.

| Rank | Predictor | Why it matters | Scoring implication |
|---:|---|---|---|
| 1 | **Breaking wave height / surf height relative to skill** | Determines whether waves are rideable, too small, or unsafe. Surf science links wave characteristics to skill. Industry products center ratings on surf height. | Replace linear height cap with skill-specific suitability curve. |
| 2 | **Wind cleanliness: direction × speed × local shelter** | Onshore wind degrades face quality; offshore can clean waves but too strong can make catching waves difficult. | Increase wind/shape influence; use continuous onshore/offshore component, not only direction bins. |
| 3 | **Wave energy / power: H² × period** | Period and height jointly determine power; long-period small swell can make larger surf; big long-period swell can be hazardous. | Add wave-power suitability and tier-specific risk. |
| 4 | **Swell period / spectral character** | Short-period wind sea is usually lower quality; longer period carries energy and improves organization but can increase risk. | Period should be nonlinear and tier-aware, not always maxed above 15 s. |
| 5 | **Swell direction vs spot exposure/optimal window** | Direction controls whether energy reaches the break and whether it refracts/peels properly. | Direction should be a spot-specific exposure function, not only a generic angular-difference penalty. |
| 6 | **Wind-sea/chop ratio and secondary swell interference** | Crossed swell/wind waves create lumps, short gaps, and poor shape. | Add explicit partition-based shape factor. |
| 7 | **Tide relative to spot’s working window** | Tide can improve or shut down many breaks, but effect is highly local. | Use spot-specific tide membership/gate. Do not apply generic tide subtraction everywhere. |
| 8 | **Bathymetry / break type / seabed gradient** | Controls peel angle, breaker type, breaking intensity, and closeout tendency. | Encode in spot metadata and transformation coefficients. |
| 9 | **Forecast uncertainty / source disagreement** | Predicts risk of the forecast being wrong, not necessarily poor quality. | Display confidence; only penalize quality after calibration. |
| 10 | **Data completeness** | Missing fields lower reliability. | Affects confidence and source weight more than quality. |

### 6.2 Wave power should be added

Wave power/energy scales with height squared and period. A simple deep-water approximation is:

```text
P ≈ (ρ g² / 64π) * Hs² * Te
```

In practical units, wave power is often approximated as proportional to `Hs² * Te`. Surf-Forecast explicitly recommends wave energy as a guide because it combines wave size and period and can better represent likely surf power than height alone.

Recommended score feature:

```text
energy_index = H_breaking^2 * T_energy_or_peak
```

Then convert it into a skill-specific suitability curve:

```text
energy_suitability = trapezoid_or_bell(energy_index, skill, spot)
```

### 6.3 Height should be bell-shaped, not monotonic

Current:

```text
height_score = min(wave_h / 3.0 * 10, 10)
```

This makes 3 m always ideal and 4 m no worse than 3 m. That is not appropriate for beginners and not always appropriate for advanced surfers if the spot closes out.

Recommended:

```text
height_suitability =
  0.0 below no-surf minimum
  rising shoulder into ideal range
  1.0 within ideal range
  falling shoulder above comfort/quality range
  0.0 or gate above safety/closeout range
```

Example priors, to be validated by spot:

| Skill | Too small | Ideal | Marginal high | Dangerous / likely skip |
|---|---:|---:|---:|---:|
| Beginner | <0.4 m | 0.7–1.2 m | 1.3–1.6 m | >1.8–2.0 m |
| Improver | <0.5 m | 0.8–1.5 m | 1.6–2.0 m | >2.3–2.5 m |
| Intermediate | <0.6 m | 1.0–2.0 m | 2.1–2.7 m | >3.0 m unless expert spot |
| Advanced | <0.7 m | 1.2–3.0 m | 3.1–3.8 m | spot-dependent |

These are not final coefficients; they are priors for validation.

### 6.4 Wind should be modeled as a vector effect

Instead of only angular-difference bins, use wind speed projected onto onshore/offshore/cross-shore directions.

Recommended concept:

```text
onshore_component  = wind_speed * max(0, cos(diff_from_onshore))
offshore_component = wind_speed * max(0, cos(diff_from_offshore))
cross_component    = wind_speed * abs(sin(diff_from_offshore))
```

Then:

- Light onshore: moderate penalty, not hard gate.
- Moderate/strong onshore: strong shape penalty.
- Very strong onshore + high wind-wave ratio: hard gate.
- Light-to-moderate offshore: reward.
- Strong offshore: yellow risk due to difficulty catching waves / blown-back faces.
- Cross-offshore: often acceptable.
- Cross-onshore: spot-dependent.

### 6.5 Secondary swell / wind-sea interference should be explicit

The current purity factor looks at wind chop/total wave ratio. That is useful but incomplete. Secondary swell from a materially different direction or period can degrade shape even when wind chop is low.

Recommended metrics:

```text
windsea_ratio = wind_wave_height / total_wave_height
secondary_ratio = secondary_swell_height / primary_swell_height
cross_angle = angular_diff(primary_direction, secondary_direction)
period_gap = abs(primary_period - secondary_period)
interference_score = f(secondary_ratio, cross_angle, period_gap)
```

A crossed secondary swell matters most when it is a meaningful fraction of the primary and arrives from a different angle.

---

## 7. Stream 5 — Decision-Theoretic Framing

### 7.1 Additive weighted sums require independence assumptions

MCDA/composite-indicator literature warns that additive weighted aggregation is sensitive to scaling and compensation assumptions. Linear aggregation is most defensible when criteria are preferentially independent and weights represent tradeoffs. The current surf criteria are not independent:

- wind speed and wind-wave ratio are related,
- period and power are related,
- height and power are related,
- direction affects breaking height and shape,
- tide affects breaking height, shape, and safety,
- source spread can reflect any underlying factor.

Therefore, adding all of these as independent penalties can distort results.

### 7.2 Use three layers instead of score-plus-penalty-stack

Recommended architecture:

#### Layer A — Hard constraints

Only apply hard gates for conditions that should truly override all scoring:

- physically flat / no ridable waves,
- severe safety hazard for selected skill tier,
- known local tide shutdown or dry reef hazard,
- severe blown-out shape with meaningful wind speed and wind-sea energy,
- missing critical data so severe that the score cannot be trusted.

#### Layer B — Suitability functions

Convert all remaining factors into smooth 0–1 functions:

```text
height_suitability
power_suitability
period_suitability
wind_shape_suitability
swell_direction_suitability
secondary_interference_suitability
tide_suitability
```

#### Layer C — Aggregation and confidence

Aggregate factor suitability without duplicate penalties:

```text
base_quality = weighted_geometric_mean(factors)
score = 10 * base_quality
confidence = f(source_spread, source_count, data_completeness, recent_model_skill)
```

### 7.3 Why geometric/multiplicative scoring fits surf better than pure arithmetic

Surf quality is partly non-compensatory. Huge clean swell with completely wrong direction is not good. Perfect wind with no waves is not good. Ideal tide with blown-out onshore wind is not good.

A weighted geometric mean captures this better than an arithmetic mean because very low factor values drag the final score down naturally, without needing several extra penalties.

Example:

```text
score = 10 * Π(factor_j ^ alpha_j)
```

where factors are 0–1 and exponents sum to 1.

### 7.4 Fuzzy logic is a credible near-term alternative

A fuzzy surf-specific wave-height forecast paper reported an expert-rule system using wave height and wind inputs with 86% forecast accuracy over two years at Kizakihama, Miyazaki. This is not a complete surf-quality score, but it supports the idea that surf forecast decision rules can be nonlinear, expert-informed, and data-validated.

A fuzzy system can encode rules like:

```text
IF height is ideal AND wind is light_offshore AND period is good THEN quality is high.
IF height is large AND period is long AND skill is beginner THEN safety is poor.
IF secondary_swell is strong AND cross_angle is high THEN shape is poor.
```

This may be easier to reason about than ML and easier to validate than an ad-hoc penalty stack.

### 7.5 Penalty calibration doctrine

Penalties should only exist when they represent something not already included in factor scoring.

Recommended decision:

| Current penalty | Keep? | Doctrine |
|---|---|---|
| Spread penalty | Not as quality default | Move to confidence. Optional small calibrated score haircut only after validation. |
| Direction penalty | Usually no | Fold into swell-direction suitability and source-specific scoring. Keep hard gate only for totally wrong exposure. |
| Tide penalty | Usually no | Fold into tide suitability. Hard gate only for spot-specific shutdown/safety. |
| Shape/onshore hard block | Yes, but revise | Use wind speed × onshore component × wind-wave ratio; 5 km/h should not hard gate. |

---

## 8. Stream 6 — Validation / Ground Truth

### 8.1 Validation should be mandatory before changing weights permanently

The current coefficients are intuitive. The proposed coefficients below are also priors unless validated. The correct process is:

1. Build a historical dataset.
2. Run the current algorithm to create baseline predictions.
3. Run candidate algorithms.
4. Compare against ground truth.
5. Select thresholds and weights that optimize target metrics.
6. Freeze a versioned scoring model.
7. Re-test periodically.

### 8.2 Candidate ground-truth sources

| Source | Use | Notes |
|---|---|---|
| Surf-Forecast historical ratings | Proxy label | Same source currently used in scoring, so avoid using it as the sole ground truth. Useful for weak supervision. |
| Surfline observed ratings / reports | Higher-quality label if accessible | Official docs say observed ratings include full ocean state and forecaster context. Scraping/access terms must be respected. |
| Local surfer logs | Best subjective quality label | Need structured forms: spot, time, skill, quality 0–10, safety, crowd, wave count. |
| Webcam-derived wave counts / conditions | Objective proxy | Requires CV or manual labeling. Good for breaking height / crowd / rideable wave count. |
| IPMA / Instituto Hidrográfico / port tide and buoy data | Physical validation | Useful for Lisbon-area wave/tide ground truth. |
| CDIP / NOAA NDBC | Method development in regions with excellent public data | Not Lisbon-specific but excellent for building validation tooling. |
| Existing `tests/test_live_latest.py` harness | Regression and live sanity checks | Should be extended with historical replay tests. |

### 8.3 Minimum dataset

The plan says at least two weeks of Lisbon data before code changes. That is acceptable for a smoke test, but not enough for stable calibration. Recommended phases:

| Phase | Duration | Purpose |
|---|---:|---|
| Smoke test | 2 weeks | Verify pipeline, compare obvious go/skip days, catch regressions. |
| Initial calibration | 8–12 weeks | Cover multiple tides, swells, wind regimes. |
| Seasonal calibration | 6–12 months | Estimate reliable source weights and thresholds. |

### 8.4 Validation metrics

Use both numeric and decision metrics:

| Metric | What it answers |
|---|---|
| MAE / RMSE vs 0–10 rating | How close is the score? |
| Spearman / Kendall rank correlation | Does the model rank better windows higher? |
| Confusion matrix for go/maybe/skip | Where are decision errors? |
| Precision of GO | How often is “go” actually good? |
| Recall of good windows | How many good sessions did the model miss? |
| Brier score for go probability | Is decision probability calibrated? |
| ROC-AUC / PR-AUC | Are thresholds separable? |
| Reliability diagram | Do scores mean what they claim? |
| Skill-stratified metrics | Does beginner/intermediate/advanced logic work? |
| Regime-stratified metrics | Does it fail in long-period swell, onshore wind, mixed swell, etc.? |

### 8.5 Proposed historical replay experiment

#### Step 1 — Build hourly feature table

For every spot-hour:

```text
spot_id
time_utc
skill_tier
source availability
SF rating/verdict/flags
OM Hs/Tp/Dir/wind/windwave/secondary/tide if present
GFS Hs/Tp/Dir/wind
IBI Hs/Tp/Dir
computed factors: wind components, power, chop ratio, secondary interference, direction diff, tide phase
current_score/current_tier/current_decision
```

#### Step 2 — Attach ground truth

Labels can be hierarchical:

```text
primary_label: observed surfer/forecaster quality 0–10
secondary_label: go/maybe/skip
auxiliary_labels: size observed, shape observed, safety, crowd, wave count
```

#### Step 3 — Run baselines

Candidate models:

1. Current formula exactly.
2. Current formula without final spread/direction/tide penalties.
3. Arithmetic source blend.
4. Geometric source blend.
5. Raw-variable consensus + geometric factor suitability.
6. Dynamic reliability-weighted source blend.
7. Fuzzy-rule prototype.

#### Step 4 — Threshold calibration

Do not choose green/gold by visual preference. Select thresholds based on target operating points:

- Green/GO threshold: choose score where precision of “worth going” is at least target, e.g. 70%.
- Gold threshold: choose score where precision is very high, e.g. 85–90%, and confidence is high.
- Red/SKIP threshold: choose score where probability of poor session is high, e.g. >75%.

#### Step 5 — Report model card

For each candidate:

```text
model_name
feature set
aggregation method
weights
hard gates
metrics overall
metrics by skill tier
metrics by spot
metrics by forecast horizon
known failure modes
recommendation
```

---

## 9. Annotated Bibliography

### 9.1 Surf science and surf quality mechanics

#### [S1] Hutt, J.A.; Black, K.P.; Mead, S.T. (2001). “Classification of Surf Breaks in Relation to Surfing Skill.” *Journal of Coastal Research*, Special Issue 29, 66–81.

- URL: https://ref.coastalrestorationtrust.org.nz/documents/classification-of-surf-breaks-in-relation-to-surfing-skill/
- Summary: Foundational classification connecting surf-break characteristics with surfer skill level. Supports skill-specific condition scoring rather than one universal quality score.
- Variables/weights: Break characteristics, wave type, height, peel/breaking mechanics; no consumer-style weights disclosed in public abstract/database entry.
- Validation metric: Not a forecast-score validation paper; classification/physical analysis.
- Relevance: Strong support for tier-aware scoring.

#### [S2] Mead, S.T.; Black, K.P. (2001). “Functional Component Combinations Controlling Surfing Wave Quality at World-Class Surfing Breaks.” *Journal of Coastal Research*, Special Issue 29, 21–32.

- URL: https://www.jstor.org/stable/25736202
- Summary: Describes how reef and seabed components combine to create world-class surf quality. Emphasizes peel angle, focusing, preconditioning, and local bathymetric function.
- Variables/weights: Functional components, peel angle, seabed/bathymetry; no public 0–10 weights.
- Validation metric: Physical/component classification, not ML validation.
- Relevance: Strong argument for spot metadata and local transformation coefficients.

#### [S3] Mead, S.T.; Black, K.P. (2001). “Predicting the Breaking Intensity of Surfing Waves.” *Journal of Coastal Research*, Special Issue 29, 51–65.

- URL: https://www.researchgate.net/publication/228605528_Predicting_the_breaking_intensity_of_surfing_waves
- Summary: Develops a method for describing plunging-wave breaking intensity using vortex length/width ratio and orthogonal seabed gradient. Notes that tube shape is critical for quality surfing waves and that simplistic Iribarren-only indicators are insufficient.
- Variables/weights: Orthogonal seabed gradient, vortex ratio, breaking intensity, wave height/period as secondary possible improvements.
- Validation metric: Physical fit/relationship; not a public forecast classifier metric.
- Relevance: Current score lacks bathymetry/breaking-intensity representation.

#### [S4] Walker, J.R. (1974). “Recreational Surf Parameters.” University of Hawaii, James K.K. Look Laboratory of Oceanographic Engineering.

- URL: https://catalog.hathitrust.org/Record/007247173
- Summary: Early foundational work on surfability parameters and recreational surfing wave classification. Frequently cited by later surf-science studies.
- Variables/weights: Surfing wave parameters including wave type and rideability; full text not freely accessible through the catalog record.
- Validation metric: Historical/technical report.
- Relevance: Supports using surf-specific parameters, not only generic marine wave variables.

#### [S5] Scarfe, B.E.; Healy, T.R.; Rennie, H.G.; Mead, S.T. (2009). “Research-Based Surfing Literature for Coastal Management and the Science of Surfing—A Review.” *Journal of Coastal Research*.

- DOI/URL: https://doi.org/10.2112/07-0958.1 ; https://bioone.org/journals/journal-of-coastal-research/volume-2009/issue-253/07-0958.1/Research-Based-Surfing-Literature-for-Coastal-Management-and-the-Science/10.2112/07-0958.1.full
- Summary: Reviews surfing literature for coastal management and summarizes parameters describing surfing waves. Reinforces that surf quality is a multi-factor physical/coastal process.
- Variables/weights: Wave height, period, peel, breaking intensity, break type, coastal morphology.
- Validation metric: Literature review.
- Relevance: Supports multi-factor scoring and local coastal context.

#### [S6] Scarfe, B.E.; Healy, T.R.; Rennie, H.G.; Mead, S.T. (2009). “Sustainable Management of Surfing Breaks: Case Studies and Recommendations.” *Journal of Coastal Research*, 25(3), 684–703.

- URL: https://ref.coastalrestorationtrust.org.nz/site/assets/files/7294/4__scarfe_healy_rennie_and_mead.pdf
- Summary: Case studies show how coastal structures and bathymetry affect surf quality. Notes that predictable, clean waves where the breaking point peels along the crest at surfable speed are desired by surfers.
- Variables/weights: Peel speed, consistency, clean wave faces, bathymetry, jetty/break geometry.
- Validation metric: Case-study evidence.
- Relevance: Strong support for local break metadata and against pure offshore-variable scoring.

#### [S7] Pattiaratchi, C. et al. “Surfability of the Perth Metropolitan Coastline.”

- URL: https://joas.free.fr/studies/bei/g2s/surfability.pdf
- Summary: Studies surfability using offshore wind/wave data and refraction/transformation concepts for a regional coastline.
- Variables/weights: Offshore wind/wave conditions, refraction, surfability climate.
- Validation metric: Regional surfability analysis.
- Relevance: Supports deriving local surfability from transformed wave climate rather than raw offshore conditions.

#### [S8] Battjes, J.A. (1974). “Surf Similarity.” *Coastal Engineering Proceedings*.

- URL: https://www.researchgate.net/publication/333735439_SURF_SIMILARITY
- Summary: Formalizes surf similarity / Iribarren-type concepts for breaking waves on slopes. Useful for breaker-type prediction, though later surf-specific work says it does not fully describe tube shape.
- Variables/weights: Slope, wave height, wavelength/period, surf similarity parameter.
- Validation metric: Coastal engineering theory/experiments.
- Relevance: Useful for future bathymetry-aware scoring.

#### [S9] Moragues, M.V. et al. (2021). “Progression of Wave Breaker Types on a Plane Impermeable Slope.” *Journal of Geophysical Research: Oceans*.

- DOI/URL: https://doi.org/10.1029/2021JC017211
- Summary: Modern treatment of breaker-type progression and Iribarren/surf similarity concepts. Relevant for translating physical wave parameters into breaker-type expectations.
- Variables/weights: Wave height, slope, period/wavelength, breaker type.
- Validation metric: Physical/numerical analysis.
- Relevance: Future advanced feature if spot beach slope/bathymetry is known.

### 9.2 Surf forecasting and industry systems

#### [S10] Surf-Forecast.com FAQ. “How does your surf quality star rating work?”

- URL: https://www.surf-forecast.com/pages/faq
- Summary: Publicly states that star rating is based on swell size and character, with bigger/longer-period swell raising ratings and onshore wind reducing rating in proportion to wind speed. Also highlights wave energy, secondary swell interference, and wind-wave chop.
- Variables/weights: Swell size, period/character, wind direction/speed, wave energy, secondary swells, wind waves; no exact coefficients.
- Validation metric: Not disclosed.
- Relevance: Strongly supports wave energy and secondary interference; warns against double-penalizing SF because its rating already includes wind/period/size effects.

#### [S11] Surfline Support. “Surf Ratings & Colors.”

- URL: https://support.surfline.com/hc/en-us/articles/36277684017819-Surf-Ratings-Colors
- Summary: Explains Surfline’s seven ratings and notes that Good/Epic need forecaster application. Says the data-science team uses 35 years and hundreds of thousands of observations to train ML to distinguish poor and good surf.
- Variables/weights: Surf height and wind in model rating; forecaster input for richer observed ratings.
- Validation metric: Internal, not public.
- Relevance: Strong support for observation-trained calibration and high-precision gold windows.

#### [S12] Surfline Support. “Observation Clarity.”

- URL: https://support.surfline.com/hc/en-us/articles/35995874238491-Observation-Clarity
- Summary: Differentiates model ratings from forecaster-observed ratings. Model ratings use wind speed, wind direction, and breaking wave height; forecaster ratings include size, shape, ocean surface, tide, and wind.
- Variables/weights: Breaking wave height, wind speed/direction; observed factors include size/shape/ocean surface/tide/wind.
- Validation metric: Internal.
- Relevance: Supports splitting model potential from full-condition observed scoring.

#### [S13] Surfline. “LOTUS swell model.”

- URL: https://www.surfline.com/lp/whatsnew/features/lotus-swell-model
- Summary: LOTUS blends high-resolution bathymetry mapping, near-shore wave models, ML, forecaster input, camera data, satellite assimilation, and buoy validation. It is validated for thousands of spots.
- Variables/weights: Bathymetry, nearshore wave models, wind-wave evolution, observations, camera data.
- Validation metric: Internal operational validation.
- Relevance: Strong evidence that local bathymetry and observations matter.

#### [S14] Freeston, B. (2018). “Machine Learning for Surf Forecasting.” Surfline Labs / Medium.

- URL: https://medium.com/surfline-labs/machine-learning-for-surf-forecasting-4a007f13b3e3
- Summary: Describes surf forecasting as pattern recognition built from careful observation and model data. Emphasizes that correlations/causations are complex and that decades of observations are key.
- Variables/weights: Not a formula; methodology discussion.
- Validation metric: Not public.
- Relevance: Supports data-driven calibration over hand-tuned weights.

#### [S15] Stormglass. “Waves, Swell, Wind Waves API.”

- URL: https://stormglass.io/waves-swell-wind-waves-api/
- Summary: Documents data partitions including wave height/direction, swell height/direction, secondary swell, and wind-wave height/direction. Shows what a modern surf/marine data schema exposes.
- Variables/weights: Primary wave, swell, secondary swell, wind wave, wind/tide via other endpoints.
- Validation metric: Not a scoring method.
- Relevance: Supports explicit partition-based shape/interference modeling.

#### [S16] Spitcast API docs. “Surf Forecast.”

- URL: https://github.com/jackmullis/spitcast-api-docs
- Summary: Public docs show forecast includes wave height and shape quality, with shape values from poor to good.
- Variables/weights: Wave height, shape quality.
- Validation metric: Not disclosed.
- Relevance: Industry pattern: height and shape are separable factors.

#### [S17] Boqué Ciurana, A. et al. (2021). “Which Meteorological and Climatological Information Is Requested for Better Surfing Experiences? A Survey-Based Analysis.” *Atmosphere*, 12(3), 293.

- DOI/URL: https://doi.org/10.3390/atmos12030293 ; https://www.mdpi.com/2073-4433/12/3/293
- Summary: Reviews surfer-facing resources and finds they mainly forecast wave height, wave period, wind speed, wind direction, and primary/secondary swell differentiation. Tables document MagicSeaweed, Surfline, Windy, Windguru, Surf-Forecast, and others.
- Variables/weights: Height, period, direction, wind, tides, primary/secondary swell, quality rating.
- Validation metric: Survey/resource analysis, not scoring validation.
- Relevance: Confirms current input set is broadly aligned with industry practice.

### 9.3 Wave forecast blending, verification, and ML

#### [S18] Raftery, A.E.; Gneiting, T.; Balabdaoui, F.; Polakowski, M. (2005). “Using Bayesian Model Averaging to Calibrate Forecast Ensembles.” *Monthly Weather Review*, 133, 1155–1174.

- DOI/URL: https://doi.org/10.1175/MWR2906.1 ; https://journals.ametsoc.org/view/journals/mwre/133/5/mwr2906.1.xml
- Summary: Establishes BMA as a statistical method for post-processing forecast ensembles using performance-based weights and predictive distributions.
- Variables/weights: General forecast members; weights learned from recent training data.
- Validation metric: Forecast calibration/sharpness metrics in meteorological examples.
- Relevance: Better source-blending doctrine than fixed weights/harmonic mean.

#### [S19] Roulston, M.S.; Ellepola, J.; von Hardenberg, J.; Smith, L.A. (2005). “Forecasting Wave Height Probabilities with Numerical Weather Prediction Models.” *Ocean Engineering*, 32, 1841–1863.

- DOI/URL: https://doi.org/10.1016/j.oceaneng.2004.11.012 ; https://www.lse.ac.uk/CATS/Assets/PDFs/Publications/Papers/2005/70-ForecastingWaveHeight-2005.pdf
- Summary: Demonstrates post-processing ECMWF ensemble wave-height forecasts for improved reliability and expected-error prediction. Shows probabilistic ensemble treatment for significant wave height.
- Variables/weights: Significant wave height ensemble members; post-processing.
- Validation metric: Reliability and expected error against offshore locations.
- Relevance: Supports probabilistic confidence and spread-skill use.

#### [S20] WMO. “Guide to Wave Analysis and Forecasting” (WMO-No. 702).

- URL: https://www.jodc.go.jp/info/ioc_doc/JCOMM_Other/WMO702.pdf
- Summary: Operational wave-model guide describing verification using ME, RMSE, scatter index, and correlation for wind speed, wave height, and peak period. Emphasizes ongoing verification with buoy and satellite data.
- Variables/weights: Wave height, peak period, wind, direction/spectra where available.
- Validation metric: ME, RMSE, SI, correlation.
- Relevance: Source weights should be based on verification metrics.

#### [S21] Copernicus Marine Service. “Global Ocean Waves Analysis and Forecast.”

- URL: https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_WAV_001_027/description
- Summary: Describes Météo-France MFWAM global wave system, third-generation wave model, including significant height, period, direction, Stokes drift, wind-wave and primary/secondary swell partitions.
- Variables/weights: Total spectrum plus wind-wave/primary/secondary partitions.
- Validation metric: Product quality docs available separately.
- Relevance: Supports using IBI/MFWAM partitions directly rather than only total score.

#### [S22] Björkqvist, J.V. et al. (2020). “WAM, SWAN and WAVEWATCH III in the Finnish archipelago.” *Journal of Operational Oceanography*.

- DOI/URL: https://doi.org/10.1080/1755876X.2019.1633236
- Summary: Compares WAM, SWAN, and WAVEWATCH III implementations against coastal buoy observations. Shows that model skill varies by coastal setting.
- Variables/weights: Wave height, period, model outputs vs buoys.
- Validation metric: Buoy comparison metrics.
- Relevance: Supports regime/region-dependent source weights.

#### [S23] James, S.C.; Zhang, Y.; O’Donncha, F. (2018). “A Machine Learning Framework to Forecast Wave Conditions.” *Coastal Engineering*, 137, 1–10.

- DOI/URL: https://doi.org/10.1016/j.coastaleng.2018.03.004 ; https://cdip.ucsd.edu/themes/media/docs/publications_references/journal_articles/A_Machine_Learning_Framework_to_Forecast_Wave_Conditions.pdf
- Summary: ML surrogate model replicates SWAN wave-height fields with 9 cm RMSE and correctly identifies over 90% of characteristic periods in test data. Shows ML can emulate wave models efficiently but is location-specific and needs retraining.
- Variables/weights: Hs, characteristic period, winds, currents, boundary conditions.
- Validation metric: 9 cm RMSE for Hs, >90% characteristic-period classification.
- Relevance: Supports future ML/transformation model, but not immediate consumer score.

#### [S24] Adnan, R.M. et al. (2023). “Short-term probabilistic prediction of significant wave height using Bayesian model averaging.” *Ocean Engineering*.

- URL: https://www.sciencedirect.com/science/article/abs/pii/S0029801823002718
- Summary: Applies BMA ensemble methods to short-term significant-wave-height prediction.
- Variables/weights: Significant wave height, model ensemble components.
- Validation metric: Forecast accuracy/probabilistic metrics in the paper.
- Relevance: Additional direct support for BMA-like wave blending.

### 9.4 Decision science, fuzzy logic, and validation data

#### [S25] “Fuzzy-based Wave Height Forecast for Surfing.”

- URL: https://www.researchgate.net/publication/277993830_Fuzzy-based_Wave_Height_Forecast_for_Surfing
- Summary: Proposes a fuzzy expert-knowledge system for surfing wave-height forecasts using previous wave height and wind variables. Reported 86% forecast accuracy over two years at Kizakihama, Miyazaki.
- Variables/weights: Wave height, wind velocity previous day/night, expert fuzzy rules.
- Validation metric: 86% forecast accuracy.
- Relevance: Supports nonlinear expert-rule/fuzzy scoring as a credible alternative to linear weights.

#### [S26] Özger, M. (2007). “Prediction of Wave Parameters by Using Fuzzy Logic Approach.” *Ocean Engineering*.

- DOI/URL: https://doi.org/10.1016/j.oceaneng.2006.07.003
- Summary: Uses fuzzy logic to predict wave parameters from wind and previous/current wave characteristics. Demonstrates nonlinear mapping for wave prediction.
- Variables/weights: Wind speed, previous/current wave characteristics.
- Validation metric: Forecast error metrics in paper.
- Relevance: Supports fuzzy/nonlinear feature transformation.

#### [S27] Martin, D.M.; Mazzotta, M. (2018). “Non-monetary valuation using Multi-Criteria Decision Analysis: Sensitivity of additive aggregation methods to scaling and compensation assumptions.” *Ecosystem Services*, 29, 13–22.

- DOI/URL: https://doi.org/10.1016/j.ecoser.2017.10.022 ; https://www.sciencedirect.com/science/article/pii/S2212041617303315
- Summary: Shows MCDA additive aggregation results are sensitive to scaling and compensation assumptions. Warns analysts to be careful when converting multiple criteria into one index.
- Variables/weights: Generic MCDA.
- Validation metric: Sensitivity/case-study analysis.
- Relevance: Direct warning for the current weighted-sum-plus-penalty design.

#### [S28] Munda, G. (2005). “Non-Compensatory Composite Indicators for Ranking Countries.” Joint Research Centre / European Commission.

- URL: https://publications.jrc.ec.europa.eu/repository/bitstream/JRC32435/EUR%2021833%20EN.pdf
- Summary: Explains limitations of linear aggregation and develops non-compensatory aggregation concepts for composite indicators. Notes that composite indicators can be misleading if weighting/aggregation choices are not theoretically sound.
- Variables/weights: Generic composite indicators.
- Validation metric: Theoretical/illustrative.
- Relevance: Supports geometric/non-compensatory surf scoring and sensitivity testing.

#### [S29] CDIP. “Data Access — CDIP Documentation.”

- URL: https://cdip.ucsd.edu/m/documents/data_access.html
- Summary: Documents programmatic access to observed and modeled wave data via THREDDS, netCDF, Python API, archive/realtime/model files. Useful for validating wave forecast algorithms in data-rich regions.
- Variables/weights: Wave spectra, wave parameters, modeled data, validation points.
- Validation metric: Dataset/source, not a scoring method.
- Relevance: Excellent model-validation infrastructure and template for Lisbon workflow.

#### [S30] NOAA NDBC. “Observation Data Descriptions” and “Wave Measurements.”

- URLs: https://www.ndbc.noaa.gov/obsdes.shtml ; https://www.ndbc.noaa.gov/waveobs.shtml
- Summary: Defines significant wave height, dominant/average period, and mean wave direction. Provides standard observational wave variables for validation.
- Variables/weights: WVHT, DPD, APD, MWD, wind fields.
- Validation metric: Dataset/source.
- Relevance: Ground-truth model-development reference outside Lisbon.

#### [S31] Instituto Hidrográfico / MONICAN buoy data.

- URL: https://monican.hidrografico.pt/boias.nazare
- Summary: Portuguese directional buoy network information. Directional buoys provide wave direction and sea-surface temperature in addition to wave measurements.
- Variables/weights: Wave height, direction, surface temperature, buoy metadata.
- Validation metric: Dataset/source.
- Relevance: Lisbon/Portugal-adjacent data source family for validation.

#### [S32] Porto de Lisboa / Instituto Hidrográfico tide tables.

- URL: https://www.portodelisboa.pt/en/tides
- Summary: Provides downloadable tidal tables for Lisbon/Portugal ports, with time-zone clarification. Useful for tide-state ground truth.
- Variables/weights: High/low tide times and heights.
- Validation metric: Dataset/source.
- Relevance: Tide validation for Lisbon-area scoring.

---

## 10. Comparison Table of Scoring / Forecasting Systems

| Source/system | Inputs | Functional form | Weights | Tier cutoffs | Validation / evidence |
|---|---|---|---|---|---|
| Current Surf Decider | SF score, OM/GFS/IBI height/period/purity/direction/wind, tide, source flags | Source scores blended by weighted harmonic mean, then subtract penalties, then hard gates | SF/OM/GFS/IBI = 40/30/20/10; model subweights = 30/25/20/15/10 | 5.0 / 6.2 / 7.5 | Hand-tuned; no empirical validation yet. |
| Surf-Forecast star rating | Swell size, period/character, wind direction/speed, wave energy, secondary swells, wind waves | Proprietary 1–10 rating; public description says onshore wind drops rating in proportion to speed | Not disclosed | 1–10 stars | Public methodology notes; no public validation metric. |
| Surfline LOTUS model rating | Breaking wave height, wind speed, wind direction | ML/model rating, spot-calibrated; simplified model rating does not include tide/wave shape | Not disclosed | 1–5 bars plus labels | Internal: 35 years and hundreds of thousands of observations; no public metric. |
| Surfline forecaster-observed rating | Size, shape, ocean surface, tide, wind, human observation | Human forecaster override / observed rating | Human expert judgment | Very Poor to Epic | Treated by Surfline as gold standard where available. |
| MagicSeaweed historical forecast | WAVEWATCH III/PROTEUS, surf height, wind/gust/direction, tide, primary/secondary swell | Proprietary quality rating | Not public | Star/quality rating | Public algorithm no longer accessible; variables documented in survey literature. |
| Spitcast | Wave height, shape quality | Proprietary forecast plus explicit shape score | Not public | Shape: 0 poor, 0.5 poor-fair, 1 fair, >1 good | No public validation. |
| Fuzzy-based Wave Height Forecast for Surfing | Prior wave height, wind variables, expert rules | Fuzzy inference | Expert fuzzy rules | Surfable wave-height classes | Reported 86% forecast accuracy over two years. |
| Hutt/Black/Mead skill classification | Break type, height, peel/breaking characteristics, skill level | Classification framework | Not consumer weights | Skill classes | Peer-reviewed classification, not forecast score. |
| BMA/EMOS wave forecast blending | Multiple model forecasts, recent observations | Statistical post-processing / probabilistic ensemble | Learned from recent performance | Probabilistic thresholds | Standard meteorological validation: calibration, reliability, error. |
| WMO operational wave verification | Model wave/wind variables vs buoys/satellite | Statistical verification | Not a score | N/A | ME, RMSE, scatter index, correlation. |
| Proposed V2 doctrine | Blended raw physical variables, spot metadata, skill tier, suitability factors, confidence | Hard gates + smooth membership functions + weighted geometric/fuzzy aggregation + separate confidence | Learned from validation; priors below | Derived by ROC/precision/quantiles | To be validated on Lisbon historical data. |

---

## 11. Specific Recommendations for the Codebase

### 11.1 Recommendation for `_hour_score()`

#### Replace height formula

Current:

```python
height_score = min(wave_h / 3.0 * 10, 10)
```

Recommended:

```python
height_score = 10 * height_suitability(wave_h, skill_tier, spot_profile)
```

where `height_suitability` is trapezoidal/bell-shaped and can penalize too-small and too-large surf.

#### Replace period formula

Current:

```text
<8s => 2
8–11s => 5
11–15s => 8
>15s => 10
```

Recommended:

```python
period_score = 10 * period_suitability(period, skill_tier, spot_profile, wave_h)
```

Principle:

- <8 s: poor/mushy/wind-sea unless specific spot exception.
- 8–10.5 s: acceptable for learners/beach breaks.
- 10.5–14 s: generally good.
- 14–17 s: powerful; good for many advanced conditions, risk-adjust for lower tiers.
- >17 s: spot/skill dependent; do not universally score 10.

#### Add wave power / energy

Add:

```python
power_index = wave_h ** 2 * period
power_score = 10 * power_suitability(power_index, skill_tier, spot_profile)
```

Then either:

- include power as its own factor, or
- let power replace part of the height+period weighting.

#### Rework wind and purity into shape

Current purity and wind are separate:

```text
Purity 20%, Wind 10%
```

Recommended:

```python
shape_score = combine(
    wind_direction_speed_suitability,
    windsea_ratio_suitability,
    secondary_interference_suitability,
    spot_shelter_adjustment,
)
```

If the five-factor structure must remain short-term, adjust from:

```text
Height 30 / Period 25 / Purity 20 / Direction 15 / Wind 10
```

to a more defensible interim prior:

```text
Height/skill suitability 30
Period/power suitability 20
Purity/chop 20
Swell direction/exposure 10
Wind direction-speed 20
```

This keeps the same number of fields but gives wind equal importance to period and purity.

#### Add secondary swell interference

If code can add a sixth factor, use this prior:

```text
Height/skill suitability     0.28
Period/power suitability     0.18
Wind direction-speed         0.20
Windsea/chop purity          0.14
Swell direction/exposure     0.10
Secondary interference       0.10
```

This is a research-based prior, not a final calibrated weight vector.

### 11.2 Recommendation for source blending in `unified_explainer.py`

#### Replace harmonic mean as default

Preferred near-term replacement:

```python
score = 10 * weighted_geometric_mean([source_score_i / 10], weights)
```

Alternative conservative replacement:

```python
score = weighted_arithmetic_mean(source_scores, weights)
```

with source disagreement shown as confidence.

Do **not** subtract a full independent spread penalty unless validation proves it improves decisions.

#### Move spread to confidence

Recommended:

```python
quality_score = blended_score
confidence = confidence_from(
    source_count,
    source_score_spread,
    raw_variable_spread,
    missing_critical_fields,
    recent_source_skill,
)
```

Then display:

```text
GO NOW — 6.8 / 10, confidence medium
Reason: good height/period, light offshore wind; lower confidence because GFS is 0.5 m smaller than OM.
```

### 11.3 Recommendation for base source weights

Current base weights are not indefensible as a prior, but they should not be permanent.

Interim prior options:

#### Option A — keep current priors but change interpretation

```text
SF  0.40
OM  0.30
GFS 0.20
IBI 0.10
```

Use these only until validation. Do not add duplicate penalties for factors already embedded in SF.

#### Option B — slightly more model-balanced prior

```text
SF  0.30
OM  0.30
GFS 0.20
IBI 0.20
```

Use if IBI is locally validated for Lisbon/Portugal nearshore conditions.

#### Option C — performance-based dynamic weights, preferred

```python
prior = {SF: .30, OM: .30, GFS: .20, IBI: .20}
error_i = rolling_error(source_i, spot, horizon, variable_or_score)
weight_i = prior_i * exp(-lambda * error_i)
normalize(weights)
```

Weights should differ by forecast horizon. A source can be good at 0–24 h and worse at 72 h.

### 11.4 Recommendation for penalties

| Current mechanism | Recommendation |
|---|---|
| Spread penalty | Move to confidence; keep only a small calibrated uncertainty haircut if validated. |
| Direction penalty | Remove from post-consensus score; include in per-source/factor direction suitability. |
| Tide penalty | Remove from post-consensus score; include as tide suitability/gate. |
| Multiple red-direction additions | Avoid summing red labels across sources. Use consensus direction suitability and confidence. |
| SF/OM/GFS/IBI verdict skip | Keep only if verdict means independently severe condition; otherwise treat as low factor score. |

### 11.5 Recommendation for hard gates

Hard gates should be fewer and more explicit.

#### Keep as hard gates

- No ridable wave height for any tier.
- Extreme/dangerous height or power for selected tier.
- Spot-specific tide shutdown / dry reef / known non-working state.
- Severe onshore wind with meaningful speed and wind-sea/chop ratio.
- Missing critical data so severe that scoring is not credible.

#### Convert from hard gate to smooth penalty

- Mild period red.
- Mild height red.
- Light onshore wind.
- Direction marginal rather than completely outside exposure window.
- Shape yellow/marginal.
- Tide yellow/marginal.

#### Revise onshore instant block

Current concept:

```text
wind ≥ 5 km/h and bearing diff >150° from offshore => instant shape block
```

Recommended:

```text
hard_shape_block if:
  onshore_component >= 12–15 km/h
  AND windsea_ratio >= 0.45–0.55
  AND spot_shelter does not block that wind-wave direction
```

Light onshore wind should reduce the shape score, not force skip.

### 11.6 Recommendation for thresholds

Do not permanently use 5.0 / 6.2 / 7.5 without validation.

Recommended threshold-calibration method:

```text
RED/SKIP threshold:
  max recall for truly bad/sunsafe conditions, while allowing some maybes.

GREEN/GO threshold:
  choose score where historical GO precision ≥ target, e.g. 70%.

GOLD threshold:
  choose score where historical excellent-session precision ≥ target, e.g. 85–90%,
  and confidence is high.
```

Gold should require both:

```text
score >= gold_threshold
confidence >= high_confidence_threshold
no major factor below local minimum
```

---

## 12. Proposed Scoring Architecture V2

### 12.1 Physical consensus stage

Instead of blending source scores first, estimate physical variables:

```text
H_breaking
T_peak_or_energy
swell_direction
wind_speed
wind_direction
windsea_ratio
secondary_ratio
secondary_cross_angle
tide_phase_or_height
```

Each source contributes to variables it knows. Bias-correct and skill-weight by source.

### 12.2 Suitability stage

Convert physical variables into 0–1 suitability factors:

```text
F_height     = height_suitability(H_breaking, skill, spot)
F_power      = power_suitability(H_breaking^2 * T, skill, spot)
F_period     = period_suitability(T, skill, spot)
F_wind       = wind_suitability(wind_speed, wind_direction, spot)
F_chop       = chop_suitability(windsea_ratio, spot)
F_swell_dir  = swell_direction_suitability(direction, spot)
F_secondary  = secondary_suitability(secondary_ratio, cross_angle, period_gap)
F_tide       = tide_suitability(tide_height_or_phase, spot)
```

### 12.3 Aggregation stage

Short-term recommended aggregation:

```text
quality_0_1 = geometric_mean_weighted({
  F_height:    0.24,
  F_power:     0.14,
  F_period:    0.12,
  F_wind:      0.18,
  F_chop:      0.12,
  F_swell_dir: 0.08,
  F_secondary: 0.06,
  F_tide:      0.06,
})

score = 10 * quality_0_1
```

These weights are starting priors only. They intentionally reduce the need for extra penalties.

### 12.4 Confidence stage

```text
confidence = weighted combination of:
  source_count
  historical source skill
  raw variable spread
  source score spread
  critical missing fields
  forecast horizon
```

Display confidence separately:

```text
score = 6.8
confidence = 0.62
headline = GO / LOW CONFIDENCE
```

### 12.5 Hard gate stage

Apply gates before or after suitability, but they should be explicit and auditable:

```text
if no_surf_height: SKIP
if skill_danger_power: SKIP or SAFETY WARNING
if severe_onshore_blown_out: SKIP
if spot_tide_shutdown: SKIP
if critical_data_missing: UNKNOWN rather than false SKIP
```

### 12.6 Tier stage

```text
if hard_gate: RED / SKIP
elif score >= gold_threshold and confidence high: GOLD / GO NOW
elif score >= green_threshold: GREEN / GO
elif score >= yellow_threshold: YELLOW / MAYBE
else: RED / SKIP
```

Thresholds are learned from validation.

---

## 13. Direct Answers to Research Questions

### Q1. Which inputs most strongly predict surfer-rated session quality?

Best-evidence answer:

1. Breaking/surf height relative to skill and spot.
2. Wind direction/speed and resulting cleanliness.
3. Wave power/period, especially height squared times period.
4. Swell direction relative to exposure and local bathymetry.
5. Wind-sea/chop and secondary swell interference.
6. Tide relative to local working window.
7. Bathymetry/break type/peel mechanics.
8. Forecast confidence/source skill.

### Q2. Do successful systems use weighted sums, products, fuzzy logic, decision trees, or ML?

Public evidence shows a mix:

- Industry systems use proprietary ML/human corrections and local calibration.
- Academic surf science uses physical classification and surfability parameters.
- Fuzzy logic has been used successfully for surf-related wave-height forecasting.
- Operational wave systems use numerical models plus statistical post-processing.

No strong evidence supports a universal hand-tuned linear weighted sum plus repeated penalties.

### Q3. For multi-source blending, what is preferred?

Operational forecast literature supports calibrated ensemble post-processing: BMA, EMOS, MOS, reliability weighting, and spread-skill modeling. The harmonic mean of final quality scores is not a standard method.

Preferred: blend raw physical variables using validation-based source weights, then score.

### Q4. Are subtractive penalties standard?

Not as a stacked architecture. Most robust decision systems either:

- encode factors directly into suitability scores,
- use fuzzy rules,
- use non-compensatory aggregation,
- or use hard gates for true veto conditions.

Subtractive penalties are acceptable only if each penalty represents a distinct, independent phenomenon and is calibrated.

### Q5. How should thresholds be anchored?

By validation against historical labels:

- ROC/PR curves,
- precision targets for GO/GOLD,
- quantiles of observed quality,
- calibration/reliability diagrams,
- skill-tier and spot-specific evaluation.

Fixed thresholds are acceptable only as initial priors.

### Q6. Is skill-tier customization studied?

Yes in principle. Hutt/Black/Mead classification relates surfing break characteristics to surfer skill. Industry tools increasingly personalize interpretation, and Surfline notes model ratings are comparative within spot context. Tier-specific scoring is justified.

### Q7. How should scoring formulas be verified?

Use a historical replay dataset with physical observations and quality labels. Evaluate numeric score error, rank correlation, decision confusion matrix, precision/recall, Brier score, calibration, and regime-specific failure modes.

---

## 14. Concrete Implementation Roadmap After Review

### Phase 1 — Low-risk formula cleanup

1. Move spread penalty to confidence.
2. Remove duplicate direction/tide penalties or reduce them to near-zero behind feature flags.
3. Replace harmonic mean with geometric mean behind a feature flag.
4. Increase wind importance in `_hour_score` interim weights.
5. Raise onshore hard-gate threshold and make it speed/chop dependent.

### Phase 2 — Suitability functions

1. Implement skill-specific height suitability.
2. Implement period/power suitability.
3. Implement wind vector suitability.
4. Implement secondary swell interference.
5. Implement tide suitability as local multiplier/gate.

### Phase 3 — Validation harness

1. Create historical replay loader.
2. Store source raw variables and generated scores.
3. Add label ingestion.
4. Compare current vs candidate scores.
5. Auto-generate model card and metrics.

### Phase 4 — Dynamic source weights

1. Estimate source error by variable, spot, horizon.
2. Build dynamic reliability weighting.
3. Retrain thresholds.
4. Add confidence output.

### Phase 5 — Optional ML/fuzzy layer

1. Start with interpretable fuzzy rules.
2. Compare against geometric suitability model.
3. If enough labels exist, train gradient boosting / calibrated ordinal classifier.
4. Keep explainability by reporting factor contributions.

---

## 15. Verification Checklist Against Original Plan

| Requirement | Covered? | Where |
|---|---:|---|
| Annotated bibliography 15–25+ entries | Yes | Section 9 includes 32 entries. |
| Formula comparison table | Yes | Section 10. |
| Predictor-importance ranking | Yes | Section 6. |
| Harmonic mean recommendation | Yes | Sections 4, 11.2. |
| Base weights assessment | Yes | Section 11.3. |
| Penalties folded into per-factor scoring? | Yes | Sections 7, 11.4. |
| `_hour_score` sub-weight recommendations | Yes | Section 11.1. |
| Hard-gate recommendations | Yes | Section 11.5. |
| Threshold anchoring | Yes | Sections 8.4, 11.6. |
| Skill-tier handling | Yes | Sections 3.2, 6.3, 13. |
| Validation experiment with Lisbon data | Yes | Section 8. |
| Famous websites / industry systems | Yes | Section 5. |
| Government/wave-model docs | Yes | Sections 4, 8, 9.3–9.4. |
| No code changes in this phase | Yes | This is research doctrine only. |

---

## 16. Final Doctrine Summary

The next Surf Decider should become a **calibrated, spot-aware, skill-aware suitability model** rather than a weighted average of source scores plus penalties.

The most defensible near-term changes are:

1. **Stop double-counting penalties**: remove direction/tide/spread score penalties as defaults.
2. **Use source disagreement as confidence**.
3. **Replace harmonic mean with weighted geometric mean** or calibrated arithmetic mean.
4. **Make height and period nonlinear and skill-specific**.
5. **Add wave power** (`H² × T`) and secondary-swell interference.
6. **Increase wind/shape importance** and model wind as speed × direction × shelter.
7. **Reserve hard gates for true no-surf/safety/local-shutdown conditions**.
8. **Learn source weights and tier thresholds from historical validation**, not intuition.

The biggest conceptual shift: the system should answer two separate questions.

```text
1. If the forecast verifies, how good is the session likely to be?
2. How confident are we that the forecast will verify?
```

The current formula mixes those questions into one score. Separating them will make the decider more accurate, more explainable, and easier to tune.

---

## 17. Source URLs Collected During Research

- Hutt/Black/Mead skill classification: https://ref.coastalrestorationtrust.org.nz/documents/classification-of-surf-breaks-in-relation-to-surfing-skill/
- Mead/Black functional components: https://www.jstor.org/stable/25736202
- Scarfe review DOI: https://doi.org/10.2112/07-0958.1
- Sustainable management of surfing breaks PDF: https://ref.coastalrestorationtrust.org.nz/site/assets/files/7294/4__scarfe_healy_rennie_and_mead.pdf
- Mead/Black breaking intensity: https://www.researchgate.net/publication/228605528_Predicting_the_breaking_intensity_of_surfing_waves
- Walker recreational surf parameters: https://catalog.hathitrust.org/Record/007247173
- Surf-Forecast FAQ: https://www.surf-forecast.com/pages/faq
- Surfline ratings: https://support.surfline.com/hc/en-us/articles/36277684017819-Surf-Ratings-Colors
- Surfline observation clarity: https://support.surfline.com/hc/en-us/articles/35995874238491-Observation-Clarity
- Surfline LOTUS: https://www.surfline.com/lp/whatsnew/features/lotus-swell-model
- Surfline ML: https://medium.com/surfline-labs/machine-learning-for-surf-forecasting-4a007f13b3e3
- Stormglass waves API: https://stormglass.io/waves-swell-wind-waves-api/
- Spitcast API docs: https://github.com/jackmullis/spitcast-api-docs
- Boqué Ciurana et al. 2021: https://www.mdpi.com/2073-4433/12/3/293
- Raftery et al. BMA: https://doi.org/10.1175/MWR2906.1
- Roulston et al. wave probabilities: https://doi.org/10.1016/j.oceaneng.2004.11.012
- WMO Guide to Wave Analysis and Forecasting: https://www.jodc.go.jp/info/ioc_doc/JCOMM_Other/WMO702.pdf
- Copernicus MFWAM product: https://data.marine.copernicus.eu/product/GLOBAL_ANALYSISFORECAST_WAV_001_027/description
- James et al. ML wave conditions: https://doi.org/10.1016/j.coastaleng.2018.03.004
- Fuzzy-based surfing forecast: https://www.researchgate.net/publication/277993830_Fuzzy-based_Wave_Height_Forecast_for_Surfing
- Özger fuzzy wave parameters: https://doi.org/10.1016/j.oceaneng.2006.07.003
- Martin & Mazzotta MCDA: https://doi.org/10.1016/j.ecoser.2017.10.022
- Munda non-compensatory indicators: https://publications.jrc.ec.europa.eu/repository/bitstream/JRC32435/EUR%2021833%20EN.pdf
- CDIP docs: https://cdip.ucsd.edu/documentation
- CDIP data access: https://cdip.ucsd.edu/m/documents/data_access.html
- NOAA NDBC observation descriptions: https://www.ndbc.noaa.gov/obsdes.shtml
- NOAA NDBC wave observations: https://www.ndbc.noaa.gov/waveobs.shtml
- Instituto Hidrográfico MONICAN buoys: https://monican.hidrografico.pt/boias.nazare
- Porto de Lisboa tide tables: https://www.portodelisboa.pt/en/tides

