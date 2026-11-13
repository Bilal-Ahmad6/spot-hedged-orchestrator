"""Drain test: does a node drain lose requests?

Runs the load generator, drains one node in the middle, and reports the failed
request count from the load generator. With a graceful drain (30 s notice,
preStop hook, readiness gate, PDB) the expected result is **zero**. With
``--abrupt`` the pod is deleted with no grace period, which is the 0 s-notice
case and should show non-zero loss.

Usage:
    python scripts/drain_test.py --node <name> --seconds 90
    python scripts/drain_test.py --node <name> --seconds 60 --abrupt
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def kubectl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", *args], capture_output=True, text=True)


def pick_node(pool: str) -> str:
    result = kubectl("get", "nodes", "-l", f"spothedge.io/pool={pool}", "-o", "name")
    names = [line.replace("node/", "") for line in result.stdout.splitlines() if line]
    if not names:
        raise SystemExit(f"no nodes in pool {pool}")
    return names[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", default=None)
    parser.add_argument("--pool", default="spot-a")
    parser.add_argument("--seconds", type=float, default=90.0)
    parser.add_argument("--drain-at", type=float, default=25.0)
    parser.add_argument("--rps", type=float, default=50.0)
    parser.add_argument("--url", default="http://localhost:8080/work")
    parser.add_argument("--abrupt", action="store_true")
    parser.add_argument("--out", default="experiments/results/drain_test.json")
    args = parser.parse_args()

    node = args.node or pick_node(args.pool)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"load {args.rps} rps for {args.seconds:.0f}s; drain {node} at t={args.drain_at:.0f}s")
    load = subprocess.Popen(
        [
            sys.executable,
            "scripts/loadtest.py",
            "--url",
            args.url,
            "--rps",
            str(args.rps),
            "--seconds",
            str(args.seconds),
            "--out",
            str(out),
        ]
    )

    time.sleep(args.drain_at)
    started = time.time()
    if args.abrupt:
        pods = kubectl(
            "get", "pods", "-l", "app=checkout", "--field-selector", f"spec.nodeName={node}",
            "-o", "name",
        ).stdout.split()
        for pod in pods:
            kubectl("delete", pod, "--grace-period=0", "--force")
        action = "abrupt delete"
    else:
        kubectl("cordon", node)
        result = kubectl(
            "drain",
            node,
            "--ignore-daemonsets",
            "--delete-emptydir-data",
            "--timeout=120s",
        )
        action = "graceful drain"
        if result.returncode != 0:
            print(result.stderr.strip())

    drain_seconds = time.time() - started
    load.wait()

    summary = json.loads(out.read_text(encoding="utf-8"))
    summary.update(
        {
            "node": node,
            "action": action,
            "drain_seconds": round(drain_seconds, 2),
            "abrupt": args.abrupt,
        }
    )
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(
        f"{action} took {drain_seconds:.1f}s | requests {summary['requests']} "
        f"| failures {summary['failures']} | p95 {summary['latency_ms']['p95']} ms"
    )
    if not args.abrupt:
        kubectl("uncordon", node)
    return 0 if summary["failures"] == 0 or args.abrupt else 1


if __name__ == "__main__":
    raise SystemExit(main())
