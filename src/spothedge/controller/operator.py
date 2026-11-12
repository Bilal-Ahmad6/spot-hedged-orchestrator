"""kopf operator wiring.

Runs outside the cluster for the demo (a kubeconfig is enough) or inside it as a
Deployment. The timer handler is a thin wrapper around ``ControllerRuntime.tick``
so the logic is testable without Kubernetes.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import kopf

from spothedge.actuator.kwok import KwokNodeActuator
from spothedge.config import load_config
from spothedge.controller.runtime import ControllerRuntime, TraceReplaySource, build_policy

RUNTIME: ControllerRuntime | None = None


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@kopf.on.startup()
def startup(**kwargs) -> None:
    global RUNTIME
    config_path = Path(_env("SPOTHEDGE_CONFIG", "configs/base.yaml"))
    trace_path = Path(_env("SPOTHEDGE_TRACE", "experiments/traces/demand_30d.csv"))
    log_path = Path(
        _env("SPOTHEDGE_DECISIONS", "experiments/runs/controller/decisions.jsonl")
    )
    policy_name = _env("SPOTHEDGE_POLICY", "p3")
    time_scale = float(_env("SPOTHEDGE_TIME_SCALE", "60"))

    config = load_config(config_path)
    actuator = KwokNodeActuator(
        catalogue=config.catalogue(),
        prices=config.price_table(),
        kube_context=os.environ.get("SPOTHEDGE_KUBE_CONTEXT"),
    )
    RUNTIME = ControllerRuntime(
        config=config,
        policy=build_policy(policy_name),
        actuator=actuator,
        source=TraceReplaySource(trace_path, time_scale=time_scale),
        log_path=log_path,
    )
    logging.getLogger(__name__).info("spothedge controller started (policy=%s)", policy_name)

@kopf.timer(
    "spothedge.io",
    "v1alpha1",
    "hedgedservices",
    interval=float(os.environ.get("SPOTHEDGE_TICK_SECONDS", "60")),
    initial_delay=5.0,
)
def tick(spec, status, patch, **kwargs) -> None:
    if RUNTIME is None:
        raise kopf.TemporaryError("runtime not initialised", delay=5)

    record = RUNTIME.tick(time.time())
    patch.status.update(
        {
            "lastDecisionId": record["decisionId"],
            "tick": record["tick"],
            "demandVcpu": record["inputs"]["demandVcpu"],
            "capacityVcpu": round(
                sum(record["inputs"]["capacityByPool"].values()), 3
            ),
            "plan": record["plan"]["nodes"],
            "predictedCostPerHour": record["plan"]["predictedCostPerHour"],
        }
    )


if __name__ == "__main__":
    kopf.run()
