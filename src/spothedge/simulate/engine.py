"""Time-stepped simulation engine.

One tick = one policy decision + one SLO evaluation + one ledger accrual. Node
readiness and drain ramps are continuous functions of time, so every quantity in
the result is derived from timestamps rather than accumulated state that could
drift.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np

from spothedge.config import Config
from spothedge.model.types import DecisionRecord, Interruption, Plan
from spothedge.policy.base import DecisionContext, Policy
from spothedge.simulate.interruptions import InterruptionConfig, InterruptionModel
from spothedge.simulate.ledger import CostLedger
from spothedge.simulate.nodes import NodePool
from spothedge.simulate.queueing import (
    WorkloadModel,
    lost_in_flight,
    p95_latency_ms,
    served_fraction,
)

P95_STAT_CAP_MS = 10_000.0


@dataclass
class SimulationResult:
    policy: str
    cost_usd: float
    cost_by_pool: dict[str, float]
    node_hours: float
    availability: float
    total_requests: float
    failed_requests: float
    violation_seconds: float
    p95_mean_ms: float
    p95_p95_ms: float
    p95_max_ms: float
    lost_in_flight: float
    node_launches: int
    node_drains: int
    interruption_count: int
    mean_capacity_vcpu: float
    peak_capacity_vcpu: float
    mean_demand_vcpu: float
    recovery_seconds: list[float]

    def to_dict(self) -> dict:
        payload = dict(self.__dict__)
        return payload


@dataclass
class Simulation:
    config: Config
    policy: Policy
    demand: np.ndarray
    interruptions: InterruptionConfig = field(default_factory=InterruptionConfig)
    seed: int | None = None
    record_every: int = 0
    warm_start: bool = True
    workload: WorkloadModel | None = None

    def __post_init__(self) -> None:
        if len(self.demand) == 0:
            raise ValueError("demand series is empty")
        self._catalogue = self.config.catalogue()
        self._prices = self.config.price_table()
        self._pool = NodePool(catalogue=self._catalogue)
        self._ledger = CostLedger(prices=self._prices, catalogue=self._catalogue)
        self._rng = random.Random(self.seed if self.seed is not None else self.config.workload.seed)
        self._interruption_model = InterruptionModel(self.interruptions, self._rng)
        self._workload = self.workload or WorkloadModel(
            service_time_s=self.config.workload.service_time_s,
            service_cv=self.config.workload.service_cv,
            requests_per_vcpu_second=self.config.workload.requests_per_vcpu_second,
        )
        self._records: list[dict] = []
        self._pending_recovery: list[tuple[float, float]] = []
        self._recovery_seconds: list[float] = []
        self._lost = 0.0
        self._total_requests = 0.0
        self._failed_requests = 0.0
        self._violation_seconds = 0.0
        self._p95_samples: list[float] = []
        self._capacities: list[float] = []
        self._demands: list[float] = []
        self._launches = 0
        self._drains = 0
        self._interruptions = 0

    # ------------------------------------------------------------------ helpers

    @property
    def policy_tick_seconds(self) -> int:
        return int(self.config.experiment.tick_seconds)

    def _demand_at(self, t: float) -> float:
        minute = int(t) // 60
        if minute >= len(self.demand):
            return float(self.demand[-1])
        return float(self.demand[minute])

    def _handle_interruption(self, event: Interruption, t: float, capacity_before: float) -> None:
        node = next((n for n in self._pool.nodes if n.node_id == event.node), None)
        if node is None or node.is_terminated(t):
            return
        drain_seconds = float(self.config.policy.drain_seconds)
        self._interruptions += 1
        if event.notice_seconds >= drain_seconds:
            self._pool.drain(node, t, drain_seconds)
        else:
            pods = node.pods_at(t, self.config.pod_cpu_vcpu)
            self._lost += lost_in_flight(
                self._demand_at(t),
                pods,
                capacity_before,
                self.config.pod_cpu_vcpu,
                self._workload,
            )
            self._pool.drain(node, t, 0.0)
        self._pending_recovery.append((t, capacity_before))

    def _check_recovery(self, t: float, capacity: float) -> None:
        still_pending: list[tuple[float, float]] = []
        for started, baseline in self._pending_recovery:
            if capacity >= 0.99 * baseline and t > started:
                self._recovery_seconds.append(t - started)
            else:
                still_pending.append((started, baseline))
        self._pending_recovery = still_pending

    def _record(
        self,
        t: float,
        tick: int,
        demand: float,
        capacity: float,
        p95: float,
        served: float,
        plan: Plan,
    ) -> None:
        record = DecisionRecord(
            schema_version="1.0",
            decision_id=DecisionRecord.new_id(),
            tick=tick,
            inputs={
                "demandVcpu": round(demand, 3),
                "capacityByPool": {
                    pool.value: round(value, 3)
                    for pool, value in self._pool.capacity_by_pool(t).items()
                },
                "p95LatencyMs": round(p95, 2) if math.isfinite(p95) else None,
                "servedFraction": round(served, 5),
                "sloP95Ms": self.config.slo.p95_latency_ms,
            },
            constraints={"status": "EVALUATED_IN_M2"},
            plan={
                "nodes": {
                    f"{pool.value}/{name}": count
                    for (pool, name), count in plan.nodes.items()
                },
                "predictedCostPerHour": round(plan.predicted_cost_per_hour, 4),
            },
            reason="BASELINE",
            solver={"name": "rule", "status": "OK"},
            action={},
        )
        self._records.append(record.to_dict())

    # --------------------------------------------------------------------- run

    def run(self) -> SimulationResult:
        dt = self.policy_tick_seconds
        minutes = len(self.demand)
        ticks = int(math.ceil(minutes * 60 / dt))

        for tick in range(ticks):
            t = tick * dt
            demand = self._demand_at(t)

            capacity_before = self._pool.capacity(t)
            events = self._interruption_model.poll(
                t, dt, self._pool.ready_spot_nodes(t), demand
            )
            for event in events:
                self._handle_interruption(event, t, capacity_before)

            context = DecisionContext(
                now_seconds=t,
                demand_vcpu=demand,
                forecast=None,
                capacity_by_pool=self._pool.capacity_by_pool(t),
                node_counts=self._pool.counts(t),
                config=self.config,
                catalogue=self._catalogue,
                prices=self._prices,
            )
            plan = self.policy.decide(context)
            actions = self._pool.ensure(
                plan,
                t,
                lead_seconds=float(self.config.policy.lead_time_seconds),
                drain_seconds=float(self.config.policy.drain_seconds),
                immediate=self.warm_start and tick == 0,
            )
            self._launches += len(actions["launched"])
            self._drains += len(actions["drained"])

            capacity = self._pool.capacity(t)
            p95 = p95_latency_ms(
                demand, capacity, self.config.pod_cpu_vcpu, self._workload
            )
            served = served_fraction(demand, capacity)
            requests = demand * self._workload.requests_per_vcpu_second * dt
            failed = (1.0 - served) * requests

            self._total_requests += requests
            self._failed_requests += failed
            if demand > 0 and (
                p95 > self.config.slo.p95_latency_ms
                or served < self.config.slo.min_availability
            ):
                self._violation_seconds += dt

            self._p95_samples.append(min(p95, P95_STAT_CAP_MS))
            self._capacities.append(capacity)
            self._demands.append(demand)

            self._ledger.accrue(self._pool.nodes, t, dt)
            self._check_recovery(t, capacity)

            if self.record_every and tick % self.record_every == 0:
                self._record(t, tick, demand, capacity, p95, served, plan)

            self._pool.advance(t)

        failed_total = self._failed_requests + self._lost
        availability = 1.0 - failed_total / self._total_requests if self._total_requests else 1.0
        p95_array = np.asarray(self._p95_samples, dtype=float)

        return SimulationResult(
            policy=self.policy.name,
            cost_usd=self._ledger.total_usd,
            cost_by_pool={pool.value: value for pool, value in self._ledger.by_pool.items()},
            node_hours=self._ledger.node_hours(),
            availability=max(0.0, min(1.0, availability)),
            total_requests=self._total_requests,
            failed_requests=failed_total,
            violation_seconds=self._violation_seconds,
            p95_mean_ms=float(np.mean(p95_array)),
            p95_p95_ms=float(np.percentile(p95_array, 95)),
            p95_max_ms=float(np.max(p95_array)),
            lost_in_flight=self._lost,
            node_launches=self._launches,
            node_drains=self._drains,
            interruption_count=self._interruptions,
            mean_capacity_vcpu=float(np.mean(self._capacities)),
            peak_capacity_vcpu=float(np.max(self._capacities)),
            mean_demand_vcpu=float(np.mean(self._demands)),
            recovery_seconds=self._recovery_seconds,
        )

    @property
    def records(self) -> list[dict]:
        return self._records
