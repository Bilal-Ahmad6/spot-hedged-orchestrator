"""Queueing and SLO model.

A 30-day run at 1-minute resolution is ~43,200 buckets; simulating individual
requests is not viable (hundreds of millions). Instead each bucket is evaluated
analytically:

* utilisation ``rho = offered_load / capacity``;
* waiting time from Erlang-C, corrected for general service times with the
  Allen-Cunneen factor ``(Ca^2 + Cs^2) / 2``;
* p95 from the exponential tail of the waiting-time distribution.

The model is intentionally conservative at saturation, and it is calibrated
against the real-cluster measurements in T3. Its job is to rank policies
correctly and to count violation minutes, not to predict milliseconds exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkloadModel:
    """Service characteristics used to turn vCPU demand into a latency."""

    service_time_s: float = 0.05
    service_cv: float = 1.2
    arrival_cv: float = 1.0
    requests_per_vcpu_second: float = 20.0

    def __post_init__(self) -> None:
        if self.service_time_s <= 0:
            raise ValueError("service time must be positive")
        if self.requests_per_vcpu_second <= 0:
            raise ValueError("request rate per vcpu must be positive")


def erlang_c(servers: int, offered_load: float) -> float:
    """Probability that an arriving request must wait (Erlang-C).

    Uses the numerically stable Erlang-B recursion, which avoids factorials for
    the 100-200 server counts this project operates at.
    """

    if servers <= 0:
        return 1.0
    if offered_load <= 0:
        return 0.0
    if offered_load >= servers:
        return 1.0

    erlang_b = 0.0
    for k in range(1, servers + 1):
        erlang_b = (offered_load * erlang_b) / (k + offered_load * erlang_b)
    rho = offered_load / servers
    return erlang_b / (1.0 - rho * (1.0 - erlang_b))


def p95_latency_ms(
    demand_vcpu: float,
    capacity_vcpu: float,
    pod_cpu_vcpu: float,
    workload: WorkloadModel,
) -> float:
    """p95 response time in milliseconds, or ``inf`` when the system is unstable."""

    if demand_vcpu <= 0:
        return workload.service_time_s * 1000.0
    if capacity_vcpu <= 0:
        return math.inf

    servers = max(1, int(capacity_vcpu // pod_cpu_vcpu))
    rho = demand_vcpu / capacity_vcpu
    if rho >= 1.0:
        return math.inf

    service_ms = workload.service_time_s * 1000.0
    offered_load = rho * servers
    wait_probability = erlang_c(servers, offered_load)

    # Mean wait in M/M/c, then Allen-Cunneen correction for G/G/c.
    mean_wait_s = wait_probability * workload.service_time_s / (servers * (1.0 - rho))
    correction = (workload.arrival_cv**2 + workload.service_cv**2) / 2.0
    mean_wait_s *= correction

    # Exponential tail: P(W > t) = C * exp(-(c*mu - lambda) * t).
    arrival_rate = demand_vcpu * workload.requests_per_vcpu_second / pod_cpu_vcpu
    service_rate = 1.0 / workload.service_time_s
    decay = servers * service_rate - arrival_rate
    if decay <= 0:
        return math.inf
    tail_wait_s = math.log(max(wait_probability, 1e-12) / 0.05) / decay
    tail_wait_s = max(tail_wait_s, 0.0) * correction

    return service_ms + max(mean_wait_s, tail_wait_s) * 1000.0


def served_fraction(demand_vcpu: float, capacity_vcpu: float) -> float:
    """Fraction of offered demand that can be served with the available capacity."""

    if demand_vcpu <= 0:
        return 1.0
    if capacity_vcpu <= 0:
        return 0.0
    return min(1.0, capacity_vcpu / demand_vcpu)


def lost_in_flight(
    demand_vcpu: float,
    pods_lost: int,
    capacity_vcpu: float,
    pod_cpu_vcpu: float,
    workload: WorkloadModel,
) -> float:
    """Little's law: requests in flight per replica times the replicas lost."""

    if pods_lost <= 0 or capacity_vcpu <= 0 or demand_vcpu <= 0:
        return 0.0
    pods = max(1.0, capacity_vcpu / pod_cpu_vcpu)
    requests_in_flight_per_pod = (
        demand_vcpu / pods * workload.requests_per_vcpu_second * workload.service_time_s
    )
    return pods_lost * requests_in_flight_per_pod
