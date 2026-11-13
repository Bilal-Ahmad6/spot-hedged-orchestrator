"""Reference service for the data-plane tier.

`/work` burns a configurable amount of CPU and sleeps for a configurable time, so
the same image can produce a realistic latency distribution and a measurable CPU
utilisation. `/healthz` is the readiness gate; on SIGTERM uvicorn stops accepting
new connections, which is what makes a zero-lost-request drain possible.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Query, Response
from fastapi.responses import PlainTextResponse

app = FastAPI()
STARTED = time.time()


def burn(ms: int) -> None:
    """Busy-wait for roughly `ms` milliseconds of CPU."""
    deadline = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < deadline:
        pass


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"


@app.get("/readyz", response_class=PlainTextResponse)
def readyz() -> str:
    return "ok"


@app.get("/work")
def work(
    cpu_ms: int = Query(default=2, ge=0, le=200),
    sleep_ms: int = Query(default=5, ge=0, le=200),
) -> Response:
    burn(cpu_ms)
    if sleep_ms:
        time.sleep(sleep_ms / 1000.0)
    return Response(content="ok", media_type="text/plain")


@app.get("/stats")
def stats() -> dict:
    return {"uptime_s": time.time() - STARTED, "pid": os.getpid()}
