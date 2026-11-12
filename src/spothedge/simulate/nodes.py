"""Node lifecycle for the discrete-event testbed.

A node's state is derived from timestamps rather than mutated flags, which makes
the billing window, the readiness window and the drain ramp impossible to
disagree with each other.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from spothedge.model.types import Plan, Pool


@dataclass(slots=True)
class SimNode:
    node_id: str
    pool: Pool
    instance_type: str
    vcpu: int
    allocatable_vcpu: float
    launched_at: float
    ready_at: float
    drain_started_at: float | None = None
    drain_complete_at: float | None = None

    def is_ready(self, t: float) -> bool:
        return t >= self.ready_at and self.drain_started_at is None

    def is_terminated(self, t: float) -> bool:
        return self.drain_complete_at is not None and t >= self.drain_complete_at

    def is_draining(self, t: float) -> bool:
        return (
            self.drain_started_at is not None
            and self.drain_complete_at is not None
            and self.drain_started_at <= t < self.drain_complete_at
        )

    def capacity_at(self, t: float) -> float:
        if t < self.ready_at:
            return 0.0
        if self.drain_started_at is None or self.drain_complete_at is None:
            return self.allocatable_vcpu
        if t >= self.drain_complete_at:
            return 0.0
        span = self.drain_complete_at - self.drain_started_at
        if span <= 0:
            return 0.0
        return self.allocatable_vcpu * max(0.0, (self.drain_complete_at - t) / span)

    def billing_seconds(self, start: float, end: float) -> float:
        """Seconds billed inside [start, end). Cloud bills from launch, not readiness."""

        begin = max(start, self.launched_at)
        finish = min(end, self.drain_complete_at) if self.drain_complete_at else end
        return max(0.0, finish - begin)

    def pods_at(self, t: float, pod_cpu: float) -> int:
        if pod_cpu <= 0:
            return 0
        return int(self.capacity_at(t) // pod_cpu)


@dataclass
class NodePool:
    catalogue: Mapping[str, object]
    nodes: list[SimNode] = field(default_factory=list)
    _sequence: int = 0

    def launch(
        self,
        pool: Pool,
        instance_type: str,
        t: float,
        lead_seconds: float,
    ) -> SimNode:
        instance = self.catalogue[instance_type]
        if t < 0:
            raise ValueError("cannot launch before t=0")
        self._sequence += 1
        node = SimNode(
            node_id=f"{pool}-{self._sequence:04d}",
            pool=pool,
            instance_type=instance_type,
            vcpu=instance.vcpu,
            allocatable_vcpu=instance.allocatable_vcpu,
            launched_at=t,
            ready_at=t + lead_seconds,
        )
        self.nodes.append(node)
        return node

    def drain(self, node: SimNode, t: float, duration_seconds: float) -> None:
        if node.drain_started_at is not None:
            return
        node.drain_started_at = t
        node.drain_complete_at = t + max(duration_seconds, 0.0)

    def capacity_by_pool(self, t: float) -> dict[Pool, float]:
        totals = dict.fromkeys(Pool, 0.0)
        for node in self.nodes:
            capacity = node.capacity_at(t)
            if capacity:
                totals[node.pool] += capacity
        return totals

    def capacity(self, t: float) -> float:
        return sum(node.capacity_at(t) for node in self.nodes)

    def counts(self, t: float) -> Counter[tuple[Pool, str]]:
        counter: Counter[tuple[Pool, str]] = Counter()
        for node in self.nodes:
            if not node.is_terminated(t):
                counter[(node.pool, node.instance_type)] += 1
        return counter

    def ready_spot_nodes(self, t: float) -> list[SimNode]:
        return [n for n in self.nodes if n.pool.is_spot and n.is_ready(t)]

    def ensure(
        self,
        plan: Plan,
        t: float,
        lead_seconds: float,
        drain_seconds: float,
        immediate: bool = False,
    ) -> dict[str, list[str]]:
        """Reconcile the pool to the plan. Returns launched and drained node ids."""

        desired = Counter({key: count for key, count in plan.nodes.items() if count > 0})
        current = self.counts(t)
        launched: list[str] = []
        drained: list[str] = []

        for key in sorted(set(desired) | set(current), key=lambda k: (k[0].value, k[1])):
            deficit = desired.get(key, 0) - current.get(key, 0)
            if deficit > 0:
                pool, instance_type = key
                for _ in range(deficit):
                    node = self.launch(
                        pool,
                        instance_type,
                        t,
                        lead_seconds=0.0 if immediate else lead_seconds,
                    )
                    launched.append(node.node_id)
            elif deficit < 0:
                pool, instance_type = key
                candidates = [
                    node
                    for node in self.nodes
                    if node.pool is pool
                    and node.instance_type == instance_type
                    and not node.is_terminated(t)
                    and node.drain_started_at is None
                ]
                # Drain pending nodes first (no capacity to lose), then oldest ready.
                candidates.sort(key=lambda n: (0 if n.ready_at > t else 1, n.launched_at))
                for node in candidates[: -deficit]:
                    self.drain(node, t, drain_seconds)
                    drained.append(node.node_id)

        return {"launched": launched, "drained": drained}

    def advance(self, t: float) -> None:
        """Drop terminated nodes so long runs do not accumulate dead objects."""

        if not self.nodes:
            return
        self.nodes = [node for node in self.nodes if not node.is_terminated(t)]

    def iter_nodes(self) -> Iterable[SimNode]:
        return iter(self.nodes)
