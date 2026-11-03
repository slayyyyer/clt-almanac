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
