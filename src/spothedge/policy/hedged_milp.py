"""MILP reference implementation of the allocation problem.

The deployed policy uses a closed form because the problem has one binding
constraint and constant per-vCPU prices. This module exists to check that claim:
a test generates random scenarios, solves both, and fails if the closed form is
more than a few percent worse or produces an infeasible plan.

Keeping the reference solver around is cheap (a dozen integer variables) and
turns "the closed form is optimal" from an assertion into evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pulp

from spothedge.model.types import ALL_POOLS, Plan, Pool
from spothedge.policy.base import DecisionContext


@dataclass
class MilpResult:
    cost_per_hour: float
    nodes: dict[tuple[Pool, str], int]
    status: str


def solve_milp(
    ctx: DecisionContext,
    effective_vcpu: float,
    floor_vcpu: float,
    q: float,
    use_spot: bool,
) -> MilpResult:
    policy = ctx.config.policy
    problem = pulp.LpProblem("hedged_allocation", pulp.LpMinimize)
    keys = [(pool, name) for pool in ALL_POOLS for name in ctx.catalogue]
    x = {
        key: pulp.LpVariable(
            f"x_{key[0].value}_{key[1]}", lowBound=0, cat=pulp.LpInteger
        )
        for key in keys
    }

    capacities = {
        key: ctx.catalogue[key[1]].allocatable_vcpu for key in keys
    }
    prices = {
        key: ctx.prices.usd_per_hour(key[0], ctx.catalogue[key[1]]) for key in keys
    }

    problem += pulp.lpSum(prices[key] * x[key] for key in keys)

    cap_od = pulp.lpSum(capacities[k] * x[k] for k in keys if k[0] is Pool.ON_DEMAND)
    cap_a = pulp.lpSum(capacities[k] * x[k] for k in keys if k[0] is Pool.SPOT_A)
    cap_b = pulp.lpSum(capacities[k] * x[k] for k in keys if k[0] is Pool.SPOT_B)
    cap_spot = cap_a + cap_b
    cap_total = cap_od + cap_spot

    problem += cap_total >= effective_vcpu
    problem += cap_od + (1.0 - q) * cap_spot >= effective_vcpu
    problem += cap_od >= floor_vcpu
    problem += pulp.lpSum(x.values()) <= policy.max_nodes

    share = policy.max_spot_share
    problem += (1.0 - share) * cap_spot - share * cap_od <= 0

    beta = policy.diversity_beta
    problem += (1.0 - beta) * cap_a - beta * cap_b <= 0
    problem += (1.0 - beta) * cap_b - beta * cap_a <= 0

    if not use_spot:
        problem += cap_spot == 0

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=2)
    try:
        problem.solve(solver)
    except pulp.PulpSolverError as exc:  # pragma: no cover - environment specific
        return MilpResult(math.inf, {}, f"SOLVER_ERROR: {exc}")

    status = pulp.LpStatus[problem.status]
    if status != "Optimal":
        return MilpResult(math.inf, {}, status)

    nodes = {
        key: int(round(value.value() or 0))
        for key, value in x.items()
        if (value.value() or 0) > 0.5
    }
    cost = float(pulp.value(problem.objective) or 0.0)
    return MilpResult(cost, nodes, status)


def plan_from_milp(result: MilpResult) -> Plan:
    return Plan(
        nodes=result.nodes,
        predicted_cost_per_hour=result.cost_per_hour,
        solver_status=result.status,
    )
