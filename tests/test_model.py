import pytest

from spothedge.model.types import (
    Forecast,
    ForecastPoint,
    InstanceType,
    Plan,
    Pool,
    PriceTable,
)

NODE_8 = InstanceType(name="c6i.2xlarge", vcpu=8)


def test_allocatable_subtracts_system_overhead():
    assert NODE_8.allocatable_vcpu == 7.7


def test_price_table_applies_discount_only_to_spot():
    table = PriceTable(on_demand_usd_per_vcpu_hour=0.04, spot_discount=0.65)
    assert table.usd_per_vcpu_hour(Pool.ON_DEMAND) == 0.04
    assert table.usd_per_vcpu_hour(Pool.SPOT_A) == pytest.approx(0.04 * 0.35)
    assert table.usd_per_hour(Pool.SPOT_B, NODE_8) == pytest.approx(8 * 0.014)


def test_price_table_override_wins():
    table = PriceTable(
        on_demand_usd_per_vcpu_hour=0.04,
        spot_discount=0.5,
        overrides={(Pool.SPOT_A, "c6i.2xlarge"): 0.09},
    )
    assert table.usd_per_hour(Pool.SPOT_A, NODE_8) == 0.09


def test_plan_capacity_by_pool():
    plan = Plan(
        nodes={(Pool.ON_DEMAND, "c6i.2xlarge"): 2, (Pool.SPOT_A, "c6i.2xlarge"): 3},
        predicted_cost_per_hour=1.0,
    )
    catalogue = {"c6i.2xlarge": NODE_8}
    by_pool = plan.capacity_vcpu_by_pool(catalogue)
    assert by_pool[Pool.ON_DEMAND] == 15.4
    assert by_pool[Pool.SPOT_A] == 23.1
    assert by_pool[Pool.SPOT_B] == 0.0
    assert plan.node_count() == 5
    assert plan.node_count(Pool.SPOT_A) == 3


def test_forecast_picks_next_point_and_p90_peak():
    forecast = Forecast(
        points=(
            ForecastPoint(at_seconds=0, vcpu=50, vcpu_p90=55),
            ForecastPoint(at_seconds=60, vcpu=70, vcpu_p90=80),
            ForecastPoint(at_seconds=120, vcpu=60, vcpu_p90=66),
        )
    )
    assert forecast.at(0).vcpu == 50
    assert forecast.at(1).vcpu == 70  # ceiling semantics: first point at/after t
    assert forecast.at(60).vcpu == 70
    assert forecast.at(61).vcpu == 60
    assert forecast.at(999).vcpu == 60
    assert forecast.max_p90(60) == 80
    assert forecast.max_p90(0) == 55


def test_forecast_rejects_p90_below_point_estimate():
    with pytest.raises(ValueError):
        ForecastPoint(at_seconds=0, vcpu=10, vcpu_p90=9)
