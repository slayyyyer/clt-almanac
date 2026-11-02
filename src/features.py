"""Turn a run of daily observations into one feature vector.

Every feature for a target day uses only data from *before* that day, which is
what makes the walk-forward backtest honest: the live prediction and the
backtest are built by the same function.
"""

from __future__ import annotations

import datetime as dt
import math

from .weather import normal_for

FEATURES = (
    "tmax_lag1",
    "tmin_lag1",
    "precip_lag1",
    "tmax_lag2",
    "tmax_lag3",
    "tmax_mean7",
    "tmax_mean14",
    "tmin_mean3",
    "tmax_anomaly_lag1",
    "tmax_anomaly_mean3",
    "tmax_anomaly_mean7",
    "tmax_trend3",
    "diurnal_range_lag1",
    "precip_sum7",
    "normal_tmax_target",
    "season_sin",
    "season_cos",
    "season_sin2",
    "season_cos2",
)

TREND_DAYS = 3
WINDOW_DAYS = 14


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _season(target: dt.date) -> tuple[float, float, float, float]:
    day_of_year = target.timetuple().tm_yday
    angle = 2.0 * math.pi * day_of_year / 365.25
    return math.sin(angle), math.cos(angle), math.sin(2 * angle), math.cos(2 * angle)


def vector(observations: dict, target: dt.date, normals: dict) -> list[float] | None:
    """Feature vector for `target`, or None when history is too thin."""
    past: dict[int, dict] = {}
    for lag in range(1, WINDOW_DAYS + 1):
        day = target - dt.timedelta(days=lag)
        row = observations.get(day)
        if row is None or row.get("tmax") is None:
            return None
        past[lag] = row

    for lag in range(1, TREND_DAYS + 1):
        if past[lag].get("tmin") is None:
            return None

    normals_used: list[float] = []
    for lag in range(1, 8):
        value = normal_for(normals, "tmax", target - dt.timedelta(days=lag))
        if value is None:
            return None
        normals_used.append(value)

    target_normal = normal_for(normals, "tmax", target)
    if target_normal is None:
        return None

    tmax = [past[lag]["tmax"] for lag in range(1, WINDOW_DAYS + 1)]
    tmin = [past[lag].get("tmin") for lag in range(1, TREND_DAYS + 1)]
    anomalies = [tmax[lag - 1] - normals_used[lag - 1] for lag in range(1, 8)]
    season = _season(target)
    precip_week = sum(past[lag].get("precip") or 0.0 for lag in range(1, 8))

    return [
        past[1]["tmax"],
        past[1]["tmin"],
        past[1].get("precip") or 0.0,
        past[2]["tmax"],
        past[3]["tmax"],
        _mean(tmax[:7]),
        _mean(tmax[7:14]),
        _mean([value for value in tmin if value is not None]),
        anomalies[0],
        _mean(anomalies[:3]),
        _mean(anomalies),
        past[1]["tmax"] - past[3]["tmax"],
        past[1]["tmax"] - past[1]["tmin"],
        precip_week,
        target_normal,
        season[0],
        season[1],
        season[2],
        season[3],
    ]
