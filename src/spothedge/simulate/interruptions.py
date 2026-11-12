"""Spot reclaim models I1-I4 from the experiment protocol.

All models are seeded and policy-independent: the same seed produces the same
events for every policy (common random numbers), which is what makes the paired
comparison statistically meaningful.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from spothedge.model.types import Interruption
from spothedge.simulate.nodes import SimNode


@dataclass(frozen=True, slots=True)
class InterruptionConfig:
    """Parameters of the four interruption models."""

    model: str = "independent"  # independent | correlated | peak | none
    hazard_per_node_hour: float = 0.04
    correlated_prob_per_hour: float = 0.02
    correlated_q: float = 1.0 / 3.0
    peak_only: bool = False
    peak_threshold_vcpu: float = 130.0
    abrupt_fraction: float = 0.0
    notice_seconds: int = 120

    def __post_init__(self) -> None:
        if self.model not in {"independent", "correlated", "peak", "none"}:
            raise ValueError(f"unknown interruption model {self.model!r}")
        if not 0 <= self.correlated_q <= 1:
            raise ValueError("q must be in [0, 1]")
        if not 0 <= self.abrupt_fraction <= 1:
            raise ValueError("abrupt fraction must be in [0, 1]")


class InterruptionModel:
    def __init__(self, config: InterruptionConfig, rng: random.Random) -> None:
        self.config = config
        self.rng = rng

    def _notice(self) -> int:
        if self.rng.random() < self.config.abrupt_fraction:
            return 0
        return self.config.notice_seconds

    def poll(
        self,
        t: float,
        dt: float,
        ready_spot_nodes: list[SimNode],
        demand_vcpu: float,
    ) -> list[Interruption]:
        if self.config.model == "none" or not ready_spot_nodes:
            return []

        events: list[Interruption] = []

        if self.config.model == "independent":
            probability = 1.0 - math.exp(-self.config.hazard_per_node_hour * dt / 3600.0)
            for node in ready_spot_nodes:
                if self.rng.random() < probability:
                    events.append(
                        Interruption(
                            node=node.node_id,
                            pool=node.pool,
                            notice_seconds=self._notice(),
                        )
                    )
            return events

        if self.config.peak_only and demand_vcpu < self.config.peak_threshold_vcpu:
            return []

        probability = 1.0 - math.exp(-self.config.correlated_prob_per_hour * dt / 3600.0)
        if self.rng.random() >= probability:
            return []

        target = sum(n.allocatable_vcpu for n in ready_spot_nodes) * self.config.correlated_q
        lost = 0.0
        # Shuffle so the loss is spread across pools rather than always pool A.
        shuffled = list(ready_spot_nodes)
        self.rng.shuffle(shuffled)
        notice = self._notice()
        for node in shuffled:
            if lost >= target:
                break
            events.append(
                Interruption(node=node.node_id, pool=node.pool, notice_seconds=notice)
            )
            lost += node.allocatable_vcpu
        return events
