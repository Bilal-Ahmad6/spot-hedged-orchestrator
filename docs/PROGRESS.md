# Progress

> Last updated: 2026-11-12 16:20 UTC | Milestone: **M1 — simulator complete** | Gate: **G1 passed**
> This document is updated **with** the work it describes, never in a separate commit.

## Snapshot

Scope ladder target: **Tier 3** (see [docs/04-timeline.md](04-timeline.md#3-scope-ladder-how-far-to-go)).

| Milestone | Scope | Status | Gate | Evidence |
|---|---|---|---|---|
| M0 Foundations | repo, CI, env, definitions, trace, prices | **done** | **G0 ✅** | 28 tests, ruff clean, trace + anchors |
| M1 Data + simulator | lifecycle, ledger, queueing, interruptions | **done** | **G1 ✅** | golden cost tests; 30-day baseline runs |
| M2 Policy + G2 | forecast, MILP, baselines, 20 seeds | in progress | G2 | — |
| M3 Controller + cluster | CRD, kopf, KWOK, reclaim | not started | G3 | — |
| M4 Data plane | kind, k6, drain, OpenCost | not started | G4 | — |
| M5 Matrix | 2,800 runs, ablation, figures | not started | G5 | — |
| M6 Report + demo | report, runbook, viva | not started | G6 | — |
| M7 Freeze | tag, archive, clean-clone check | not started | G7 | — |

## Baseline results (30 days = 720 h, 15 % headroom everywhere)

| Policy | 30-day cost | Monthly equivalent (×730/720) | Availability | SLO-violation minutes |
|---|---|---|---|---|
| P0 static peak | $5,068.80 | $5,138.40 | 100.00 % | 0 |
| P1 on-demand HPA + CA | $2,630.47 | $2,667.01 | 99.745 % | 1,224 |
| P2 fixed 70/30 ratio | $1,513.06 | $1,534.07 | 99.892 % | 303 |

Artifacts: `experiments/results/baseline_p*.json`. This is the first evidence that the
model produces sensible, differentiated numbers — and that **neither reactive baseline
meets the 99.9 % target**, which is the gap the hedged policy must close.

## Now / Next / Blocked

- **Now:** M2 — forecaster, hedged allocation, reclaim-aware provisioning, 20-seed runner.
- **Next:** G2 experiment (P3 ≥ 20 % cheaper than P1 at 65 % discount, ≤ 0.1 pp availability loss).
- **Blocked:** nothing. Docker daemon still stopped; needed at M3.

## Journal

Newest first.

- **2026-11-12** — **M1 complete.** Time-stepped engine with derived node state, cost ledger, Erlang-C/Allen-Cunneen SLO model and interruption models I1–I4. Golden tests: 160 vCPU-month = **$4,672.00** exactly (proposal), discrete packing = **$5,139.20** (the ADR-0005 correction, hand-verified). 30-day run ≈ 6 s. Baseline table above. — commit: pending — evidence: `tests/golden/test_p0_cost.py`, `experiments/results/`.
- **2026-11-12** — **Trace finding.** Raw per-minute invocation counts change by 16.6 % minute-to-minute (p99 109 %); feeding that to a controller produces churn no real system shows. Added a 15-minute centred smoothing step before the rank transform (mean jump 2.1 %, p99 17.5 %). Rebuilt trace, hash `7eb8f5f2…`. — evidence: `experiments/traces/README.md`.
- **2026-11-12** — **ADR-0001 revised** after the prototype: a deterministic time-stepped loop replaces SimPy (derived node state, 6 s per 30-day run, trivial determinism). SimPy removed from dependencies. — evidence: `docs/decisions/ADR-0001-simulation-engine.md`.
- **2026-11-12** — **M0 complete.** Price anchors (median **$0.048/vCPU-h** on-demand, **79 %** implied spot discount); 43,200-minute trace from the Azure Functions invocation stream; M0 gate green. — commit: `8ace0c2`.
- **2026-11-12** — Plan approved; environment recon; repo pushed to `Bilal-Ahmad6/spot-hedged-orchestrator` (`3b7c55e`).

## Decisions

| ADR | Decision |
|---|---|
| [0001](decisions/ADR-0001-simulation-engine.md) | Deterministic time-stepped engine (revised from SimPy) |
| [0002](decisions/ADR-0002-allocation-solver.md) | PuLP/CBC for the allocation MILP |
| [0003](decisions/ADR-0003-controller-framework.md) | kopf for the Kubernetes controller |
| [0004](decisions/ADR-0004-fake-cluster.md) | KWOK (+ kind) for control-plane realism |
| [0005](decisions/ADR-0005-discrete-packing-and-headroom.md) | Discrete node packing + drain headroom |
| [0006](decisions/ADR-0006-data-sources.md) | Azure Functions trace + Azure Retail price anchors |

## Validation

| Check | Command | Result |
|---|---|---|
| Environment | `python -m spothedge doctor` | ok — all deps, config parses |
| Lint | `python -m ruff check src tests` | clean |
| Tests | `python -m pytest` | **28 passed** |
| Golden: continuous P0 | `pytest tests/golden` | **$4,672.00**/month (proposal, exact) |
| Golden: discrete P0 | `pytest tests/golden` | **$5,139.20**/month (11 × 16 vCPU) |
| Determinism | `pytest tests/test_simulation.py` | identical results for identical seeds |
| 30-day runtime | `spothedge sim run` | ≈ 6 s |
| CI | GitHub Actions `ci` | pending this push |
| G2 | primary comparison | not yet run (M2) |

## Deviations

- **ADR-0001 revised:** time-stepped loop instead of SimPy (see the ADR for why).
- **Trace smoothing (15 min)** added after measuring the raw jump distribution. The
  source data and the envelope are unchanged; only sampling noise is removed.
- **Hour-of-day is arbitrary** because the source uses relative timestamps. The
  report will state this; the daily amplitude and weekly pattern are preserved.
- Azure's implied spot discount (79 %) is deeper than the proposal's 65 % base. The
  base stays 65 % for comparability; the sweep covers 40–80 %.

## Asks

| What | Why | Blocking |
|---|---|---|
| Docker Desktop login/UAC, when M3 starts | start the daemon for kind/KWOK | no, until M3 |
| GitHub usernames of Amina, Mahnoor, Rabia | collaborator access | no |
| AWS budget/credentials | optional live validation, ≤ US$50 | no |
