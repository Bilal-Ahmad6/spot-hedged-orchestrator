"""KWOK node actuator.

Creates and deletes ``Node`` objects labelled ``kwok.x-k8s.io/node=fake``. KWOK's
controller marks them Ready once created, so the real scheduler, eviction path and
PDB semantics apply; the kubelet is simulated.

Capacity is taken from the instance catalogue rather than from ``status`` so that
the policy's arithmetic is identical in simulation and in the cluster.
"""

from __future__ import annotations

import uuid
from collections import Counter

from kubernetes import client, config

from spothedge.model.types import ClusterState, InstanceType, Plan, Pool

MANAGED_LABEL = "spothedge.io/managed"
POOL_LABEL = "spothedge.io/pool"
TYPE_LABEL = "node.kubernetes.io/instance-type"
DRAIN_ANNOTATION = "spothedge.io/delete-after"
PRICE_ANNOTATION = "spothedge.io/price-per-hour"
FAKE_LABEL = "kwok.x-k8s.io/node"


class KwokNodeActuator:
    def __init__(
        self,
        catalogue: dict[str, InstanceType],
        prices,
        namespace: str = "default",
        kube_context: str | None = None,
        in_cluster: bool = False,
    ) -> None:
        if in_cluster:
            config.load_incluster_config()
        else:
            config.load_kube_config(context=kube_context)
        self._api = client.CoreV1Api()
        self._catalogue = catalogue
        self._prices = prices
        self._namespace = namespace

    # ------------------------------------------------------------------ reading

    def _managed_nodes(self) -> list[client.V1Node]:
        result = self._api.list_node(label_selector=f"{MANAGED_LABEL}=true")
        # Nodes with a deletionTimestamp still appear in LIST but must not count
        # toward capacity, or the controller drains live nodes to compensate.
        return [n for n in result.items if n.metadata.deletion_timestamp is None]

    def current(self) -> ClusterState:
        counts: Counter[tuple[Pool, str]] = Counter()
        draining: list[str] = []
        for node in self._managed_nodes():
            labels = node.metadata.labels or {}
            annotations = node.metadata.annotations or {}
            pool = Pool(labels.get(POOL_LABEL, Pool.ON_DEMAND.value))
            instance_type = labels.get(TYPE_LABEL, "")
            if instance_type not in self._catalogue:
                continue
            if DRAIN_ANNOTATION in annotations:
                draining.append(node.metadata.name)
            # Draining nodes still exist and still count toward capacity until
            # they are reaped; excluding them makes the planner over-provision
            # against capacity that is already on its way out.
            counts[(pool, instance_type)] += 1
        return ClusterState(nodes=dict(counts), draining=tuple(draining))

    # ------------------------------------------------------------------ writing

    def _create_node(self, pool: Pool, instance_type: str) -> str:
        instance = self._catalogue[instance_type]
        name = f"{pool.value}-{instance_type.replace('.', '-')}-{uuid.uuid4().hex[:6]}"
        labels = {
            "kubernetes.io/hostname": name,
            "kubernetes.io/os": "linux",
            "kubernetes.io/arch": "amd64",
            FAKE_LABEL: "fake",
            MANAGED_LABEL: "true",
            POOL_LABEL: pool.value,
            TYPE_LABEL: instance_type,
        }
        annotations = {
            PRICE_ANNOTATION: f"{self._prices.usd_per_hour(pool, instance):.6f}",
        }
        taints = []
        if pool.is_spot:
            taints.append(
                client.V1Taint(key="spothedge.io/spot", value="true", effect="NoSchedule")
            )
        body = client.V1Node(
            metadata=client.V1ObjectMeta(name=name, labels=labels, annotations=annotations),
            spec=client.V1NodeSpec(taints=taints or None),
        )
        self._api.create_node(body)
        # KWOK defaults allocatable to 1m CPU; the scheduler needs the real shape.
        self._api.patch_node_status(
            name,
            {
                "status": {
                    "capacity": {
                        "cpu": str(instance.vcpu),
                        "memory": f"{max(4, instance.vcpu * 4)}Gi",
                        "pods": "110",
                    },
                    "allocatable": {
                        "cpu": f"{instance.allocatable_vcpu:.1f}",
                        "memory": f"{max(3, instance.vcpu * 4 - 1)}Gi",
                        "pods": "110",
                    },
                }
            },
        )
        return name

    def ensure(self, plan: Plan, now_seconds: float) -> dict[str, list[str]]:
        self.reap(now_seconds)
        nodes = self._managed_nodes()
        all_counts: Counter[tuple[Pool, str]] = Counter()
        active: dict[tuple[Pool, str], list[str]] = {}
        for node in nodes:
            labels = node.metadata.labels or {}
            annotations = node.metadata.annotations or {}
            instance_type = labels.get(TYPE_LABEL, "")
            if instance_type not in self._catalogue:
                continue
            pool = Pool(labels.get(POOL_LABEL, Pool.ON_DEMAND.value))
            key = (pool, instance_type)
            all_counts[key] += 1
            if DRAIN_ANNOTATION not in annotations:
                active.setdefault(key, []).append(node.metadata.name)

        desired = Counter({key: count for key, count in plan.nodes.items() if count > 0})
        launched: list[str] = []
        drained: list[str] = []

        for key in sorted(set(desired) | set(all_counts), key=lambda k: (k[0].value, k[1])):
            delta = desired.get(key, 0) - all_counts.get(key, 0)
            if delta > 0:
                pool, instance_type = key
                for _ in range(delta):
                    launched.append(self._create_node(pool, instance_type))
            elif delta < 0:
                # Draining nodes still count toward capacity until reaped, so a
                # surplus that is already draining must not be drained twice.
                surplus = -delta
                active_for_key = active.get(key, [])
                already_draining = all_counts.get(key, 0) - len(active_for_key)
                to_drain = max(0, surplus - already_draining)
                for name in active_for_key[:to_drain]:
                    self.drain(name, now_seconds + 20.0)
                    drained.append(name)
        return {"launched": launched, "drained": drained}

    def pending_reclaims(self, now_seconds: float) -> list[tuple[str, float, float]]:
        """Nodes with a notice that has not yet been drained: (name, vcpu, deadline)."""

        pending: list[tuple[str, float, float]] = []
        for node in self._managed_nodes():
            annotations = node.metadata.annotations or {}
            if DRAIN_ANNOTATION in annotations:
                continue
            raw = annotations.get("spothedge.io/interruption-deadline")
            if raw is None:
                continue
            instance_type = (node.metadata.labels or {}).get(TYPE_LABEL, "")
            instance = self._catalogue.get(instance_type)
            if instance is None:
                continue
            try:
                deadline = float(raw)
            except ValueError:
                continue
            pending.append((node.metadata.name, instance.allocatable_vcpu, deadline))
        return pending

    def drain(self, node_name: str, delete_after_seconds: float) -> None:
        body = {
            "metadata": {
                "annotations": {DRAIN_ANNOTATION: f"{delete_after_seconds:.0f}"},
                "labels": {"spothedge.io/draining": "true"},
            }
        }
        self._api.patch_node(node_name, body)

    def reap(self, now_seconds: float) -> list[str]:
        deleted: list[str] = []
        for node in self._managed_nodes():
            annotations = node.metadata.annotations or {}
            deadline = annotations.get(DRAIN_ANNOTATION)
            if deadline is None:
                continue
            try:
                due = float(deadline)
            except ValueError:
                continue
            if due <= now_seconds:
                try:
                    self._api.delete_node(node.metadata.name)
                    deleted.append(node.metadata.name)
                except client.exceptions.ApiException:
                    pass
        return deleted
