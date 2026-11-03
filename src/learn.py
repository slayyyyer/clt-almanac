"""Dataset assembly, walk-forward scoring, and the live prediction."""

from __future__ import annotations

import datetime as dt

import numpy as np

from .features import FEATURES, vector
from .models import Logistic, Ridge
from .weather import normal_for

WET_THRESHOLD_IN = 0.01
MAX_TRAIN_ROWS = 3650
TEMPERATURE_ALPHA = 1.0
RAIN_ALPHA = 1.0
AMOUNT_ALPHA = 1.0
BACKTEST_DAYS = 365


def build_dataset(observations: dict, normals: dict,
                  upstream: dict | None = None) -> list[dict]:
    rows: list[dict] = []
    for target in sorted(observations):
        label = observations[target]
        if label.get("tmax") is None or label.get("tmin") is None:
            continue
        features = vector(observations, target, normals, upstream)
        if features is None:
            continue
        rows.append({
            "date": target,
            "x": features,
            "tmax": float(label["tmax"]),
            "tmin": float(label["tmin"]),
            "precip": float(label.get("precip") or 0.0),
            "normal_tmax": normal_for(normals, "tmax", target),
            "normal_tmin": normal_for(normals, "tmin", target),
        })
    return [row for row in rows if row["normal_tmax"] is not None]


def _arrays(rows: list[dict]) -> dict[str, np.ndarray]:
    return {
        "x": np.asarray([row["x"] for row in rows], dtype=float),
        "tmax": np.asarray([row["tmax"] for row in rows], dtype=float),
        "tmin": np.asarray([row["tmin"] for row in rows], dtype=float),
        "wet": np.asarray([row["precip"] >= WET_THRESHOLD_IN for row in rows], dtype=float),
        "amount": np.asarray([row["precip"] for row in rows], dtype=float),
        "normal_tmax": np.asarray([row["normal_tmax"] for row in rows], dtype=float),
        "normal_tmin": np.asarray([row["normal_tmin"] for row in rows], dtype=float),
    }


def _fit_models(features: np.ndarray, data: dict, indices: np.ndarray) -> dict:
    wet_mask = data["wet"][indices] > 0
    amount_model = None
    if int(wet_mask.sum()) >= 40:
        wet_indices = indices[wet_mask]
        amount_model = Ridge(AMOUNT_ALPHA).fit(
            data["x"][wet_indices], np.log1p(data["amount"][wet_indices])
        )
    return {
        "tmax": Ridge(TEMPERATURE_ALPHA).fit(features, data["tmax"][indices]),
        "tmin": Ridge(TEMPERATURE_ALPHA).fit(features, data["tmin"][indices]),
        "wet": Logistic(RAIN_ALPHA).fit(features, data["wet"][indices]),
        "amount": amount_model,
    }


def _predict(models: dict, features: np.ndarray) -> tuple[float, float, float, float]:
    tmax = float(models["tmax"].predict(features)[0])
    tmin = float(models["tmin"].predict(features)[0])
    pop = float(np.clip(models["wet"].predict_proba(features)[0], 0.0, 1.0))
    if models["amount"] is not None:
        rainy_amount = float(np.expm1(models["amount"].predict(features)[0]))
    else:
        rainy_amount = 0.1
    expected = float(np.clip(pop * max(rainy_amount, 0.0), 0.0, 3.0))
    if tmax < tmin:
        tmax, tmin = tmin, tmax
    return tmax, tmin, pop, expected


