"""Policy interface shared by the simulator and the controller."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from spothedge.config import Config
from spothedge.model.types import Forecast, InstanceType, Plan, Pool, PriceTable


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """Everything a policy is allowed to see at a tick."""

    now_seconds: float
    demand_vcpu: float
    forecast: Forecast | None
    capacity_by_pool: Mapping[Pool, float]
    node_counts: Mapping[tuple[Pool, str], int]
    config: Config
    catalogue: Mapping[str, InstanceType]
    prices: PriceTable
    reclaim_deficit_vcpu: float = 0.0

    @property
    def capacity_vcpu(self) -> float:
        return sum(self.capacity_by_pool.values())

    def peak_forecast_vcpu(self, horizon_seconds: int) -> float:
        if self.forecast is None:
            return self.demand_vcpu
        return max(self.demand_vcpu, self.forecast.max_p90(horizon_seconds))


class Policy(Protocol):
    name: str

    def decide(self, ctx: DecisionContext) -> Plan: ...
