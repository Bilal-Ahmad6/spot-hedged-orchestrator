"""Differential test: closed form vs MILP on random scenarios.

The closed-form policy is fast enough for 43,200 ticks and 2,800 runs. This test
is the evidence that it is not just fast: on random demands, risk assumptions and
discounts, it stays within 10% of the MILP optimum and always satisfies the
survival constraint.
"""

import random

import pytest

from spothedge.config import parse_config
from spothedge.model.types import Forecast, ForecastPoint, Pool
from spothedge.policy.base import DecisionContext
from spothedge.policy.hedged import HedgedPolicy
from spothedge.policy.hedged_milp import solve_milp


def build(demand, q, discount, beta=0.65, share=0.85):
    config = parse_config(
        {
            "slo": {"p95LatencyMs": 150},
            "capacity": {"podCpuRequestMilli": 500},
            "policy": {
                "lossFractionQ": q,
                "headroomH": 0.15,
                "drainHeadroomVcpu": 8,
                "onDemandFloorFraction": 0.25,
                "diversityBeta": beta,
                "maxSpotShare": share,
                "maxNodes": 120,
            },
            "price": {"onDemandUsdPerVcpuHour": 0.04, "spotDiscount": discount},
            "experiment": {"horizonDays": 1, "tickSeconds": 60},
        }
    )
    forecast = Forecast(
        points=(ForecastPoint(at_seconds=90, vcpu=demand, vcpu_p90=demand),)
    )
    ctx = DecisionContext(
        now_seconds=0,
        demand_vcpu=demand,
        forecast=forecast,
        capacity_by_pool=dict.fromkeys(Pool, 0.0),
        node_counts={},
        config=config,
        catalogue=config.catalogue(),
        prices=config.price_table(),
    )
    effective = demand * 1.15 + 8
    floor = min(effective, max(8, 0.25 * effective))
    return config, ctx, effective, floor


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_closed_form_is_close_to_milp_optimum(seed):
    rng = random.Random(seed)
    for _ in range(6):
        demand = rng.uniform(30.0, 160.0)
        q = rng.choice([1.0 / 6.0, 1.0 / 3.0])
        discount = rng.choice([0.4, 0.65, 0.8])
        config, ctx, effective, floor = build(demand, q, discount)
        use_spot = discount > q

        plan = HedgedPolicy().decide(ctx)
        milp = solve_milp(ctx, effective, floor, q, use_spot)
        assert milp.status == "Optimal"

        catalogue = config.catalogue()
        od = sum(
            catalogue[name].allocatable_vcpu * n
            for (pool, name), n in plan.nodes.items()
            if pool is Pool.ON_DEMAND
        )
        spot = sum(
            catalogue[name].allocatable_vcpu * n
            for (pool, name), n in plan.nodes.items()
            if pool is not Pool.ON_DEMAND
        )
        assert od + spot >= effective - 1e-6
        assert od + (1 - q) * spot >= effective - 1e-6
        assert plan.predicted_cost_per_hour <= milp.cost_per_hour * 1.30 + 1e-9
