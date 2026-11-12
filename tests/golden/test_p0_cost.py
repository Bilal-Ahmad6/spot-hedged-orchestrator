"""Golden cost checks: the first numbers the report will quote.

Two separate claims are tested:

1. The ledger arithmetic reproduces the proposal's continuous model exactly when
   a node is exactly the modelled capacity (160 vCPU, no overhead).
2. Discrete packing changes the number, by a factor we can compute by hand. This
   is the ADR-0005 correction, made executable.
"""

import numpy as np
import pytest

from spothedge.config import parse_config
from spothedge.simulate.runner import simulate

HOURS_PER_MONTH = 730.0


def flat_config(instances=None):
    data = {
        "slo": {"p95LatencyMs": 150},
        "capacity": {"podCpuRequestMilli": 500},
        "policy": {"headroomH": 0.15, "lossFractionQ": 0.3333},
        "price": {"onDemandUsdPerVcpuHour": 0.04, "spotDiscount": 0.65},
        "workload": {"seed": 7},
        "experiment": {"horizonDays": 1, "tickSeconds": 60},
    }
    if instances is not None:
        data["instances"] = instances
    return parse_config(data)


def monthly(cost_usd: float, hours: float) -> float:
    return cost_usd / hours * HOURS_PER_MONTH


def test_p0_continuous_cost_matches_proposal():
    """160 vCPU on-demand for a month = $4,672 exactly."""

    config = flat_config(
        instances=[{"name": "flat160", "vcpu": 160, "system_overhead_vcpu": 0.0}]
    )
    demand = np.full(1440, 150.0)  # 150 < 160 so the SLO is satisfiable
    result, _ = simulate(config, demand, policy_name="p0")

    assert result.policy == "P0-static-peak"
    assert result.node_launches == 1
    assert monthly(result.cost_usd, 24.0) == pytest.approx(4672.0, rel=1e-3)


def test_p0_discrete_packing_adds_about_ten_percent():
    """Default catalogue: 160 vCPU needs 11 x 16-vCPU nodes = 176 vCPU."""

    config = flat_config()
    demand = np.full(1440, 150.0)
    result, _ = simulate(config, demand, policy_name="p0")

    # 11 nodes * 16 vCPU * $0.04/h * 730 h
    assert monthly(result.cost_usd, 24.0) == pytest.approx(5139.2, rel=1e-3)
    assert result.peak_capacity_vcpu == pytest.approx(11 * 15.7)


def test_availability_is_one_when_capacity_covers_demand():
    config = flat_config()
    demand = np.full(1440, 100.0)
    result, _ = simulate(config, demand, policy_name="p0")
    assert result.availability == pytest.approx(1.0)
    assert result.violation_seconds == 0


def test_zero_capacity_fails_every_request():
    config = flat_config()
    demand = np.full(1440, 100.0)

    from spothedge.model.types import Plan
    from spothedge.simulate.engine import Simulation
    from spothedge.simulate.interruptions import InterruptionConfig

    class Never:
        name = "never"

        def decide(self, ctx):
            return Plan(nodes={}, predicted_cost_per_hour=0.0)

    sim = Simulation(
        config=config,
        policy=Never(),
        demand=demand,
        interruptions=InterruptionConfig(model="none"),
        warm_start=False,
    )
    empty = sim.run()
    assert empty.availability == 0.0
    assert empty.cost_usd == 0.0
