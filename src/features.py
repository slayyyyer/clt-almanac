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
    "upstream_overnight",
    "upstream_vs_charlotte",
    "upstream_change",
)

# Appended only when a day-ahead forecast series is supplied, so the model can be
# built with or without the NWP block from the same function.
NWP_FEATURES = (
    "nwp_tmax",
    "nwp_tmin",
    "nwp_vs_lag1",
    "nwp_trend",
)

TREND_DAYS = 3
WINDOW_DAYS = 14


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _season(target: dt.date) -> tuple[float, float, float, float]:
    day_of_year = target.timetuple().tm_yday
    angle = 2.0 * math.pi * day_of_year / 365.25
    return math.sin(angle), math.cos(angle), math.sin(2 * angle), math.cos(2 * angle)


def _nwp_features(target: dt.date, nwp: dict | None, target_normal: float,
                  target_normal_low: float, lag1_high: float) -> list[float]:
    """The forecast high and how it departs from persistence.

    Empty when no forecast series is supplied. When the target has no forecast,
    the block falls back to the normal and two zeros, which is neutral for a
    model trained on real values rather than an invitation to extrapolate.
    """
    if nwp is None:
        return []
    forecast = nwp.get(target) or {}
    high = forecast.get("tmax")
    if high is None:
        return [target_normal, target_normal_low, 0.0, 0.0]
    low = forecast.get("tmin")
    previous = (nwp.get(target - dt.timedelta(days=1)) or {}).get("tmax")
    return [
        high,
        target_normal_low if low is None else low,
        high - lag1_high,
        0.0 if previous is None else high - previous,
    ]


def vector(observations: dict, target: dt.date, normals: dict,
           upstream: dict | None = None, nwp: dict | None = None) -> list[float] | None:
    """Feature vector for `target`, or None when history is too thin.

    `upstream` is the regional overnight temperature keyed by date: the only
    input here that is not a Charlotte measurement, and the only one that says
    where the air is going instead of where it has been.
    """
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
    target_normal_low = normal_for(normals, "tmin", target) or target_normal

    tmax = [past[lag]["tmax"] for lag in range(1, WINDOW_DAYS + 1)]
    tmin = [past[lag].get("tmin") for lag in range(1, TREND_DAYS + 1)]
    anomalies = [tmax[lag - 1] - normals_used[lag - 1] for lag in range(1, 8)]
    season = _season(target)
    precip_week = sum(past[lag].get("precip") or 0.0 for lag in range(1, 8))

    regional = upstream or {}
    air_now = regional.get(target)
    air_previous = regional.get(target - dt.timedelta(days=1))
    if air_now is None:
        # No upstream report: assume the air has not moved.
        air_now = past[1]["tmax"]
    if air_previous is None:
        air_previous = air_now

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
        air_now,
        air_now - past[1]["tmax"],
        air_now - air_previous,
    ] + _nwp_features(target, nwp, target_normal, target_normal_low, past[1]["tmax"])
