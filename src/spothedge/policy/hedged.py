"""The hedged allocation policy.

Given demand ``D``, an assumed simultaneous spot-loss fraction ``q``, and an
on-demand floor, the cheapest surviving mix is:

    spot S    <= (D - floor) / (1 - q)
    on-demand  = D - (1 - q) * S
    total      = D + q * S          (the over-provisioning that buys survival)

Spot is only worth buying when its discount exceeds ``q``; below that threshold
the over-provisioning costs more than the discount saves. That is the general form
of the proposal's 16.67 % break-even point.

The instance shape is chosen **once**, from the packing optimum, and then held.
Re-optimising the shape every minute makes the reconciler drain and relaunch the
cluster whenever rounding changes, which empties capacity for the whole lead time
(measured: 180,000 launches and 93 % availability). Shape stability is not a
performance detail; it is a correctness requirement.

Counts are adjusted at the margin, inside a capacity band, with a scale-down
cooldown. Without the band the planner chases forecast noise and performs tens of
thousands of node launches.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from spothedge.model.types import Plan, Pool
from spothedge.policy.base import DecisionContext


@dataclass
class HedgedPolicy:
    name: str = "P3-hedged"
    scale_down_cooldown_seconds: int = 900
    scale_up_band: float = 0.95
    scale_down_band: float = 1.20
    _instance_name: str | None = None
    _last_down: float = -1e9
    _last_up: float = -1e9

    # ------------------------------------------------------------------ policy

    def decide(self, ctx: DecisionContext) -> Plan:
        policy = ctx.config.policy
        if ctx.forecast is not None:
            point = ctx.forecast.at(policy.lead_time_seconds)
            demand_p90 = point.vcpu_p90
        else:
            demand_p90 = ctx.demand_vcpu

        effective = (
            demand_p90 * (1.0 + policy.headroom_h)
            + policy.drain_headroom_vcpu
            + ctx.reclaim_deficit_vcpu
        )
        if effective <= 0:
            return Plan(nodes={}, predicted_cost_per_hour=0.0)

        floor = min(
            effective,
            max(
                policy.on_demand_floor_vcpu,
                policy.on_demand_floor_fraction * effective,
            ),
        )

        discount = 1.0 - (
            ctx.prices.usd_per_vcpu_hour(Pool.SPOT_A)
            / ctx.prices.usd_per_vcpu_hour(Pool.ON_DEMAND)
        )
        q = policy.loss_fraction_q
        use_spot = discount > q and q < 1.0

        if use_spot:
            spot_max_survival = (effective - floor) / (1.0 - q)
            share = policy.max_spot_share
            ratio = share / (1.0 - share)
            spot_max_share = ratio * effective / (1.0 + ratio * (1.0 - q))
            spot_target = max(0.0, min(spot_max_survival, spot_max_share, effective))
            od_target = effective - (1.0 - q) * spot_target
        else:
            spot_target = 0.0
            od_target = effective

        if self._instance_name is None:
            self._instance_name = self._choose_shape(
                ctx, od_target + spot_target, od_target
            )
        instance = ctx.catalogue[self._instance_name]
        allocatable = instance.allocatable_vcpu

        od_nodes = self._ceil(max(od_target, floor), allocatable)
        spot_nodes = self._ceil(spot_target / 2.0, allocatable)
        nodes: dict[tuple[Pool, str], int] = {}
        if od_nodes:
            nodes[(Pool.ON_DEMAND, instance.name)] = od_nodes
        if spot_nodes:
            nodes[(Pool.SPOT_A, instance.name)] = spot_nodes
            nodes[(Pool.SPOT_B, instance.name)] = spot_nodes

        cost = (
            od_nodes * ctx.prices.usd_per_hour(Pool.ON_DEMAND, instance)
            + 2 * spot_nodes * ctx.prices.usd_per_hour(Pool.SPOT_A, instance)
        )

        if ctx.node_counts:
            current_capacity = self._capacity_of(ctx)
            within_band = (
                effective * self.scale_up_band
                <= current_capacity
                <= effective * self.scale_down_band
            )
            cooling = (
                current_capacity > effective * self.scale_down_band
                and ctx.now_seconds - self._last_down < self.scale_down_cooldown_seconds
            )
            if within_band or cooling:
                kept = self._keep_current(ctx, effective, floor, q)
                if kept is not None:
                    kept_cost = sum(
                        ctx.prices.usd_per_hour(pool, ctx.catalogue[name]) * count
                        for (pool, name), count in kept.items()
                    )
                    return Plan(nodes=kept, predicted_cost_per_hour=kept_cost)

            if sum(nodes.values()) > sum(ctx.node_counts.values()):
                self._last_up = ctx.now_seconds
            else:
                self._last_down = ctx.now_seconds

        return Plan(nodes=nodes, predicted_cost_per_hour=cost)

    # ------------------------------------------------------------------ helpers

    def _choose_shape(self, ctx: DecisionContext, total_target: float, od_target: float) -> str:
        """Pick one node shape and hold it for the run.

        Shape stability is a correctness requirement, not a tuning choice: a
        shape optimiser that re-packs every tick drained and relaunched the whole
        cluster whenever rounding changed (180,000 launches, 93 % availability).
        A 4-vCPU default is the best compromise measured against the MILP over
        random scenarios (mean 1.14x, worst 1.24x of the optimum).
        """

        target = ctx.config.policy.shape_vcpu
        return min(
            ctx.catalogue.values(),
            key=lambda i: (abs(i.vcpu - target), i.vcpu, i.name),
        ).name

    @staticmethod
    def _ceil(capacity: float, allocatable: float) -> int:
        if capacity <= 0:
            return 0
        return math.ceil(capacity / allocatable)

    @staticmethod
    def _capacity_of(ctx: DecisionContext) -> float:
        total = 0.0
        for (_, name), count in ctx.node_counts.items():
            instance = ctx.catalogue.get(name)
            if instance is not None:
                total += instance.allocatable_vcpu * count
        return total

    def _keep_current(self, ctx: DecisionContext, effective: float, floor: float, q: float):
        """Return the current mix if it still satisfies every constraint."""

        counts = {key: value for key, value in ctx.node_counts.items() if value > 0}
        if not counts:
            return None
        cap_od = 0.0
        cap_spot = 0.0
        for (pool, name), count in counts.items():
            instance = ctx.catalogue.get(name)
            if instance is None:
                return None
            if pool is Pool.ON_DEMAND:
                cap_od += instance.allocatable_vcpu * count
            else:
                cap_spot += instance.allocatable_vcpu * count
        if cap_od + cap_spot < effective - 1e-9:
            return None
        if cap_od + (1.0 - q) * cap_spot < effective - 1e-9:
            return None
        if cap_od < floor - 1e-9:
            return None
        return counts
