"""Controller runtime: the same policy, driven by a cluster instead of a simulator.

The runtime is deliberately thin. It obtains demand, builds the same
``DecisionContext`` the simulator builds, calls the same policy object, hands the
plan to an actuator, and appends one auditable record. No policy logic lives here.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from spothedge.config import Config, load_config
from spothedge.forecast.seasonal import HistoryView, SeasonalNaiveForecaster
from spothedge.model.types import DecisionRecord, Pool
from spothedge.policy.base import DecisionContext
from spothedge.policy.baselines import build_baseline
from spothedge.policy.hedged import HedgedPolicy


class DemandSource(Protocol):
    def demand(self, now_seconds: float) -> float: ...

    def prefill(self, now_seconds: float) -> list[float]: ...


class TraceReplaySource:
    """Replays the demand trace at ``time_scale`` × wall-clock speed."""

    def __init__(self, csv_path: Path, time_scale: float, start: float | None = None) -> None:
        import pandas as pd

        self.values = pd.read_csv(csv_path)["demand_vcpu"].to_numpy(dtype=float)
        self.time_scale = time_scale
        self.start = time.time() if start is None else start

    def _minute(self, now_seconds: float) -> int:
        elapsed = (now_seconds - self.start) * self.time_scale
        return max(0, int(elapsed // 60))

    def demand(self, now_seconds: float) -> float:
        index = min(self._minute(now_seconds), len(self.values) - 1)
        return float(self.values[index])

    def prefill(self, now_seconds: float) -> list[float]:
        minute = min(self._minute(now_seconds), len(self.values) - 1)
        start = max(0, minute - 1440)
        return [float(v) for v in self.values[start:minute]]


class PrometheusSource:
    """Demand from a PromQL query, converted from rps to vCPU equivalents."""

    def __init__(self, base_url: str, query: str, rps_per_vcpu: float = 20.0) -> None:
        import urllib.parse
        import urllib.request

        self.base_url = base_url.rstrip("/")
        self.query = query
        self.rps_per_vcpu = rps_per_vcpu
        self._urllib = urllib.request
        self._parse = urllib.parse

    def demand(self, now_seconds: float) -> float:
        url = f"{self.base_url}/api/v1/query?query={self._parse.quote(self.query)}"
        with self._urllib.urlopen(url, timeout=5) as response:
            payload = json.load(response)
        result = payload["data"]["result"]
        if not result:
            raise RuntimeError("empty Prometheus result")
        rps = float(result[0]["value"][1])
        return rps / self.rps_per_vcpu

    def prefill(self, now_seconds: float) -> list[float]:
        return []


@dataclass
class ControllerRuntime:
    config: Config
    policy: object
    actuator: object
    source: DemandSource
    log_path: Path
    history: list[float] = field(default_factory=list)
    forecaster: SeasonalNaiveForecaster = field(default_factory=SeasonalNaiveForecaster)
    started_at: float = field(default_factory=time.time)
    decisions: int = 0

    def __post_init__(self) -> None:
        self.history = list(self.source.prefill(self.started_at))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _reclaim_deficit(self, now_seconds: float) -> float:
        getter = getattr(self.actuator, "pending_reclaims", None)
        if getter is None:
            return 0.0
        return sum(capacity for _, capacity, _ in getter(now_seconds))

    def _service_reclaims(self, now_seconds: float, demand: float, capacity: float) -> None:
        getter = getattr(self.actuator, "pending_reclaims", None)
        if getter is None:
            return
        drain_seconds = float(self.config.policy.drain_seconds)
        spare = capacity - demand
        for name, node_capacity, deadline in sorted(getter(now_seconds), key=lambda r: r[2]):
            if now_seconds + drain_seconds >= deadline or spare >= node_capacity:
                self.actuator.drain(name, now_seconds + drain_seconds)
                spare -= node_capacity

    def tick(self, now_seconds: float) -> dict:
        demand = self.source.demand(now_seconds)
        self.history.append(demand)
        view = HistoryView(self.history, len(self.history))
        self.forecaster.update(view)
        forecast = self.forecaster.forecast(view)

        state = self.actuator.current()
        catalogue = self.config.catalogue()
        capacity_by_pool = dict.fromkeys(Pool, 0.0)
        for (pool, name), count in state.nodes.items():
            instance = catalogue.get(name)
            if instance is not None:
                capacity_by_pool[pool] += instance.allocatable_vcpu * count

        context = DecisionContext(
            now_seconds=now_seconds,
            demand_vcpu=demand,
            forecast=forecast,
            capacity_by_pool=capacity_by_pool,
            node_counts=state.nodes,
            config=self.config,
            catalogue=catalogue,
            prices=self.config.price_table(),
            reclaim_deficit_vcpu=self._reclaim_deficit(now_seconds),
        )
        plan = self.policy.decide(context)
        actions = self.actuator.ensure(plan, now_seconds)
        self._service_reclaims(now_seconds, demand, sum(capacity_by_pool.values()))

        self.decisions += 1
        record = DecisionRecord(
            schema_version="1.0",
            decision_id=DecisionRecord.new_id(),
            tick=self.decisions,
            inputs={
                "demandVcpu": round(demand, 3),
                "forecastP90Vcpu": round(
                    forecast.at(self.config.policy.lead_time_seconds).vcpu_p90, 3
                ),
                "reclaimDeficitVcpu": round(self._reclaim_deficit(now_seconds), 3),
                "capacityByPool": {p.value: round(v, 3) for p, v in capacity_by_pool.items()},
                "drainingNodes": list(state.draining),
            },
            constraints={"status": "EVALUATED_BY_POLICY"},
            plan={
                "nodes": {
                    f"{pool.value}/{name}": count
                    for (pool, name), count in plan.nodes.items()
                },
                "predictedCostPerHour": round(plan.predicted_cost_per_hour, 4),
                "solverStatus": plan.solver_status,
            },
            reason="POLICY_DECISION",
            solver={"name": "closed-form"},
            action={
                "launched": actions.get("launched", []),
                "drained": actions.get("drained", []),
            },
        ).to_dict()

        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
            handle.flush()
        return record


def build_policy(name: str):
    if name.lower() in {"p3", "hedge", "hedged"}:
        return HedgedPolicy()
    return build_baseline(name)


def build_runtime(config_path: Path, policy_name: str, actuator, source, log_path: Path):
    config = load_config(config_path)
    return ControllerRuntime(
        config=config,
        policy=build_policy(policy_name),
        actuator=actuator,
        source=source,
        log_path=Path(log_path),
    )
