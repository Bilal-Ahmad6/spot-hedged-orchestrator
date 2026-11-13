"""In-cluster load generator (stdlib only, so it runs in the app image).

Hits the Service DNS name, so kube-proxy load-balances across pods and endpoint
updates during a drain are actually exercised. Prints one JSON line.
"""

import json
import statistics
import sys
import threading
import time
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://checkout/work"
RPS = float(sys.argv[2]) if len(sys.argv) > 2 else 50.0
SECONDS = float(sys.argv[3]) if len(sys.argv) > 3 else 60.0
WORKERS = 20

latencies = []
failures = []
lock = threading.Lock()
stop_at = time.perf_counter() + SECONDS


def worker(rate):
    interval = 1.0 / rate
    next_at = time.perf_counter()
    while time.perf_counter() < stop_at:
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(URL, timeout=5) as response:
                response.read()
                if response.status >= 300:
                    with lock:
                        failures.append(str(response.status))
        except Exception as exc:  # noqa: BLE001
            with lock:
                failures.append(type(exc).__name__)
        finally:
            with lock:
                latencies.append((time.perf_counter() - started) * 1000.0)
        next_at += interval
        delay = next_at - time.perf_counter()
        if delay > 0:
            time.sleep(delay)


threads = [threading.Thread(target=worker, args=(RPS / WORKERS,)) for _ in range(WORKERS)]
started_at = time.time()
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()

ordered = sorted(latencies)
total = len(ordered)
print(
    json.dumps(
        {
            "requests": total,
            "failures": len(failures),
            "failure_kinds": sorted(set(failures))[:10],
            "seconds": round(time.time() - started_at, 2),
            "rps": round(total / max(0.001, time.time() - started_at), 2),
            "p95_ms": round(ordered[min(total - 1, int(total * 0.95))], 2) if total else None,
            "p99_ms": round(ordered[min(total - 1, int(total * 0.99))], 2) if total else None,
            "mean_ms": round(statistics.fmean(ordered), 2) if total else None,
        }
    )
)
