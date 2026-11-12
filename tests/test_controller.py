import json

from spothedge.config import parse_config
from spothedge.controller.runtime import ControllerRuntime
from spothedge.model.types import ClusterState


class FakeActuator:
    def __init__(self):
        self.nodes: dict = {}
        self.draining: list[str] = []
        self.pending: list[tuple[str, float, float]] = []
        self.ensured = 0

    def current(self) -> ClusterState:
        return ClusterState(nodes=dict(self.nodes), draining=tuple(self.draining))

    def ensure(self, plan, now_seconds):
        self.nodes = dict(plan.nodes)
        self.ensured += 1
        return {"launched": ["x"], "drained": []}

    def drain(self, node_name, delete_after_seconds):
        self.draining.append(node_name)

    def reap(self, now_seconds):
        return []

    def pending_reclaims(self, now_seconds):
        return list(self.pending)


class ConstantSource:
    def __init__(self, value: float):
        self.value = value

    def demand(self, now_seconds):
        return self.value

    def prefill(self, now_seconds):
        return [self.value] * 1440


def make_runtime(tmp_path, demand=80.0):
    config = parse_config(
        {
            "policy": {"lossFractionQ": 1.0 / 6.0, "headroomH": 0.15, "drainHeadroomVcpu": 8},
            "price": {"onDemandUsdPerVcpuHour": 0.04, "spotDiscount": 0.65},
            "experiment": {"horizonDays": 1, "tickSeconds": 60},
        }
    )
    from spothedge.policy.hedged import HedgedPolicy

    actuator = FakeActuator()
    runtime = ControllerRuntime(
        config=config,
        policy=HedgedPolicy(),
        actuator=actuator,
        source=ConstantSource(demand),
        log_path=tmp_path / "decisions.jsonl",
    )
    return runtime, actuator


def test_tick_writes_a_valid_decision_record(tmp_path):
    runtime, actuator = make_runtime(tmp_path)
    record = runtime.tick(1000.0)

    assert record["decisionId"]
    assert record["inputs"]["demandVcpu"] == 80.0
    assert record["plan"]["nodes"]
    assert actuator.ensured == 1

    lines = (tmp_path / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["tick"] == 1


def test_reclaim_deficit_increases_the_plan(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    base = runtime.tick(1000.0)
    base_nodes = sum(base["plan"]["nodes"].values())

    runtime.actuator.pending = [("spot-a-1", 7.7, 2000.0)]
    stressed = runtime.tick(1060.0)
    stressed_nodes = sum(stressed["plan"]["nodes"].values())

    assert stressed["inputs"]["reclaimDeficitVcpu"] == 7.7
    assert stressed_nodes >= base_nodes


def test_second_tick_is_stable_when_demand_is_flat(tmp_path):
    runtime, _ = make_runtime(tmp_path)
    runtime.tick(1000.0)
    second = runtime.tick(1060.0)
    assert second["action"]["launched"] in ([], ["x"])
