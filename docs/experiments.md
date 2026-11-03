# Experiments

Every change that can move a published number gets an entry here, scored on the
baseline window in `docs/baseline_metrics.md` — 365 walk-forward days,
2025-11-02 to 2026-11-01 — using the same code paths as the live run.

## 2026-11-03 — Repair the live feature path (no model change)

The model was never the problem. The backtest built its feature vectors with the
upwind data and scored 4.88 / 3.34 / 0.170, while the live call built the same
vector without it and would have shipped 6.27 / 10.29 / 0.316. This change closes
that gap instead of adding a feature.

| what changed | before | after |
|---|---|---|
| `predict_live()` vector | `upstream=None`, all three upwind features degenerate | real regional values |
| Mesonet request | end date exclusive, so every span lost its last day | asks one day past, then filters |
| cache coverage | advanced over days that produced no report | derived from the values that arrived |
| same-day rerun | overwrote the logged forecast | first write wins, `logged_at` recorded |
| gap fill | averaged both neighbours | previous day only |
| backcast | logged and scored as a prediction | not logged |

Backtest, unchanged window and folds: high **4.88**, low **3.34**, rain Brier
**0.170** — identical to baseline, as it should be, because the scored rows already
used the honest path.

Live output for 2026-11-02: 67°F / 50°F, 34% rain, with `upstream_overnight` at
56.5°F against yesterday's 58.1°F regional reading (−1.5°F).

The existing 2026-11-02 line in `data/predictions.jsonl` stays as it was issued
under `ridge-logistic-v1`. A forecast log that drops its own calls when the model
changes is not a log, and the `model` field is there precisely so a change of
version does not rewrite history.

Runtime: 5.8 s end to end on this machine against 5.0 s at baseline — one extra day
requested per station, plus run-to-run noise.

Tests: `python -m unittest discover -s tests -t .`

## 2026-11-03 — Phase 1: day-ahead forecast features

Source: Open-Meteo Previous Runs API, model `ecmwf_ifs025`, variable
`temperature_2m_previous_day1` (hourly, aggregated to the local-day max and min).
The archive begins 2024-06-01, so the dataset is restricted to that era and both
arms are scored on identical rows and folds.

| config | features | high MAE | low MAE | Brier |
|---|---|---|---|---|
| A control, NWP-era rows only | 22 | 4.95 | 3.31 | 0.171 |
| B with the forecast block | 26 | **2.17** | **1.98** | **0.158** |
| S negative control, same series shuffled | 26 | 4.92 | 3.32 | 0.173 |

Full-history baseline for context: 4.88 / 3.34 / 0.170.

Raw ECMWF day-1 error across the same 365 days: high MAE **3.00** with a
**−1.84°F** bias; low MAE **2.17** with +0.36. The ridge is not merely copying
the forecast — it corrects a systematic cold bias, which is why 2.17 beats the
raw 3.00.

The shuffled control is the integrity check: permute the forecast series across
days and the entire gain disappears (4.92 / 3.32 / 0.173). The features are also
strictly backward-looking — deleting every forecast dated after the target leaves
the vector unchanged — and `build_dataset` refuses rows without a real forecast,
so no imputed value ever reaches training.

Dataset: 870 rows (2024-06-15 onward), 365 scored days.
Runtime: 2.5 s end to end, down from 5.8 s — fewer training rows cost more than
four extra features.

## 2026-11-03 — Phase 3: regularization is not the bottleneck

Swept the ridge, logistic and amount alphas over {0.3, 1, 3, 10, 30} on the
26-feature dataset, with a split-half check (first 182 days vs last 182).

| alpha | high | low | Brier | head high/low | tail high/low |
|---|---|---|---|---|---|
| 0.3 | 2.18 | 1.97 | 0.161 | 2.42 / 2.32 | 1.94 / 1.63 |
| 1.0 | 2.17 | 1.99 | 0.158 | 2.40 / 2.34 | 1.94 / 1.64 |
| 3.0 | 2.16 | 2.02 | 0.155 | 2.39 / 2.41 | 1.93 / 1.64 |
| 10 | 2.15 | 2.15 | 0.152 | 2.38 / 2.63 | 1.91 / 1.68 |
| 30 | 2.13 | 2.38 | 0.152 | 2.41 / 2.98 | 1.86 / 1.79 |

Nothing here is worth keeping. More shrinkage buys 0.04°F on the high and 0.006
Brier while costing 0.39°F on the low, and the two halves disagree about which
direction is better. **Alpha stays at 1.0.** The model is not variance-limited;
the next gain has to come from information, not shrinkage.

## 2026-11-03 — defect 6, sized rather than fixed

The train/serve source mismatch is far smaller than the baseline audit assumed.
In the current build exactly **2 of 884 rows** (2026-10-31 and 2026-11-01) carry
a label from the Open-Meteo fill instead of the station, because GHCN has caught
up with everything older. On the 12 days both sources cover, GHCN reads +1.38°F
warmer on the high (max 2.12°F).

Two labels, one direction. It belongs in the limits list, not in a refactor of
the merge logic. Left open and now sized.
