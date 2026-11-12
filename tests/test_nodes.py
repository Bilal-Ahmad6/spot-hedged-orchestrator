import pytest

from spothedge.model.types import InstanceType, Plan, Pool
from spothedge.simulate.nodes import NodePool, SimNode

CATALOGUE = {
    "c6i.2xlarge": InstanceType(name="c6i.2xlarge", vcpu=8),
    "c6i.4xlarge": InstanceType(name="c6i.4xlarge", vcpu=16),
}


def make_node(**overrides):
    defaults = dict(
        node_id="n1",
        pool=Pool.SPOT_A,
        instance_type="c6i.2xlarge",
        vcpu=8,
        allocatable_vcpu=7.7,
        launched_at=0.0,
        ready_at=90.0,
    )
    defaults.update(overrides)
    return SimNode(**defaults)


def test_node_is_not_schedulable_before_ready():
    node = make_node()
    assert node.capacity_at(0) == 0.0
    assert node.capacity_at(89.9) == 0.0
    assert node.capacity_at(90) == pytest.approx(7.7)


def test_drain_ramps_capacity_down():
    node = make_node(ready_at=0.0, drain_started_at=100.0, drain_complete_at=120.0)
    assert node.capacity_at(100) == pytest.approx(7.7)
    assert node.capacity_at(110) == pytest.approx(3.85)
    assert node.capacity_at(120) == 0.0
    assert node.is_terminated(120)


def test_billing_starts_at_launch_and_ends_at_termination():
    node = make_node(
        launched_at=10.0,
        ready_at=100.0,
        drain_started_at=200.0,
        drain_complete_at=220.0,
    )
    assert node.billing_seconds(0, 10) == 0.0
    assert node.billing_seconds(0, 20) == pytest.approx(10.0)
    assert node.billing_seconds(200, 230) == pytest.approx(20.0)
    assert node.billing_seconds(220, 300) == 0.0


def test_pool_ensure_launches_and_drains_to_plan():
    pool = NodePool(catalogue=CATALOGUE)
    plan = Plan(nodes={(Pool.ON_DEMAND, "c6i.2xlarge"): 2}, predicted_cost_per_hour=0.64)

    actions = pool.ensure(plan, t=0, lead_seconds=90, drain_seconds=20, immediate=True)
    assert len(actions["launched"]) == 2
    assert pool.capacity(0) == pytest.approx(15.4)

    smaller = Plan(nodes={(Pool.ON_DEMAND, "c6i.2xlarge"): 1}, predicted_cost_per_hour=0.32)
    actions = pool.ensure(smaller, t=60, lead_seconds=90, drain_seconds=20)
    assert len(actions["drained"]) == 1
    assert pool.capacity(80) == pytest.approx(7.7)
    assert pool.capacity(100) < 15.4


def test_terminated_nodes_are_dropped():
    pool = NodePool(catalogue=CATALOGUE)
    node = pool.launch(Pool.SPOT_A, "c6i.2xlarge", t=0, lead_seconds=0)
    pool.drain(node, t=10, duration_seconds=10)
    pool.advance(19)
    assert len(pool.nodes) == 1
    pool.advance(21)
    assert pool.nodes == []
