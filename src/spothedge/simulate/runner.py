"""Run orchestration: config + trace + policy -> artifacts on disk."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from spothedge import __version__
from spothedge.config import Config, load_config
from spothedge.policy.baselines import build_baseline
from spothedge.simulate.engine import Simulation, SimulationResult
from spothedge.simulate.interruptions import InterruptionConfig


def load_demand(path: Path, days: int | None = None) -> np.ndarray:
    frame = pd.read_csv(path)
    if "demand_vcpu" not in frame.columns:
        raise ValueError(f"{path}: missing 'demand_vcpu' column")
    values = frame["demand_vcpu"].to_numpy(dtype=float)
    if days is not None:
        values = values[: days * 1440]
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{path}: demand contains non-finite values")
    return values


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def build_policy(name: str, config: Config):
    key = name.lower()
    if key in {"p3", "hedge", "hedged"}:
        from spothedge.policy.hedged import HedgedPolicy

        return HedgedPolicy()
    return build_baseline(key)


def simulate(
    config: Config,
    demand: np.ndarray,
    policy_name: str = "p0",
    interruptions: InterruptionConfig | None = None,
    seed: int | None = None,
    record_every: int = 0,
) -> tuple[SimulationResult, Simulation]:
    policy = build_policy(policy_name, config)
    simulation = Simulation(
        config=config,
        policy=policy,
        demand=demand,
        interruptions=interruptions or InterruptionConfig(),
        seed=seed,
        record_every=record_every,
    )
    result = simulation.run()
    return result, simulation


def run_from_config(
    config_path: Path,
    out_dir: Path,
    policy: str = "p0",
    interruption_model: str = "independent",
    q: float | None = None,
    notice_seconds: int | None = None,
    abrupt_fraction: float = 0.0,
    seed: int | None = None,
    days: int | None = None,
    record_every: int = 0,
) -> dict:
    started = time.perf_counter()
    config = load_config(config_path)
    demand_path = Path(config.workload.demand_csv)
    demand = load_demand(demand_path, days=days)

    interruptions = InterruptionConfig(
        model=interruption_model,
        correlated_q=config.policy.loss_fraction_q if q is None else q,
        notice_seconds=config.policy.notice_seconds if notice_seconds is None else notice_seconds,  # type: ignore[attr-defined]
        abrupt_fraction=abrupt_fraction,
    )

    result, simulation = simulate(
        config,
        demand,
        policy_name=policy,
        interruptions=interruptions,
        seed=seed if seed is not None else config.workload.seed,
        record_every=record_every,
    )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = _summary_payload(
        result,
        simulation,
        config,
        config_path,
        demand_path,
        demand,
        interruptions,
        started,
    )
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "config.resolved.yaml").write_text(
        json.dumps(asdict(config), indent=2), encoding="utf-8"
    )
    (out_dir / "env.txt").write_text(_env_text(), encoding="utf-8")

    if record_every and simulation.records:
        with gzip.open(out_dir / "decisions.jsonl.gz", "wt", encoding="utf-8") as handle:
            for record in simulation.records:
                handle.write(json.dumps(record) + "\n")

    return summary


def _env_text() -> str:
    return "\n".join(
        [
            f"spothedge {__version__}",
            f"git {git_sha()}",
            f"python {platform.python_version()}",
            f"platform {platform.platform()}",
            f"numpy {np.__version__}",
            f"pandas {pd.__version__}",
            f"executable {sys.executable}",
        ]
    )


def _summary_payload(
    result,
    simulation,
    config,
    config_path: Path,
    demand_path: Path,
    demand: np.ndarray,
    interruptions: InterruptionConfig,
    started: float,
) -> dict:
    summary = result.to_dict()
    summary.update(
        {
            "policy": result.policy,
            "wall_seconds": round(time.perf_counter() - started, 3),
            "ticks": int(len(demand) * 60 / config.experiment.tick_seconds),
            "demand": {
                "path": str(demand_path),
                "sha256": sha256_file(demand_path) if demand_path.exists() else None,
                "rows": int(len(demand)),
                "mean": float(np.mean(demand)),
                "max": float(np.max(demand)),
            },
            "interruptions": asdict(interruptions),
            "price": asdict(config.price),
            "policy_config": asdict(config.policy),
            "config": {
                "path": str(config_path),
                "sha256": sha256_file(Path(config_path)),
            },
        }
    )
    return summary


def _mean_ci(values: list[float]) -> dict:
    if not values:
        return {"mean": None, "ci95": None}
    array = np.asarray(values, dtype=float)
    mean = float(np.mean(array))
    if len(array) < 2:
        return {"mean": mean, "ci95": None}
    half = 1.96 * float(np.std(array, ddof=1)) / math.sqrt(len(array))
    return {"mean": mean, "ci95": half}


def run_comparison(
    config_path: Path,
    out_dir: Path,
    policies: list[str],
    seeds: list[int],
    discount: float | None = None,
    interruption_model: str = "independent",
    q: float | None = None,
    notice_seconds: int | None = None,
    days: int | None = None,
) -> dict:
    """Run policies on paired seeds and aggregate the primary endpoints."""

    config = load_config(config_path)
    demand_path = Path(config.workload.demand_csv)
    demand = load_demand(demand_path, days=days)
    base_price = config.price
    if discount is not None:
        config = replace(config, price=replace(base_price, spot_discount=discount))

    interruption_config = InterruptionConfig(
        model=interruption_model,
        correlated_q=config.policy.loss_fraction_q if q is None else q,
        notice_seconds=config.policy.notice_seconds if notice_seconds is None else notice_seconds,
    )

    rows: list[dict] = []
    for seed in seeds:
        for policy in policies:
            result, _ = simulate(
                config,
                demand,
                policy_name=policy,
                interruptions=interruption_config,
                seed=seed,
            )
            row = result.to_dict()
            row["seed"] = seed
            row["policy_key"] = policy
            rows.append(row)

    by_policy: dict[str, dict] = {}
    for policy in policies:
        subset = [row for row in rows if row["policy_key"] == policy]
        by_policy[policy] = {
            "cost_usd": _mean_ci([r["cost_usd"] for r in subset]),
            "availability": _mean_ci([r["availability"] for r in subset]),
            "violation_seconds": _mean_ci([r["violation_seconds"] for r in subset]),
            "lost_in_flight": _mean_ci([r["lost_in_flight"] for r in subset]),
            "node_launches": _mean_ci([r["node_launches"] for r in subset]),
            "mean_capacity_vcpu": _mean_ci([r["mean_capacity_vcpu"] for r in subset]),
        }

    paired: dict[str, dict] = {}
    if len(policies) == 2:
        left, right = policies
        diffs = []
        for seed in seeds:
            a = next(r for r in rows if r["seed"] == seed and r["policy_key"] == left)
            b = next(r for r in rows if r["seed"] == seed and r["policy_key"] == right)
            diffs.append((b["cost_usd"] - a["cost_usd"]) / a["cost_usd"])
        paired["cost_reduction"] = _mean_ci([-d for d in diffs])

    payload = {
        "config": str(config_path),
        "policies": policies,
        "seeds": seeds,
        "discount": config.price.spot_discount,
        "interruptions": asdict(interruption_config),
        "aggregate": by_policy,
        "paired": paired,
        "rows": rows,
        "wall_seconds": round(sum(r.get("wall_seconds", 0) for r in rows), 2),
    }

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "comparison.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
