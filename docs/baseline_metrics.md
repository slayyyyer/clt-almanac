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

## Known defects at this baseline

1. **The live forecast does not use the upstream features.** `learn.predict_live()`
   calls `vector(observations, target, normals)` without the `upstream` argument, so
   `upstream_overnight` is imputed as yesterday's high, `upstream_vs_charlotte` and
   `upstream_change` are exactly 0, while the model was trained on real values. Backtest
   numbers above are unaffected (they go through `build_dataset`, which does pass it);
   the published forecast is.
2. **Same-day reruns overwrite the logged forecast** (`entries[target] = ...`), so a
   late-day rerun can quietly replace a morning call.
3. **`_interpolate_gaps()` fills a missing day from both neighbours**, so a feature for
   day D can inherit an interpolated value for D−1 that was computed using D itself.
4. **Backcasts are logged and scored as predictions** when the station record lags and
   `target` lands in the past.
