"""Actuator boundary: what the policy is allowed to change.

The policy returns a ``Plan``; an actuator turns it into nodes. Three
implementations exist: in-memory (tests), KWOK nodes (T2), and a stub for
Karpenter NodeClaims (documented, not the default). The policy is identical in
all three.
"""

from __future__ import annotations

from typing import Protocol

from spothedge.model.types import ClusterState, Plan


class Actuator(Protocol):
    def current(self) -> ClusterState: ...

    def ensure(self, plan: Plan, now_seconds: float) -> dict[str, list[str]]: ...

    def drain(self, node_name: str, delete_after_seconds: float) -> None: ...

    def reap(self, now_seconds: float) -> list[str]: ...
