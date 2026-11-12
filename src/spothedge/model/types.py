"""Pure data contracts shared by the simulator, the policy and the controller.

Nothing here performs I/O or knows about Kubernetes. Keeping these types pure is
what allows the same policy code to run in all four testbeds (SimPy, KWOK, kind,
optional live cloud).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Pool(StrEnum):
    """Logical capacity pools from the proposal's architecture figure."""

    ON_DEMAND = "on-demand"
    SPOT_A = "spot-a"
    SPOT_B = "spot-b"

    @property
    def is_spot(self) -> bool:
        return self is not Pool.ON_DEMAND


ALL_POOLS: tuple[Pool, ...] = (Pool.ON_DEMAND, Pool.SPOT_A, Pool.SPOT_B)
SPOT_POOLS: tuple[Pool, ...] = (Pool.SPOT_A, Pool.SPOT_B)


@dataclass(frozen=True, slots=True)
class InstanceType:
    """A purchasable node shape.

    ``allocatable_vcpu`` subtracts kubelet/system reserve, because scheduling
    against the raw vCPU count is the classic way a simulation becomes
    optimistically wrong by 5-15%.
    """

    name: str
    vcpu: int
    system_overhead_vcpu: float = 0.3
    memory_gib: float = 0.0

    def __post_init__(self) -> None:
        if self.vcpu <= 0:
            raise ValueError(f"instance {self.name!r} must have positive vcpu")
        if not 0 <= self.system_overhead_vcpu < self.vcpu:
            raise ValueError(
                f"instance {self.name!r}: overhead {self.system_overhead_vcpu} "
                f"must be in [0, {self.vcpu})"
            )

    @property
    def allocatable_vcpu(self) -> float:
        return self.vcpu - self.system_overhead_vcpu


@dataclass(frozen=True, slots=True)
class PriceTable:
    """Prices in USD per vCPU-hour, with per-node overrides when needed."""

    on_demand_usd_per_vcpu_hour: float
    spot_discount: float
    overrides: Mapping[tuple[Pool, str], float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.on_demand_usd_per_vcpu_hour <= 0:
            raise ValueError("on-demand price must be positive")
        if not 0 <= self.spot_discount < 1:
            raise ValueError("spot discount must be in [0, 1)")

    def usd_per_vcpu_hour(self, pool: Pool) -> float:
        if pool is Pool.ON_DEMAND:
            return self.on_demand_usd_per_vcpu_hour
        return self.on_demand_usd_per_vcpu_hour * (1.0 - self.spot_discount)

    def usd_per_hour(self, pool: Pool, instance: InstanceType) -> float:
        override = self.overrides.get((pool, instance.name))
        if override is not None:
            return override
        return instance.vcpu * self.usd_per_vcpu_hour(pool)

    def blended_usd_per_vcpu_hour(self) -> float:
        """Average price across the three pools, useful for quick sanity checks."""
        return sum(self.usd_per_vcpu_hour(p) for p in ALL_POOLS) / len(ALL_POOLS)


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    at_seconds: int
    vcpu: float
    vcpu_p90: float

    def __post_init__(self) -> None:
        if self.at_seconds < 0:
            raise ValueError("forecast horizon must be non-negative")
        if self.vcpu < 0 or self.vcpu_p90 < 0:
            raise ValueError("demand cannot be negative")
        if self.vcpu_p90 < self.vcpu:
            raise ValueError("p90 must be >= point forecast")


@dataclass(frozen=True, slots=True)
class Forecast:
    points: tuple[ForecastPoint, ...]
    mape: float | None = None
    degraded: bool = False

    def at(self, seconds: int) -> ForecastPoint:
        """Nearest available point at or after ``seconds``."""
        if not self.points:
            raise ValueError("empty forecast")
        for point in self.points:
            if point.at_seconds >= seconds:
                return point
        return self.points[-1]

    def max_p90(self, within_seconds: int) -> float:
        candidates = [p.vcpu_p90 for p in self.points if p.at_seconds <= within_seconds]
        return max(candidates) if candidates else self.points[0].vcpu_p90


@dataclass(frozen=True, slots=True)
class Plan:
    """Desired capacity, expressed as node counts per (pool, instance type)."""

    nodes: Mapping[tuple[Pool, str], int]
    predicted_cost_per_hour: float
    predicted_p95_ms: float | None = None
    predicted_availability: float | None = None
    solver_status: str = "OPTIMAL"
    relaxed: tuple[str, ...] = ()

    def node_count(self, pool: Pool | None = None) -> int:
        if pool is None:
            return sum(self.nodes.values())
        return sum(n for (p, _), n in self.nodes.items() if p is pool)

    def capacity_vcpu(self, catalogue: Mapping[str, InstanceType]) -> float:
        total = 0.0
        for (_, name), count in self.nodes.items():
            total += catalogue[name].allocatable_vcpu * count
        return total

    def capacity_vcpu_by_pool(self, catalogue: Mapping[str, InstanceType]) -> dict[Pool, float]:
        totals = dict.fromkeys(ALL_POOLS, 0.0)
        for (pool, name), count in self.nodes.items():
            totals[pool] += catalogue[name].allocatable_vcpu * count
        return totals


@dataclass(frozen=True, slots=True)
class Interruption:
    """A reclaim signal for one node."""

    node: str
    pool: Pool
    notice_seconds: int
    source: str = "simulated"

    def __post_init__(self) -> None:
        if self.notice_seconds < 0:
            raise ValueError("notice window cannot be negative")


@dataclass(frozen=True, slots=True)
class ClusterState:
    """What the actuator currently owns."""

    nodes: Mapping[tuple[Pool, str], int]
    ready_at_seconds: Mapping[tuple[Pool, str], int] = field(default_factory=dict)
    draining: Sequence[str] = ()


@dataclass(slots=True)
class DecisionRecord:
    """One auditable tick. Serialised to JSONL by the controller and simulator."""

    schema_version: str
    decision_id: str
    tick: int
    inputs: dict[str, Any]
    constraints: dict[str, Any]
    plan: dict[str, Any]
    reason: str
    solver: dict[str, Any]
    action: dict[str, Any] = field(default_factory=dict)
    experiment_id: str | None = None

    @staticmethod
    def new_id(now: datetime | None = None) -> str:
        now = now or datetime.now(UTC)
        return now.strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict[str, Any]:
        """Serialise with the camelCase keys documented in docs/02-architecture.md."""

        return {
            "schemaVersion": self.schema_version,
            "decisionId": self.decision_id,
            "experimentId": self.experiment_id,
            "tick": self.tick,
            "inputs": self.inputs,
            "constraints": self.constraints,
            "plan": self.plan,
            "reason": self.reason,
            "solver": self.solver,
            "action": self.action,
        }


SCHEMA_VERSION = "1.0"