def backtest(rows: list[dict], horizon: int = BACKTEST_DAYS) -> dict:
    """Retrain every day on data available at the time, then score the result."""
    data = _arrays(rows)
    count = len(rows)
    start = max(90, count - horizon)

    predicted_tmax = np.full(count, np.nan)
    predicted_tmin = np.full(count, np.nan)
    predicted_pop = np.full(count, np.nan)

    for index in range(start, count):
        low = max(0, index - MAX_TRAIN_ROWS)
        training = np.arange(low, index)
        models = _fit_models(data["x"][training], data, training)
        tmax, tmin, pop, _ = _predict(models, data["x"][index:index + 1])
        predicted_tmax[index] = tmax
        predicted_tmin[index] = tmin
        predicted_pop[index] = pop

    evaluated = ~np.isnan(predicted_tmax)
    persistence_tmax = _persistence(rows, "tmax", data["normal_tmax"])
    persistence_tmin = _persistence(rows, "tmin", data["normal_tmin"])

    rain_evaluated = ~np.isnan(predicted_pop)
    actual_wet = data["wet"][rain_evaluated].astype(bool)
    probability = predicted_pop[rain_evaluated]
    base_rate = float(np.mean(data["wet"][rain_evaluated]))

    return {
        "days": int(evaluated.sum()),
        "from": rows[start]["date"].isoformat() if start < count else None,
        "to": rows[-1]["date"].isoformat() if count else None,
        "high": {
            "model": round(float(np.mean(np.abs(predicted_tmax[evaluated] - data["tmax"][evaluated]))), 2),
            "persistence": round(float(np.mean(np.abs(persistence_tmax[evaluated] - data["tmax"][evaluated]))), 2),
            "climatology": round(float(np.mean(np.abs(data["normal_tmax"][evaluated] - data["tmax"][evaluated]))), 2),
            "bias": round(float(np.mean(predicted_tmax[evaluated] - data["tmax"][evaluated])), 2),
        },
        "low": {
            "model": round(float(np.mean(np.abs(predicted_tmin[evaluated] - data["tmin"][evaluated]))), 2),
            "persistence": round(float(np.mean(np.abs(persistence_tmin[evaluated] - data["tmin"][evaluated]))), 2),
            "climatology": round(float(np.mean(np.abs(data["normal_tmin"][evaluated] - data["tmin"][evaluated]))), 2),
            "bias": round(float(np.mean(predicted_tmin[evaluated] - data["tmin"][evaluated])), 2),
        },
        "rain": {
            "brier": round(float(np.mean((probability - actual_wet) ** 2)), 3),
            "brier_climatology": round(float(np.mean((base_rate - actual_wet) ** 2)), 3),
            "base_rate": round(base_rate, 3),
            "accuracy": round(float(np.mean((probability >= 0.5) == actual_wet)), 3),
        },
    }


def _persistence(rows: list[dict], key: str, fallback: np.ndarray) -> np.ndarray:
    """Yesterday's value, repeated. A strong and honest one-day baseline."""
    by_date = {row["date"]: row[key] for row in rows}
    values = np.array(fallback, dtype=float)
    for index, row in enumerate(rows):
        previous = by_date.get(row["date"] - dt.timedelta(days=1))
        if previous is not None:
            values[index] = previous
    return values


def predict_live(rows: list[dict], observations: dict, target: dt.date, normals: dict,
                 upstream: dict | None = None) -> dict:
    data = _arrays(rows)
    indices = np.arange(max(0, len(rows) - MAX_TRAIN_ROWS), len(rows))
    models = _fit_models(data["x"][indices], data, indices)

    features = vector(observations, target, normals, upstream)
    if features is None:
        raise RuntimeError("not enough recent observations to build a feature vector")

    matrix = np.asarray([features], dtype=float)
    tmax, tmin, pop, expected = _predict(models, matrix)

    yesterday = target - dt.timedelta(days=1)
    past_week = [
        observations[target - dt.timedelta(days=lag)]["tmax"]
        for lag in range(1, 8)
        if target - dt.timedelta(days=lag) in observations
    ]
    past_two_weeks = [
        observations[target - dt.timedelta(days=lag)]["precip"] or 0.0
        for lag in range(1, 15)
        if target - dt.timedelta(days=lag) in observations
    ]

    return {
        "target": target,
        "tmax": round(tmax, 1),
        "tmin": round(tmin, 1),
        "pop": round(pop, 3),
        "precip_in": round(expected, 2),
        "normal_tmax": normal_for(normals, "tmax", target),
        "normal_tmin": normal_for(normals, "tmin", target),
        "yesterday": observations.get(yesterday),
        "week_mean_high": round(float(np.mean(past_week)), 1) if past_week else None,
        "recent_rain_in": round(float(sum(past_two_weeks)), 2) if past_two_weeks else None,
        "features": dict(zip(FEATURES, [round(value, 2) for value in features])),
    }
