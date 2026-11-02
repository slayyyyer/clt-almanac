"""Two small linear learners, in numpy.

Ridge regression for temperatures and rain amounts, L2 logistic regression for
the chance of rain. Deliberately simple: fifteen features, a few thousand rows,
and a model that can be retrained from scratch in a fraction of a second so the
backtest can honestly retrain every single day.
"""

from __future__ import annotations

import numpy as np


def _sigmoid(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(value, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


class Scaler:
    def __init__(self) -> None:
        self.mean: np.ndarray | None = None
        self.scale: np.ndarray | None = None

    def fit(self, features: np.ndarray) -> "Scaler":
        self.mean = features.mean(axis=0)
        spread = features.std(axis=0)
        self.scale = np.where(spread < 1e-9, 1.0, spread)
        return self

    def transform(self, features: np.ndarray) -> np.ndarray:
        assert self.mean is not None and self.scale is not None
        return (features - self.mean) / self.scale


class Ridge:
    def __init__(self, alpha: float = 2.0) -> None:
        self.alpha = alpha
        self.scaler = Scaler()
        self.coef: np.ndarray | None = None
        self.intercept: float = 0.0

    def fit(self, features: np.ndarray, target: np.ndarray) -> "Ridge":
        scaled = self.scaler.fit(features).transform(features)
        self.intercept = float(target.mean())
        gram = scaled.T @ scaled + self.alpha * np.eye(scaled.shape[1])
        self.coef = np.linalg.solve(gram, scaled.T @ (target - self.intercept))
        return self

    def predict(self, features: np.ndarray) -> np.ndarray:
        assert self.coef is not None
        return self.scaler.transform(features) @ self.coef + self.intercept


class Logistic:
    def __init__(self, alpha: float = 1.0, iterations: int = 40) -> None:
        self.alpha = alpha
        self.iterations = iterations
        self.scaler = Scaler()
        self.coef: np.ndarray | None = None
        self.intercept: float = 0.0

    def fit(self, features: np.ndarray, target: np.ndarray) -> "Logistic":
        scaled = self.scaler.fit(features).transform(features)
        design = np.column_stack([np.ones(len(scaled)), scaled])
        penalty = np.full(design.shape[1], self.alpha)
        penalty[0] = 0.0
        weights = np.zeros(design.shape[1])
        weights[0] = float(np.log(max(target.mean(), 1e-4) / max(1 - target.mean(), 1e-4)))

        for _ in range(self.iterations):
            probabilities = _sigmoid(design @ weights)
            variance = np.clip(probabilities * (1 - probabilities), 1e-6, None)
            gradient = design.T @ (probabilities - target) + penalty * weights
            hessian = (design * variance[:, None]).T @ design + np.diag(penalty)
            step = np.linalg.solve(hessian + 1e-9 * np.eye(len(weights)), gradient)
            weights -= step
            if float(np.max(np.abs(step))) < 1e-9:
                break

        self.intercept = float(weights[0])
        self.coef = weights[1:]
        return self

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        assert self.coef is not None
        return _sigmoid(self.scaler.transform(features) @ self.coef + self.intercept)
