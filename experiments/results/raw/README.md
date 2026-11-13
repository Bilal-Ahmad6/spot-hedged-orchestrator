# Raw and superseded results

These files are kept for audit, not as evidence. The report must cite
`experiments/results/g4_summary.json`, not anything here.

| File | Status |
|---|---|
| `drain_graceful.json` | **Invalid methodology.** Produced with `kubectl port-forward`, which pins one TCP stream to one pod; the drained pod was never on the traffic path, so the zero failure count is meaningless. Superseded by the in-cluster run in `g4_summary.json`. |
| `drain_abrupt.json` | Abrupt-deletion run at 50 rps. Zero failures observed, but at ~17 ms service time only a fraction of a request was in flight; inconclusive, not evidence. |
| `loadtest_kind.json` | Valid baseline through port-forward (100 rps, p95 71.25 ms), but port-forward is single-backend; kept as a harness check only. |
| `loadtest_local.json` | Local uvicorn run used to validate the generator itself before the cluster existed. |

The lesson from the first row is in `docs/PROGRESS.md` under "Methodology
correction": a drain test must send traffic through the Service from inside the
cluster, or it proves nothing.
