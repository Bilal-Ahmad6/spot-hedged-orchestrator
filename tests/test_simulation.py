import numpy as np

from spothedge.config import parse_config
from spothedge.simulate.interruptions import InterruptionConfig
from spothedge.simulate.runner import simulate


def config_1day():
    return parse_config(
        {
            "slo": {"p95LatencyMs": 150},
            "capacity": {"podCpuRequestMilli": 500},
            "policy": {"headroomH": 0.15, "lossFractionQ": 0.5, "drainSeconds": 20},
            "price": {"onDemandUsdPerVcpuHour": 0.04, "spotDiscount": 0.65},
            "workload": {"seed": 11},
            "experiment": {"horizonDays": 1, "tickSeconds": 60},
        }
    )


def test_same_seed_produces_identical_results():
    demand = np.full(1440, 80.0)
    interruptions = InterruptionConfig(
        model="correlated",
        correlated_prob_per_hour=2.0,
        correlated_q=0.5,
        notice_seconds=0,
    )
    first, _ = simulate(config_1day(), demand, "p2", interruptions, seed=11)
    second, _ = simulate(config_1day(), demand, "p2", interruptions, seed=11)
    assert first.to_dict() == second.to_dict()


def test_abrupt_reclaim_causes_measurable_loss():
    demand = np.full(1440, 80.0)
    abrupt = InterruptionConfig(
        model="correlated",
        correlated_prob_per_hour=2.0,
        correlated_q=0.5,
        notice_seconds=0,
    )
    graceful = InterruptionConfig(
        model="correlated",
        correlated_prob_per_hour=2.0,
        correlated_q=0.5,
        notice_seconds=120,
    )
    hard, _ = simulate(config_1day(), demand, "p2", abrupt, seed=11)
    soft, _ = simulate(config_1day(), demand, "p2", graceful, seed=11)

    assert hard.interruption_count > 0
    assert hard.lost_in_flight > 0
    assert soft.lost_in_flight == 0


def test_steady_state_has_no_failures_without_interruptions():
    demand = np.full(1440, 60.0)
    result, _ = simulate(
        config_1day(),
        demand,
        "p2",
        InterruptionConfig(model="none"),
        seed=11,
    )
    assert result.availability == 1.0
    assert result.lost_in_flight == 0
    assert result.violation_seconds == 0
