"""Inject a spot reclaim notice into the cluster.

Usage:
    python scripts/inject_reclaim.py --pool spot-a --notice 120
    python scripts/inject_reclaim.py --node spot-a-... --abrupt

The controller watches ``spothedge.io/interruption-deadline`` (epoch seconds) and
provisions a replacement before draining. ``--abrupt`` deletes the node instead,
which models a missed notice.
"""

from __future__ import annotations

import argparse
import time

from kubernetes import client, config

DEADLINE = "spothedge.io/interruption-deadline"
MANAGED = "spothedge.io/managed"
POOL = "spothedge.io/pool"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", default="spot-a")
    parser.add_argument("--node", default=None)
    parser.add_argument("--notice", type=int, default=120)
    parser.add_argument("--abrupt", action="store_true")
    parser.add_argument("--context", default=None)
    args = parser.parse_args()

    config.load_kube_config(context=args.context)
    api = client.CoreV1Api()

    if args.node:
        name = args.node
    else:
        nodes = api.list_node(label_selector=f"{MANAGED}=true,{POOL}={args.pool}").items
        if not nodes:
            raise SystemExit(f"no managed nodes in pool {args.pool}")
        name = nodes[0].metadata.name

    if args.abrupt:
        api.delete_node(name)
        print(f"deleted {name} abruptly (no notice)")
        return 0

    deadline = time.time() + args.notice
    api.patch_node(
        name,
        {
            "metadata": {
                "annotations": {DEADLINE: f"{deadline:.0f}"},
            }
        },
    )
    print(f"{name}: interruption notice, {args.notice}s window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
