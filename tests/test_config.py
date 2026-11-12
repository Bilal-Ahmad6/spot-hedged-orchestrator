import pytest

from spothedge.config import parse_config


def base_data():
    return {
        "slo": {"p95LatencyMs": 150},
        "capacity": {"podCpuRequestMilli": 500},
        "policy": {"headroomH": 0.15, "lossFractionQ": 0.3333},
        "price": {"onDemandUsdPerVcpuHour": 0.04, "spotDiscount": 0.65},
        "workload": {"demandCsv": "experiments/traces/demand_30d.csv", "seed": 7},
        "experiment": {"horizonDays": 30, "tickSeconds": 60},
    }


def test_parse_uses_defaults_and_camel_case_keys():
    config = parse_config(base_data())
    assert config.slo.p95_latency_ms == 150
    assert config.policy.headroom_h == 0.15
    assert config.price.spot_discount == 0.65
    assert config.pod_cpu_vcpu == 0.5
    assert len(config.instances) == 4


def test_unknown_key_is_rejected():
    data = base_data()
    data["policy"]["headromH"] = 0.2
    with pytest.raises(ValueError, match="unknown keys"):
        parse_config(data)


def test_invalid_q_is_rejected():
    data = base_data()
    data["policy"]["lossFractionQ"] = 1.5
    with pytest.raises(ValueError, match="q must be"):
        parse_config(data)


def test_default_instances_are_unique():
    config = parse_config({})
    assert len(config.instances) == len({i.name for i in config.instances})
