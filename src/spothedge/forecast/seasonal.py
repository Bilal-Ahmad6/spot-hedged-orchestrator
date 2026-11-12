"""Seasonal-naive forecasting with EWMA correction.

Why this and not ARIMA/Prophet: the policy needs a defensible, auditable point
forecast with a quantile, recomputed every 60 s, with no training step and no
hidden state. Seasonal naive is hard to beat on strongly periodic load and is
trivial to explain in the decision log.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from spothedge.model.types import Forecast, ForecastPoint

MINUTES_PER_DAY = 1440
Z90 = 1.2815515655446004


class HistoryView:
    """Read-only view of demand up to ``now``; future access raises.

    Passing the raw array to a policy would let it cheat by looking ahead. This
    wrapper makes the no-lookahead rule executable rather than a convention.
    """

    __slots__ = ("_values", "_limit")

    def __init__(self, values: Sequence[float], limit: int) -> None:
        self._values = values
        self._limit = max(0, limit)

    def __len__(self) -> int:
        return self._limit

    def __getitem__(self, index):
        if isinstance(index, slice):
            raise TypeError("slice access is not supported; index a single minute")
        if index < 0:
            index += self._limit
        if index < 0 or index >= self._limit:
            raise IndexError(f"demand at minute {index} is not in the past")
        return self._values[index]

    def last(self, count: int) -> list[float]:
        start = max(0, self._limit - count)
        return list(self._values[start : self._limit])


@dataclass
class SeasonalNaiveForecaster:
    horizon_seconds: int = 1800
    step_seconds: int = 60
    alpha: float = 0.2
    z: float = Z90
    name: str = "seasonal-naive-ewma"
    _correction: float = 0.0
    _variance: float = 0.0
    _initialised: bool = False
    _residuals: list[float] = field(default_factory=list)

    def update(self, history: HistoryView) -> None:
        """Fold the newest observation into the residual model."""
        now = len(history) - 1
        if now < 0:
            return
        if now < MINUTES_PER_DAY:
            self._initialised = True
            return
        actual = history[now]
        baseline = history[now - MINUTES_PER_DAY]
        residual = actual - baseline
        if not self._initialised:
            self._correction = residual
            self._variance = residual**2
            self._initialised = True
            return
        self._correction = self.alpha * residual + (1 - self.alpha) * self._correction
        deviation = residual - self._correction
        self._variance = self.alpha * deviation**2 + (1 - self.alpha) * self._variance

    def _point(self, history: HistoryView, offset_minutes: int) -> float:
        now = len(history) - 1
        source = now + offset_minutes - MINUTES_PER_DAY
        if source < 0:
            return max(0.0, history[now])
        return max(0.0, history[source] + self._correction)

    def forecast(self, history: HistoryView) -> Forecast:
        sigma = math.sqrt(max(self._variance, 0.0))
        points: list[ForecastPoint] = []
        steps = max(1, self.horizon_seconds // self.step_seconds)
        for step in range(steps + 1):
            seconds = step * self.step_seconds
            minutes_ahead = max(0, round(seconds / 60))
            point = self._point(history, minutes_ahead)
            # Uncertainty grows with the square root of the horizon.
            horizon_sigma = sigma * math.sqrt(max(1.0, minutes_ahead / 60.0))
            points.append(
                ForecastPoint(
                    at_seconds=seconds,
                    vcpu=point,
                    vcpu_p90=point + self.z * horizon_sigma,
                )
            )
        return Forecast(points=tuple(points), degraded=len(history) < MINUTES_PER_DAY)


__all__ = ["HistoryView", "SeasonalNaiveForecaster"]
