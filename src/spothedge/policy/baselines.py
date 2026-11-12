"""Baseline policies from the pre-registered comparison.

P0 static peak, P1 on-demand HPA + cluster autoscaler, P2 fixed spot ratio.
The hedged policy (P3) lives in ``hedged.py`` and is added in milestone M2.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from spothedge.model.types import ALL_POOLS, Plan, Pool
from spothedge.policy.base import DecisionContext


def pick_instance(catalogue, preferred_vcpu: int = 8):
    """Closest instance size to ``preferred_vcpu``, deterministic on ties."""

    return min(catalogue.values(), key=lambda i: (abs(i.vcpu - preferred_vcpu), i.vcpu, i.name))


def nodes_for(capacity_vcpu: float, instance) -> int:
    if capacity_vcpu <= 0:
        return 0
    return math.ceil(capacity_vcpu / instance.allocatable_vcpu)


def _plan(nodes: dict[tuple[Pool, str], int], ctx: DecisionContext) -> Plan:
    cost = sum(
        ctx.prices.usd_per_hour(pool, ctx.catalogue[name]) * count
        for (pool, name), count in nodes.items()
    )
    return Plan(nodes={k: v for k, v in nodes.items() if v > 0}, predicted_cost_per_hour=cost)


@dataclass
class StaticPeak:
    """P0: provision the daily peak on-demand, permanently."""

    peak_vcpu: float = 160.0
    name: str = "P0-static-peak"

    def decide(self, ctx: DecisionContext) -> Plan:
        instance = max(ctx.catalogue.values(), key=lambda i: (i.vcpu, i.name))
        return _plan({(Pool.ON_DEMAND, instance.name): nodes_for(self.peak_vcpu, instance)}, ctx)


@dataclass
class OnDemandHpa:
    """P1: HPA on CPU utilisation plus an on-demand-only node pool.

    The fixed point of the HPA ratio is ``demand / target_utilisation``. The
    default target is ``1 / 1.15`` so that every baseline provisions the same
    15% headroom as the hedged policy; the usual 70% target is a sensitivity
    case (see the experiment protocol).
    """

    target_utilisation: float = 1.0 / 1.15
    stabilisation_seconds: int = 300
    tolerance: float = 0.10
    name: str = "P1-ondemand-hpa"
    _history: deque[tuple[float, float]] = field(default_factory=deque)

    def decide(self, ctx: DecisionContext) -> Plan:
        instance = pick_instance(ctx.catalogue, preferred_vcpu=8)
        target = ctx.demand_vcpu / self.target_utilisation if ctx.demand_vcpu > 0 else 0.0

        self._history.append((ctx.now_seconds, target))
        cutoff = ctx.now_seconds - self.stabilisation_seconds
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()
        # HPA uses the maximum recommendation inside the window.
        stabilised = max(value for _, value in self._history)
        if target >= stabilised:
            stabilised = target

        desired_nodes = nodes_for(stabilised, instance)
        current_nodes = ctx.node_counts.get((Pool.ON_DEMAND, instance.name), 0)
        # HPA ignores changes inside its tolerance band (default 10%).
        if current_nodes and abs(desired_nodes - current_nodes) <= max(
            1, int(self.tolerance * current_nodes)
        ):
            desired_nodes = current_nodes

        return _plan({(Pool.ON_DEMAND, instance.name): desired_nodes}, ctx)


@dataclass
class FixedRatio:
    """P2: a constant spot/on-demand split with reactive sizing."""

    spot_share: float = 0.70
    headroom: float = 0.15
    name: str = "P2-fixed-ratio"

    def decide(self, ctx: DecisionContext) -> Plan:
        instance = pick_instance(ctx.catalogue, preferred_vcpu=8)
        total = ctx.demand_vcpu * (1.0 + self.headroom)
        spot_capacity = total * self.spot_share
        od_capacity = total - spot_capacity
        nodes = {
            (Pool.ON_DEMAND, instance.name): nodes_for(od_capacity, instance),
            (Pool.SPOT_A, instance.name): nodes_for(spot_capacity / 2, instance),
            (Pool.SPOT_B, instance.name): nodes_for(spot_capacity / 2, instance),
        }
        return _plan(nodes, ctx)


BASELINES = {
    "p0": StaticPeak,
    "p1": OnDemandHpa,
    "p2": FixedRatio,
}


def build_baseline(name: str) -> object:
    try:
        return BASELINES[name.lower()]()
    except KeyError as exc:
        raise ValueError(f"unknown policy {name!r}; known: {sorted(BASELINES)}") from exc


__all__ = [
    "ALL_POOLS",
    "BASELINES",
    "FixedRatio",
    "OnDemandHpa",
    "StaticPeak",
    "build_baseline",
    "nodes_for",
    "pick_instance",
]
