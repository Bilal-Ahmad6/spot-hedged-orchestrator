
from spothedge.config import parse_config
from spothedge.model.types import Forecast, ForecastPoint, Pool
from spothedge.policy.base import DecisionContext
from spothedge.policy.hedged import HedgedPolicy


def make_config(**policy_overrides):
    policy = {
        "headroomH": 0.15,
        "lossFractionQ": 1.0 / 3.0,
        "onDemandFloorVcpu": 8,
        "onDemandFloorFraction": 0.25,
        "diversityBeta": 0.65,
        "drainHeadroomVcpu": 8,
        "leadTimeSeconds": 90,
        "maxSpotShare": 0.85,
        "maxNodes": 40,
    }
    policy.update(policy_overrides)
    return parse_config(
        {
            "slo": {"p95LatencyMs": 150},
            "capacity": {"podCpuRequestMilli": 500},
            "policy": policy,
            "price": {"onDemandUsdPerVcpuHour": 0.04, "spotDiscount": 0.65},
            "workload": {"seed": 7},
            "experiment": {"horizonDays": 1, "tickSeconds": 60},
        }
    )


def make_context(config, demand=100.0, reclaim=0.0, forecast=None):
    forecast = forecast or Forecast(
        points=(
            ForecastPoint(at_seconds=0, vcpu=demand, vcpu_p90=demand),
            ForecastPoint(at_seconds=600, vcpu=demand, vcpu_p90=demand),
        )
    )
    return DecisionContext(
        now_seconds=0,
        demand_vcpu=demand,
        forecast=forecast,
        capacity_by_pool=dict.fromkeys(Pool, 0.0),
        node_counts={},
        config=config,
        catalogue=config.catalogue(),
        prices=config.price_table(),
        reclaim_deficit_vcpu=reclaim,
    )


def capacity(plan, pool):
    catalogue = make_config().catalogue()
    return sum(
        catalogue[name].allocatable_vcpu * count
        for (p, name), count in plan.nodes.items()
        if p is pool
    )


def test_survival_constraint_holds_after_rounding():
    config = make_config()
    ctx = make_context(config)
    plan = HedgedPolicy().decide(ctx)

    effective = 100.0 * 1.15 + config.policy.drain_headroom_vcpu
    od = capacity(plan, Pool.ON_DEMAND)
    spot = capacity(plan, Pool.SPOT_A) + capacity(plan, Pool.SPOT_B)

    assert od + (1 - config.policy.loss_fraction_q) * spot >= effective - 1e-6
    assert od + spot >= effective - 1e-6


def test_on_demand_floor_is_respected():
    config = make_config(onDemandFloorFraction=0.5)
    plan = HedgedPolicy().decide(make_context(config))
    effective = 100.0 * 1.15 + 8
    assert capacity(plan, Pool.ON_DEMAND) >= 0.5 * effective - 1e-6


def test_q_equal_one_disables_spot():
    config = make_config(lossFractionQ=1.0)
    plan = HedgedPolicy().decide(make_context(config))
    assert capacity(plan, Pool.SPOT_A) == 0
    assert capacity(plan, Pool.SPOT_B) == 0


def test_discount_below_q_disables_spot():
    config = parse_config(
        {
            "policy": {"lossFractionQ": 0.5},
            "price": {"onDemandUsdPerVcpuHour": 0.04, "spotDiscount": 0.4},
            "experiment": {"horizonDays": 1, "tickSeconds": 60},
        }
    )
    plan = HedgedPolicy().decide(make_context(config))
    assert capacity(plan, Pool.SPOT_A) == 0


def test_hedge_is_cheaper_than_all_on_demand():
    config = make_config()
    ctx = make_context(config)
    plan = HedgedPolicy().decide(ctx)

    catalogue = config.catalogue()
    instance = catalogue["c6i.2xlarge"]
    import math

    all_od_nodes = math.ceil((100.0 * 1.15 + 8) / instance.allocatable_vcpu)
    all_od_cost = all_od_nodes * ctx.prices.usd_per_hour(Pool.ON_DEMAND, instance)

    assert plan.predicted_cost_per_hour < all_od_cost


def test_reclaim_deficit_increases_capacity():
    config = make_config()
    base = HedgedPolicy().decide(make_context(config))
    stressed = HedgedPolicy().decide(make_context(config, reclaim=16.0))
    base_total = base.capacity_vcpu(config.catalogue())
    stressed_total = stressed.capacity_vcpu(config.catalogue())
    assert stressed_total > base_total


def test_diversity_cap_is_respected():
    config = make_config(diversityBeta=0.6)
    plan = HedgedPolicy().decide(make_context(config))
    a = capacity(plan, Pool.SPOT_A)
    b = capacity(plan, Pool.SPOT_B)
    total = a + b
    assert total > 0
    assert max(a, b) <= 0.6 * total + 1e-6
