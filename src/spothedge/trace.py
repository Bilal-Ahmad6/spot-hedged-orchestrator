"""Demand trace construction.

The Azure Functions invocation trace is a stream of individual invocations with
timestamps and durations. We need two things from it:

1. a per-minute demand series rescaled to the proposal's 40-160 vCPU envelope
   with a mean of ~70 vCPU, and
2. an empirical service-time distribution for the queueing model.

The rescaling uses a rank transform, ``D = min + (max-min) * F^gamma``, where
``F`` is the empirical CDF and ``gamma`` is solved so the mean hits the target.
That preserves the trace's temporal shape exactly (it is monotone) while making
the envelope match the documented workload.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

AZURE_REQUIRED = {"end_timestamp", "duration"}
MINUTES_PER_DAY = 1440


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def _read_azure_invocations(path: Path) -> tuple[pd.Series, np.ndarray]:
    """Return (invocations per minute, sampled durations in seconds)."""

    counts: list[pd.Series] = []
    durations: list[np.ndarray] = []
    for chunk in pd.read_csv(path, usecols=["end_timestamp", "duration"], chunksize=2_000_000):
        minute = np.floor(chunk["end_timestamp"].to_numpy() / 60.0).astype(np.int64)
        counts.append(pd.Series(minute).value_counts())
        if len(durations) < 8:
            durations.append(chunk["duration"].to_numpy(dtype=float))
    per_minute = pd.concat(counts, axis=1).fillna(0).sum(axis=1).sort_index()
    per_minute.index = per_minute.index.astype(np.int64)
    sample = np.concatenate(durations) if durations else np.array([], dtype=float)
    return per_minute, sample


def _read_simple_csv(path: Path) -> tuple[pd.Series, np.ndarray]:
    """Accept `minute,count` or `timestamp,count` for tests and small runs."""

    frame = pd.read_csv(path)
    columns = {c.lower(): c for c in frame.columns}
    if "minute" in columns:
        minute = frame[columns["minute"]].astype(int)
    elif "timestamp" in columns:
        timestamps = pd.to_datetime(frame[columns["timestamp"]], utc=True)
        origin = timestamps.min()
        minute = ((timestamps - origin).dt.total_seconds() // 60).astype(int)
    else:
        raise ValueError(f"{path}: expected a 'minute' or 'timestamp' column")
    value_column = columns.get("count") or columns.get("demand") or columns.get("invocations")
    if value_column is None:
        raise ValueError(f"{path}: expected a count/demand column")
    series = frame.groupby(minute)[value_column].sum().sort_index()
    series.index = series.index.astype(int)
    return series, np.array([], dtype=float)


def read_invocations(path: Path) -> tuple[pd.Series, np.ndarray]:
    columns = set(pd.read_csv(path, nrows=0).columns)
    if AZURE_REQUIRED.issubset(columns):
        return _read_azure_invocations(path)
    return _read_simple_csv(path)


def synthetic_invocations(days: int = 14, seed: int = 7) -> pd.Series:
    """Fallback profile, documented in the protocol: diurnal + weekly + AR(1)."""

    rng = np.random.default_rng(seed)
    minutes = days * MINUTES_PER_DAY
    index = np.arange(minutes)
    hour = (index % MINUTES_PER_DAY) / 60.0
    weekday = (index // MINUTES_PER_DAY) % 7
    diurnal = 0.5 * (1.0 + np.sin(2 * math.pi * (hour - 9.0) / 24.0))
    weekly = np.where(weekday < 5, 1.0, 0.55)
    noise = np.zeros(minutes)
    for i in range(1, minutes):
        noise[i] = 0.85 * noise[i - 1] + rng.normal(0.0, 0.12)
    strength = np.clip(diurnal * weekly + noise, 0.01, None)
    return pd.Series(strength * 1000.0, index=index)


def _tile_to_days(series: pd.Series, days: int) -> np.ndarray:
    values = series.to_numpy(dtype=float)
    if values.size == 0:
        raise ValueError("empty demand series")
    target = days * MINUTES_PER_DAY
    repeats = math.ceil(target / values.size)
    return np.tile(values, repeats)[:target]


def _solve_gamma(percentiles: np.ndarray, target_mean: float, lo: float, hi: float) -> float:
    """Find gamma such that mean(lo + (hi-lo) * pct**gamma) == target_mean."""

    target = (target_mean - lo) / (hi - lo)
    a, b = 0.05, 12.0
    for _ in range(80):
        mid = 0.5 * (a + b)
        if float(np.mean(percentiles**mid)) > target:
            a = mid
        else:
            b = mid
    return 0.5 * (a + b)


def build_trace(
    source: Path | None,
    out: Path,
    seed: int,
    days: int,
    min_vcpu: float,
    max_vcpu: float,
    target_mean_vcpu: float = 70.0,
    start: str = "2026-01-05T00:00:00Z",
    smooth_minutes: int = 15,
) -> dict:
    """Build the 30-day demand CSV and its metadata sidecar."""

    if source is not None and Path(source).exists():
        invocations, durations = read_invocations(Path(source))
        provenance = {"kind": "azure-functions-invocation-trace", "path": str(source)}
        provenance["sha256"] = _sha256(Path(source))
    else:
        invocations = synthetic_invocations(days=14, seed=seed)
        durations = np.array([], dtype=float)
        provenance = {"kind": "synthetic-fallback", "seed": seed}

    # A capacity controller observes a rate over its metrics window, not a single
    # minute's invocation count. Smoothing removes sampling noise while leaving
    # the diurnal and weekly structure intact.
    if smooth_minutes > 1:
        invocations = invocations.rolling(
            window=smooth_minutes, min_periods=1, center=True
        ).mean()

    tiled = _tile_to_days(invocations, days)
    percentiles = pd.Series(tiled).rank(pct=True, method="average").to_numpy(dtype=float)
    gamma = _solve_gamma(percentiles, target_mean_vcpu, min_vcpu, max_vcpu)
    demand = min_vcpu + (max_vcpu - min_vcpu) * np.power(percentiles, gamma)

    timestamps = pd.date_range(start=start, periods=len(demand), freq="min", tz="UTC")
    frame = pd.DataFrame(
        {
            "minute": np.arange(len(demand), dtype=np.int64),
            "timestamp": timestamps.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "demand_vcpu": np.round(demand, 4),
        }
    )

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out, index=False)
    digest = _sha256(out)

    duration_stats: dict[str, float] = {}
    if durations.size:
        positives = durations[durations > 0]
        if positives.size:
            duration_stats = {
                "count_sampled": int(positives.size),
                "mean_s": float(np.mean(positives)),
                "p50_s": float(np.quantile(positives, 0.50)),
                "p90_s": float(np.quantile(positives, 0.90)),
                "p95_s": float(np.quantile(positives, 0.95)),
                "p99_s": float(np.quantile(positives, 0.99)),
            }

    summary = {
        "out": str(out),
        "sha256": digest,
        "rows": int(len(frame)),
        "days": days,
        "start": start,
        "envelope": {"min": min_vcpu, "max": max_vcpu, "target_mean": target_mean_vcpu},
        "observed": {
            "min": float(demand.min()),
            "mean": float(demand.mean()),
            "p95": float(np.quantile(demand, 0.95)),
            "max": float(demand.max()),
        },
        "rank_transform": {
            "gamma": gamma,
            "formula": "D = min + (max - min) * empirical_cdf ^ gamma",
        },
        "smoothing": {"window_minutes": smooth_minutes, "method": "centred rolling mean"},
        "provenance": provenance,
        "service_time": duration_stats,
    }

    meta_path = out.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
