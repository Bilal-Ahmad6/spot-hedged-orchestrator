import math

import pytest

from spothedge.simulate.queueing import (
    WorkloadModel,
    erlang_c,
    lost_in_flight,
    p95_latency_ms,
    served_fraction,
)

WORKLOAD = WorkloadModel(service_time_s=0.05, service_cv=1.2, requests_per_vcpu_second=20.0)


def test_p95_grows_with_utilisation():
    # Small server pool so queueing is visible before saturation.
    low = p95_latency_ms(0.4, 1.0, 0.5, WORKLOAD)
    high = p95_latency_ms(0.9, 1.0, 0.5, WORKLOAD)
    assert low < high
    assert low > 0


def test_p95_is_infinite_at_or_above_capacity():
    assert math.isinf(p95_latency_ms(80, 80, 0.5, WORKLOAD))
    assert math.isinf(p95_latency_ms(90, 80, 0.5, WORKLOAD))
    assert math.isinf(p95_latency_ms(10, 0, 0.5, WORKLOAD))


def test_zero_demand_returns_service_time():
    assert p95_latency_ms(0, 80, 0.5, WORKLOAD) == pytest.approx(50.0)


def test_erlang_c_bounds():
    assert erlang_c(0, 1.0) == 1.0
    assert erlang_c(10, 0.0) == 0.0
    assert erlang_c(10, 10.0) == 1.0
    assert 0.0 < erlang_c(10, 5.0) < 1.0


def test_served_fraction():
    assert served_fraction(0, 0) == 1.0
    assert served_fraction(10, 0) == 0.0
    assert served_fraction(80, 100) == 1.0
    assert served_fraction(100, 80) == pytest.approx(0.8)


def test_lost_in_flight_scales_with_pods_lost():
    one = lost_in_flight(70, 1, 70, 0.5, WORKLOAD)
    three = lost_in_flight(70, 3, 70, 0.5, WORKLOAD)
    assert three == pytest.approx(3 * one)
    assert one > 0
    assert lost_in_flight(0, 5, 0, 0.5, WORKLOAD) == 0.0
