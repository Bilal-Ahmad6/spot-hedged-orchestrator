"""Cost ledger: the authoritative money counter.

Billing runs from launch to termination (not from readiness), which is how cloud
providers charge and is the convention stated in the report. Idle and draining
capacity is billed on purpose: that is what makes a cost comparison honest.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from spothedge.model.types import InstanceType, Pool, PriceTable
from spothedge.simulate.nodes import SimNode


@dataclass
class CostLedger:
    prices: PriceTable
    catalogue: Mapping[str, InstanceType]
    total_usd: float = 0.0
    by_pool: dict[Pool, float] = field(default_factory=lambda: dict.fromkeys(Pool, 0.0))
    node_seconds: float = 0.0

    def accrue(self, nodes: Iterable[SimNode], t: float, dt: float) -> None:
        for node in nodes:
            seconds = node.billing_seconds(t, t + dt)
            if seconds <= 0:
                continue
            rate = self.prices.usd_per_hour(node.pool, self.catalogue[node.instance_type])
            amount = rate * seconds / 3600.0
            self.total_usd += amount
            self.by_pool[node.pool] += amount
            self.node_seconds += seconds

    def node_hours(self) -> float:
        return self.node_seconds / 3600.0
