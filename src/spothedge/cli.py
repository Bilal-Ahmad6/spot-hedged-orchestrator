"""Command line entry point.

Every operational task is reachable from here so that CI, the Makefile and a
human on Windows all run the same code path.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import subprocess
import sys
from pathlib import Path

from spothedge import __version__
from spothedge.config import load_config

CORE_DEPENDENCIES = ("simpy", "pulp", "numpy", "pandas", "yaml", "jsonschema", "matplotlib")
OPTIONAL_DEPENDENCIES = ("kubernetes", "kopf")


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _dependency_report() -> dict[str, bool]:
    report = {name: importlib.util.find_spec(name) is not None for name in CORE_DEPENDENCIES}
    report.update(
        {name: importlib.util.find_spec(name) is not None for name in OPTIONAL_DEPENDENCIES}
    )
    return report


def cmd_doctor(args: argparse.Namespace) -> int:
    deps = _dependency_report()
    missing_core = [name for name in CORE_DEPENDENCIES if not deps[name]]
    config_path = Path(args.config)
    config_ok: bool | None = None
    config_error: str | None = None
    if config_path.exists():
        try:
            load_config(config_path)
            config_ok = True
        except Exception as exc:  # noqa: BLE001 - doctor must report, not crash
            config_ok = False
            config_error = str(exc)

    payload = {
        "version": __version__,
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "git_sha": _git_sha(),
        "dependencies": deps,
        "missing_core": missing_core,
        "config": {"path": str(config_path), "ok": config_ok, "error": config_error},
        "data": {
            "demand_csv": Path("experiments/traces/demand_30d.csv").exists(),
            "prices": Path("prices/base.yaml").exists(),
        },
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"spothedge {payload['version']}  ({payload['git_sha']})")
        print(f"python   {payload['python']}  {payload['executable']}")
        print(f"platform {payload['platform']}")
        print(f"config   {config_path} -> {'ok' if config_ok else config_error or 'missing'}")
        print("deps     " + "  ".join(f"{k}={'ok' if v else 'MISSING'}" for k, v in deps.items()))
        print(
            "data     demand_csv="
            f"{'present' if payload['data']['demand_csv'] else 'missing'}  "
            f"prices={'present' if payload['data']['prices'] else 'missing'}"
        )
        if missing_core:
            print("ERROR: missing core dependencies; run `pip install -e '.[dev]'`")

    return 1 if missing_core else 0


def cmd_prices(args: argparse.Namespace) -> int:
    from spothedge.prices import fetch_prices, write_price_file

    if args.action == "fetch":
        anchors = fetch_prices(region=args.region)
        out = Path(args.out)
        write_price_file(anchors, out, base_on_demand=args.on_demand)
        print(f"wrote {out} ({len(anchors['items'])} anchor meters)")
        return 0
    raise SystemExit("unknown prices action")


def cmd_trace(args: argparse.Namespace) -> int:
    from spothedge.trace import build_trace

    if args.action != "build":
        raise SystemExit("unknown trace action")
    summary = build_trace(
        source=Path(args.source) if args.source else None,
        out=Path(args.out),
        seed=args.seed,
        days=args.days,
        min_vcpu=args.min_vcpu,
        max_vcpu=args.max_vcpu,
        smooth_minutes=args.smooth_minutes,
    )
    print(json.dumps(summary, indent=2))
    return 0


def cmd_sim(args: argparse.Namespace) -> int:
    from spothedge.simulate.runner import run_comparison, run_from_config

    if args.action == "compare":
        payload = run_comparison(
            Path(args.config),
            out_dir=Path(args.out),
            policies=args.policies.split(","),
            seeds=list(range(1, args.seeds + 1)),
            discount=args.discount,
            interruption_model=args.interruption,
            q=args.q,
            notice_seconds=args.notice,
            days=args.days,
        )
        print(json.dumps(payload["aggregate"], indent=2))
        if payload.get("paired"):
            print(json.dumps(payload["paired"], indent=2))
        return 0

    if args.action != "run":
        raise SystemExit("unknown sim action")
    summary = run_from_config(
        Path(args.config),
        out_dir=Path(args.out),
        policy=args.policy,
        interruption_model=args.interruption,
        q=args.q,
        notice_seconds=args.notice,
        abrupt_fraction=args.abrupt,
        seed=args.seed,
        days=args.days,
        record_every=args.record_every,
    )
    print(json.dumps(summary, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from spothedge.verify import verify

    return verify(Path(args.runs), Path(args.expected))


def cmd_report(args: argparse.Namespace) -> int:
    from spothedge.report import build_report

    return build_report(Path(args.runs), Path(args.out))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spothedge",
        description="Spot-hedged elastic orchestrator: simulation, policy and controller.",
    )
    parser.add_argument("--version", action="version", version=f"spothedge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check environment, config and data")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--config", default="configs/base.yaml")
    doctor.set_defaults(func=cmd_doctor)

    prices = sub.add_parser("prices", help="price table utilities")
    prices.add_argument("action", choices=["fetch"])
    prices.add_argument("--region", default="eastus")
    prices.add_argument("--on-demand", type=float, default=0.04)
    prices.add_argument("--out", default="prices/anchors.json")
    prices.set_defaults(func=cmd_prices)

    trace = sub.add_parser("trace", help="demand trace construction")
    trace.add_argument("action", choices=["build"])
    trace.add_argument("--source", default=None, help="raw trace archive (optional)")
    trace.add_argument("--out", default="experiments/traces/demand_30d.csv")
    trace.add_argument("--seed", type=int, default=7)
    trace.add_argument("--days", type=int, default=30)
    trace.add_argument("--min-vcpu", type=float, default=40.0)
    trace.add_argument("--max-vcpu", type=float, default=160.0)
    trace.add_argument("--smooth-minutes", type=int, default=15)
    trace.set_defaults(func=cmd_trace)

    sim = sub.add_parser("sim", help="discrete-event simulator")
    sim.add_argument("action", choices=["run", "compare"])
    sim.add_argument("--config", default="configs/base.yaml")
    sim.add_argument("--out", default="experiments/runs/smoke")
    sim.add_argument("--policy", default="p0", help="p0 | p1 | p2 | p3")
    sim.add_argument("--policies", default="p1,p3", help="comma-separated, for compare")
    sim.add_argument("--seeds", type=int, default=20, help="number of paired seeds, for compare")
    sim.add_argument("--discount", type=float, default=None, help="spot discount override")
    sim.add_argument(
        "--interruption",
        default="independent",
        choices=["independent", "correlated", "peak", "none"],
    )
    sim.add_argument("--q", type=float, default=None, help="simultaneous spot loss fraction")
    sim.add_argument("--notice", type=int, default=None, help="notice window in seconds")
    sim.add_argument(
        "--abrupt", type=float, default=0.0, help="fraction of reclaims with 0s notice"
    )
    sim.add_argument("--seed", type=int, default=None)
    sim.add_argument("--days", type=int, default=None)
    sim.add_argument(
        "--record-every", type=int, default=0, help="write one decision record every N ticks"
    )
    sim.set_defaults(func=cmd_sim)

    verify = sub.add_parser("verify", help="re-run fixed cells and diff results")
    verify.add_argument("--runs", default="experiments/runs")
    verify.add_argument("--expected", default="experiments/expected")
    verify.set_defaults(func=cmd_verify)

    report = sub.add_parser("report", help="build figures and report artifacts")
    report.add_argument("--runs", default="experiments/runs")
    report.add_argument("--out", default="report")
    report.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
