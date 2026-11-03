"""Phase 1 experiment: does a day-ahead forecast high beat lagged observations?

Two models are scored on identical rows and identical folds, so the only
difference is the three NWP features:

    A  22 features, observations restricted to the NWP era
    B  25 features, same rows, plus the day-ahead forecast

A is the control. Comparing B against the full-history baseline would confound
the new features with the loss of ten years of training rows.

Run from the project root:  python scripts/experiment_nwp.py
"""

from __future__ import annotations

import datetime as dt
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import learn, nwp, upstream, weather  # noqa: E402

DATA = ROOT / "data"
HISTORY_START = dt.date(2005, 1, 1)
HORIZON = 365


def show(label: str, result: dict) -> None:
    print(f"{label}")
    print(f"  rows {result['days']}  {result['from']} .. {result['to']}")
    print(f"  high {result['high']['model']:>5}  (persistence {result['high']['persistence']}, "
          f"normal {result['high']['climatology']}, bias {result['high']['bias']})")
    print(f"  low  {result['low']['model']:>5}  (persistence {result['low']['persistence']}, "
          f"normal {result['low']['climatology']}, bias {result['low']['bias']})")
    print(f"  rain Brier {result['rain']['brier']}  (climatology "
          f"{result['rain']['brier_climatology']}, hit {result['rain']['accuracy']})")


def main() -> int:
    normals = weather.load_normals(DATA / "normals.json")
    observations, _, _ = weather.fetch_observations(HISTORY_START)
    air = upstream.ensure(DATA / "upstream.json", HISTORY_START, weather.local_today())
    forecast = nwp.ensure(DATA / "nwp.json", dt.date(2024, 6, 1), weather.local_today())

    era = min(forecast)
    recent = {day: row for day, row in observations.items() if day >= era}
    print(f"NWP era starts {era}; {len(forecast)} forecast days cached; "
          f"{len(recent)} observation days in the era\n")

    rows_a = learn.build_dataset(recent, normals, air)
    rows_b = learn.build_dataset(recent, normals, air, forecast)
    print(f"features: A={len(rows_a[0]['x'])}  B={len(rows_b[0]['x'])}")
    print(f"rows:     A={len(rows_a)}  B={len(rows_b)}\n")

    full = learn.build_dataset(observations, normals, air)
    show("full-history baseline (22 features, 2005+)", learn.backtest(full, HORIZON))
    print()
    show("A  control (22 features, NWP era only)", learn.backtest(rows_a, HORIZON))
    print()
    show("B  with day-ahead forecast", learn.backtest(rows_b, HORIZON))
    print()

    window = [row["date"] for row in rows_a[-HORIZON:]]
    covered = [day for day in window if day in forecast]
    print(f"target days with a day-1 forecast: {len(covered)}/{len(window)}")
    for label, field, key in (("high", "tmax", "tmax"), ("low", "tmin", "tmin")):
        errors = [forecast[day][field] - recent[day][key] for day in covered]
        raw = sum(abs(error) for error in errors) / len(errors)
        bias = sum(errors) / len(errors)
        print(f"raw NWP {label} MAE {raw:.2f}  bias {bias:+.2f}")
    print()

    order = sorted(forecast)
    values = [forecast[day] for day in order]
    random.Random(0).shuffle(values)
    shuffled = dict(zip(order, values))
    rows_s = learn.build_dataset(recent, normals, air, shuffled)
    show("S  negative control: same series, shuffled across days",
         learn.backtest(rows_s, HORIZON))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
