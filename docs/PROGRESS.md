# Progress

> Last updated: 2026-11-12 15:05 UTC | Milestone: **M0 — Foundations complete** | Gate: **G0 passed locally** (CI pending first push)
> This document is updated **with** the work it describes, never in a separate commit.

## Snapshot

Scope ladder target: **Tier 3** (see [docs/04-timeline.md](04-timeline.md#3-scope-ladder-how-far-to-go)).

| Milestone | Scope | Status | Gate | Evidence |
|---|---|---|---|---|
| M0 Foundations | repo, CI, env, definitions, trace, prices | **done** | **G0 ✅** | 10 tests, ruff clean, trace + anchors built |
| M1 Data + simulator | lifecycle, ledger, queueing, interruptions | in progress | G1 | queueing model written |
| M2 Policy + G2 | forecast, MILP, baselines, 20 seeds | not started | G2 | — |
| M3 Controller + cluster | CRD, kopf, KWOK, reclaim | not started | G3 | — |
| M4 Data plane | kind, k6, drain, OpenCost | not started | G4 | — |
| M5 Matrix | 2,800 runs, ablation, figures | not started | G5 | — |
| M6 Report + demo | report, runbook, viva | not started | G6 | — |
| M7 Freeze | tag, archive, clean-clone check | not started | G7 | — |

## Now / Next / Blocked

- **Now:** M1 — node lifecycle, cost ledger, interruption generators, engine, runner.
- **Next:** G1 golden test (P0 = $4,672/month ±1%), then M2 policy.
- **Blocked:** nothing. Docker daemon is stopped; needed at M3, not before.

## Journal

Newest first. Each entry: date — change — commit — evidence.

- **2026-11-12** — **M0 complete.** Price anchors fetched from Azure Retail API (median **$0.048/vCPU-h** on-demand, implied spot discount **79%** across D2s/D4s/D8s v5). Demand trace built from the real Azure Functions 2021 invocation stream: 43,200 minutes, min 40.0, mean 70.0, p95 142.9, max 160.0, γ=3.0001; weekday mean 75.3 vs weekend 55.3. Service-time median 46 ms recorded for the SLO model. — commit: pending — evidence: `prices/anchors.json`, `experiments/traces/demand_30d.csv`, `demand_30d.meta.json`.
- **2026-11-12** — Scaffolded `src/spothedge` (model, config, CLI, price fetcher, trace builder), Makefile, CI, six ADRs, 10 unit tests; `ruff` clean, `pytest` 10/10. — commit: pending — evidence: `python -m spothedge doctor`.
- **2026-11-12** — Plan approved (Plannotator). Reconnaissance: Python 3.14.2 works with all dependencies; Docker installed but daemon stopped; `kind`/`kwokctl`/`helm`/`k6` missing (choco present, shell not elevated); RAR extraction solved with a WASM unrar under Node; Azure Retail Prices API works unauthenticated. — evidence: shell recon in session.
- **2026-11-12** — Repository initialised with research digest, architecture, experiment protocol, milestones/scope ladder and backlog; pushed to `Bilal-Ahmad6/spot-hedged-orchestrator`. — commit: `3b7c55e`.

## Decisions

| ADR | Decision |
|---|---|
| [0001](decisions/ADR-0001-simulation-engine.md) | SimPy for the discrete-event testbed |
| [0002](decisions/ADR-0002-allocation-solver.md) | PuLP/CBC for the allocation MILP |
| [0003](decisions/ADR-0003-controller-framework.md) | kopf for the Kubernetes controller |
| [0004](decisions/ADR-0004-fake-cluster.md) | KWOK (+ kind) for control-plane realism |
| [0005](decisions/ADR-0005-discrete-packing-and-headroom.md) | Discrete node packing + drain headroom in the capacity constraint |
| [0006](decisions/ADR-0006-data-sources.md) | Azure Functions trace + Azure Retail price anchors |

## Validation

| Check | Command | Result |
|---|---|---|
| Environment | `python -m spothedge doctor` | ok — all deps present, config parses |
| Lint | `python -m ruff check src tests` | clean |
| Tests | `python -m pytest` | **10 passed** |
| CI | GitHub Actions `ci` | pending first push |
| Trace sanity | rows/min/mean/max | 43,200 / 40.0 / 70.0 / 160.0 |
| Price anchor | `prices/anchors.json` | $0.048/vCPU-h on-demand, 79% spot discount |
| G1 golden cost | `pytest tests/golden -k p0_cost` | not yet written (M1) |

## Deviations

- The 2021 trace ships as `.rar`, and no unrar/7-Zip was installed. Extracted with the
  `node-unrar-js` WASM extractor (Node 24, no admin rights needed) into
  `experiments/traces/raw/` (gitignored). No change to the data or the method.
- Azure's implied spot discount (79%) is deeper than the proposal's 65% base case. The
  base case stays 65% for comparability; the sensitivity sweep covers 40–80%.

## Asks

| What | Why | Blocking |
|---|---|---|
| Docker Desktop login/UAC, when M3 starts | start the daemon for kind/KWOK | no, until M3 |
| GitHub usernames of Amina, Mahnoor, Rabia | collaborator access | no |
| AWS budget/credentials | optional live validation, ≤ US$50 | no |
