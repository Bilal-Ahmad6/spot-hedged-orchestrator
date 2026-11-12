"""Configuration loading and validation.

One YAML file drives a simulator run today and a controller deployment later, so
that a result can never come from parameters that are not written down.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from spothedge.model.types import InstanceType, PriceTable


@dataclass(frozen=True, slots=True)
class SloConfig:
    p95_latency_ms: float = 150.0
    min_availability: float = 0.999
    window_seconds: int = 60

    def __post_init__(self) -> None:
        if self.p95_latency_ms <= 0:
            raise ValueError("p95 latency threshold must be positive")
        if not 0 < self.min_availability <= 1:
            raise ValueError("availability target must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class CapacityConfig:
    pod_cpu_request_milli: int = 500
    system_overhead_vcpu: float = 0.3
    max_pods_per_node: int = 16

    def __post_init__(self) -> None:
        if self.pod_cpu_request_milli <= 0:
            raise ValueError("pod cpu request must be positive")
        if self.max_pods_per_node <= 0:
            raise ValueError("max pods per node must be positive")

    @property
    def pod_cpu_vcpu(self) -> float:
        return self.pod_cpu_request_milli / 1000.0


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    tick_seconds: int = 60
    horizon_seconds: int = 1800
    headroom_h: float = 0.15
    loss_fraction_q: float = 1.0 / 3.0
    on_demand_floor_vcpu: float = 8.0
    on_demand_floor_fraction: float = 0.25
    diversity_beta: float = 0.65
    drain_headroom_vcpu: float = 8.0
    lead_time_seconds: int = 90
    drain_seconds: int = 20
    notice_seconds: int = 120
    churn_penalty_per_node: float = 0.02
    max_spot_share: float = 0.85
    max_nodes: int = 120
    shape_vcpu: int = 4

    def __post_init__(self) -> None:
        if self.tick_seconds <= 0:
            raise ValueError("tick must be positive")
        if self.horizon_seconds < self.tick_seconds:
            raise ValueError("horizon must be at least one tick")
        if self.headroom_h < 0:
            raise ValueError("headroom cannot be negative")
        if not 0 <= self.on_demand_floor_fraction <= 1:
            raise ValueError("floor fraction must be in [0, 1]")
        if not 0 < self.loss_fraction_q <= 1:
            raise ValueError("q must be in (0, 1]")
        if not 0.5 <= self.diversity_beta <= 1:
            raise ValueError("diversity beta must be in [0.5, 1]")
        if not 0 < self.max_spot_share <= 1:
            raise ValueError("max spot share must be in (0, 1]")
        if self.lead_time_seconds < 0:
            raise ValueError("lead time cannot be negative")
        if self.drain_seconds < 0:
            raise ValueError("drain time cannot be negative")
        if self.notice_seconds < 0:
            raise ValueError("notice window cannot be negative")
        if self.max_nodes <= 0:
            raise ValueError("max nodes must be positive")


@dataclass(frozen=True, slots=True)
class PriceConfig:
    on_demand_usd_per_vcpu_hour: float = 0.04
    spot_discount: float = 0.65
    volatile: bool = False

    def table(self) -> PriceTable:
        return PriceTable(
            on_demand_usd_per_vcpu_hour=self.on_demand_usd_per_vcpu_hour,
            spot_discount=self.spot_discount,
        )


@dataclass(frozen=True, slots=True)
class WorkloadConfig:
    demand_csv: str = "experiments/traces/demand_30d.csv"
    seed: int = 7
    service_time_s: float = 0.046
    service_cv: float = 1.2
    requests_per_vcpu_second: float = 20.0

    def __post_init__(self) -> None:
        if self.service_time_s <= 0:
            raise ValueError("service time must be positive")
        if self.service_cv <= 0:
            raise ValueError("service cv must be positive")
        if self.requests_per_vcpu_second <= 0:
            raise ValueError("request rate must be positive")


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    horizon_days: int = 30
    tick_seconds: int = 60


@dataclass(frozen=True, slots=True)
class Config:
    slo: SloConfig
    capacity: CapacityConfig
    policy: PolicyConfig
    price: PriceConfig
    workload: WorkloadConfig
    experiment: ExperimentConfig
    instances: tuple[InstanceType, ...]

    def catalogue(self) -> dict[str, InstanceType]:
        return {instance.name: instance for instance in self.instances}

    def price_table(self) -> PriceTable:
        return self.price.table()

    @property
    def pod_cpu_vcpu(self) -> float:
        return self.capacity.pod_cpu_vcpu


DEFAULT_INSTANCES: tuple[InstanceType, ...] = (
    InstanceType(name="c6i.large", vcpu=2, system_overhead_vcpu=0.3),
    InstanceType(name="c6i.xlarge", vcpu=4, system_overhead_vcpu=0.3),
    InstanceType(name="c6i.2xlarge", vcpu=8, system_overhead_vcpu=0.3),
    InstanceType(name="c6i.4xlarge", vcpu=16, system_overhead_vcpu=0.3),
)


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"config section {name!r} must be a mapping")
    return value


_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _snake(key: str) -> str:
    """p95LatencyMs -> p95_latency_ms, demandCsv -> demand_csv."""
    return _CAMEL_BOUNDARY.sub("_", key).lower()


def _build(cls: type, values: dict[str, Any], section: str):
    """Instantiate a config dataclass from camelCase YAML keys.

    Unknown keys are rejected: a typo in a config file must not silently fall
    back to a default, because that would make two "identical" runs differ.
    """

    normalized = {_snake(key): value for key, value in values.items()}
    if len(normalized) != len(values):
        raise ValueError(
            f"duplicate keys in {section!r} after normalisation: {sorted(values)}"
        )
    allowed = {f for f in cls.__dataclass_fields__}
    unknown = set(normalized) - allowed
    if unknown:
        raise ValueError(f"unknown keys in {section!r}: {sorted(unknown)}")
    return cls(**normalized)


def parse_config(data: dict[str, Any]) -> Config:
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")

    instances = tuple(
        InstanceType(
            name=item["name"],
            vcpu=int(item["vcpu"]),
            system_overhead_vcpu=float(item.get("system_overhead_vcpu", 0.3)),
            memory_gib=float(item.get("memory_gib", 0.0)),
        )
        for item in data.get("instances", [])
    ) or DEFAULT_INSTANCES

    names = [i.name for i in instances]
    if len(names) != len(set(names)):
        raise ValueError("duplicate instance type names")

    return Config(
        slo=_build(SloConfig, _section(data, "slo"), "slo"),
        capacity=_build(CapacityConfig, _section(data, "capacity"), "capacity"),
        policy=_build(PolicyConfig, _section(data, "policy"), "policy"),
        price=_build(PriceConfig, _section(data, "price"), "price"),
        workload=_build(WorkloadConfig, _section(data, "workload"), "workload"),
        experiment=_build(ExperimentConfig, _section(data, "experiment"), "experiment"),
        instances=instances,
    )


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return parse_config(data)
