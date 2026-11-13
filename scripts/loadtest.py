"""Closed-loop load generator for the data-plane tier.

k6 would be the default choice, but it is a 30 MB download on a slow link and we
need one number (tail latency) plus one count (failed requests). This does both,
with the same semantics: fixed arrival rate, bounded concurrency, per-request
latency, and a failure for any non-2xx or connection error.

Usage:
    python scripts/loadtest.py --url http://localhost:8080/work --rps 100 --seconds 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import aiohttp


async def one_request(session: aiohttp.ClientSession, url: str, latencies: list, failures: list):
    started = time.perf_counter()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
            await response.read()
            if response.status >= 300:
                failures.append(response.status)
    except Exception as exc:  # noqa: BLE001 - the load generator must survive anything
        failures.append(type(exc).__name__)
    finally:
        latencies.append((time.perf_counter() - started) * 1000.0)


async def worker(
    session: aiohttp.ClientSession,
    url: str,
    rate_per_worker: float,
    stop_at: float,
    latencies: list,
    failures: list,
) -> None:
    interval = 1.0 / rate_per_worker if rate_per_worker > 0 else 0.0
    next_at = time.perf_counter()
    while time.perf_counter() < stop_at:
        await one_request(session, url, latencies, failures)
        next_at += interval
        delay = next_at - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)


async def run(args) -> dict:
    workers = max(1, args.concurrency)
    rate_per_worker = args.rps / workers
    latencies: list[float] = []
    failures: list = []
    started = time.perf_counter()
    stop_at = started + args.seconds

    connector = aiohttp.TCPConnector(limit=workers * 2)
    async with aiohttp.ClientSession(connector=connector) as session:
        await asyncio.gather(
            *[
                worker(session, args.url, rate_per_worker, stop_at, latencies, failures)
                for _ in range(workers)
            ]
        )

    elapsed = time.perf_counter() - started
    ordered = sorted(latencies)
    total = len(ordered)
    summary = {
        "url": args.url,
        "target_rps": args.rps,
        "seconds": round(elapsed, 2),
        "requests": total,
        "achieved_rps": round(total / elapsed, 2),
        "failures": len(failures),
        "failure_rate": round(len(failures) / total, 6) if total else None,
        "failure_kinds": sorted({str(f) for f in failures})[:10],
        "latency_ms": {
            "mean": round(statistics.fmean(ordered), 2) if total else None,
            "p50": round(ordered[int(total * 0.50)], 2) if total else None,
            "p95": round(ordered[min(total - 1, int(total * 0.95))], 2) if total else None,
            "p99": round(ordered[min(total - 1, int(total * 0.99))], 2) if total else None,
            "max": round(ordered[-1], 2) if total else None,
        },
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080/work")
    parser.add_argument("--rps", type=float, default=100.0)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    summary = asyncio.run(run(args))
    text = json.dumps(summary, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
