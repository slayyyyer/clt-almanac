# Baseline metrics

Recorded before any Phase 1+ change, at commit `be164e6` on branch `main`.
Command: `python -m src.main --no-narrative` (plus `learn.backtest(rows, 365)` directly).

Every later experiment is compared against these numbers on **this exact window**.

## Evaluation
- 365 walk-forward days: **2025-11-02 to 2026-11-01**
- retrained for every day using at most `MAX_TRAIN_ROWS=3650` prior rows
- 7961 labelled rows, 22 features
- ridge alpha 1.0, logistic alpha 1.0, wet threshold 0.01 in

## Temperature — mean absolute error, °F (lower is better)

| method | high MAE | low MAE |
|---|---|---|
| This model (ridge) | **4.88** | **3.34** |
| Yesterday repeats | 5.57 | 4.65 |
| Normal for the date (1991–2020) | 7.40 | 6.67 |

Bias (predicted − observed): high -0.35°F, low -0.10°F.

## Rain

| metric | value |
|---|---|
| Brier score | **0.170** |
| Brier, climatology base rate | 0.184 |
| Brier skill score | **+0.076** |
| Base rate (days with ≥0.01 in) | 0.244 |
| Hit rate at 50% | 0.759 |

## Runtime (this machine, warm cache)
| stage | seconds |
|---|---|
| fetch + normals + upstream | 1.68 |
| dataset build | 0.19 |
| 365-day walk-forward backtest | 2.29 |
| total pipeline, end to end | ~5.0 (measured with `time`) |

GitHub-hosted runners are slower; the workflow allows 15 minutes and the step has
always finished well inside it.

## Known defects at this baseline — verified by experiment

1. **The live forecast does not use the upstream features.** `learn.predict_live()`
   (line 155) calls `vector(observations, target, normals)` without the `upstream`
   argument, so `upstream_overnight` is imputed as yesterday's high,
   `upstream_vs_charlotte` and `upstream_change` are exactly 0 — while the model is
   trained on real values. Measured on the same folds with the same training data:

   | inference features | high MAE | low MAE | Brier |
   |---|---|---|---|
   | real upwind values | 4.88 | 3.34 | 0.170 |
   | imputed (what ships) | **6.27** | **10.29** | **0.316** |

   Mean prediction shift 5.02°F (max 21.19°F), more than 1°F on 333 of 365 days, and a
   +4.52°F warm bias on the high. The published forecast would be worse than the
   19-feature model it replaced (5.26 / 4.13 / 0.174) and worse than climatology on the
   low — while the page's skill table still reports 4.88 / 3.34.

2. **The upwind cache drops the last day of every fetch span.** The Mesonet treats the
   end date as **exclusive**: requesting 2026-10-29..2026-11-02 returns 10-29 through
   11-01. `ensure()` nevertheless records coverage through 11-02, so that day is never
   requested again. The cache claims coverage to 2026-11-02 and holds values only to
   2026-11-01, even though a single-day request for 11-02 returns 57.3°F. Because the
   live run needs the *target* day, this alone makes the live feature always missing —
   so fixing defect 1 without fixing this changes nothing.

3. **Same-day reruns overwrite the logged forecast** (`entries[target] = ...`). Three
   writes for one date leave one line carrying the last value; the first is lost.

4. **`_interpolate_gaps()` fills a missing day from both neighbours.** A gap at D−1 is
   filled as the mean of D−2 and D, importing D into a feature for D. Currently latent:
   0 of 7,975 observation days in this build came from interpolation.

5. **Backcasts are logged and scored as predictions** when the station record lags, so
   `target` can land in the past and still enter the live scoreboard.

6. **Train/serve source mismatch.** On the 12 days where both sources cover, GHCN and
   Open-Meteo differ by 1.38°F on the high and 1.14°F on the low. Recent training rows
   use analysis values; scoring uses station values.

## What the vetting cleared

- `features.vector()` is strictly backward-looking. Deleting every observation dated on
  or after the target day leaves all 22 features bit-identical on seven sampled targets
  spanning 364 days and today.
- The walk-forward loop trains only on indices strictly below the day it scores, so the
  backtest rows themselves are clean; the 4.88 / 3.34 above are real for the model they
  describe.
