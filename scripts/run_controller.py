"""Run the controller loop without kopf.

Used for the T2 demo and for local experiments: it drives the exact same
``ControllerRuntime`` that the kopf operator wraps, against whatever kubeconfig is
current. The kopf path is the deployment path; this is the "run it now" path.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from spothedge.actuator.kwok import KwokNodeActuator
from spothedge.config import load_config
from spothedge.controller.runtime import ControllerRuntime, TraceReplaySource, build_policy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--trace", default="experiments/traces/demand_30d.csv")
    parser.add_argument("--policy", default="p3")
    parser.add_argument("--time-scale", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--ticks", type=int, default=0, help="0 = run forever")
    parser.add_argument("--log", default="experiments/runs/controller/decisions.jsonl")
    parser.add_argument("--kube-context", default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    actuator = KwokNodeActuator(
        catalogue=config.catalogue(),
        prices=config.price_table(),
        kube_context=args.kube_context,
    )
    runtime = ControllerRuntime(
        config=config,
        policy=build_policy(args.policy),
        actuator=actuator,
        source=TraceReplaySource(Path(args.trace), time_scale=args.time_scale),
        log_path=Path(args.log),
    )

    ticks = 0
    while True:
        record = runtime.tick(time.time())
        capacity = sum(record["inputs"]["capacityByPool"].values())
        print(
            f"tick {record['tick']:4d} | demand {record['inputs']['demandVcpu']:6.1f} "
            f"| capacity {capacity:6.1f} | nodes {sum(record['plan']['nodes'].values()):3d} "
            f"| launched {len(record['action']['launched']):2d} "
            f"| drained {len(record['action']['drained']):2d}",
            flush=True,
        )
        ticks += 1
        if args.ticks and ticks >= args.ticks:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
