# Progress

> Last updated: 2026-11-12 16:20 UTC | Milestone: **M1 — simulator complete** | Gate: **G1 passed**
> This document is updated **with** the work it describes, never in a separate commit.

## Snapshot

Scope ladder target: **Tier 3** (see [docs/04-timeline.md](04-timeline.md#3-scope-ladder-how-far-to-go)).

| Milestone | Scope | Status | Gate | Evidence |
|---|---|---|---|---|
| M0 Foundations | repo, CI, env, definitions, trace, prices | **done** | **G0 ✅** | 28 tests, ruff clean, trace + anchors |
| M1 Data + simulator | lifecycle, ledger, queueing, interruptions | **done** | **G1 ✅** | golden cost tests; 30-day baseline runs |
| M2 Policy + G2 | forecast, hedged allocation, reclaim-aware provisioning | **in progress** | G2 | 20-seed comparison running |
| M3 Controller + cluster | CRD, kopf, KWOK, reclaim | not started | G3 | — |
| M4 Data plane | kind, k6, drain, OpenCost | not started | G4 | — |
| M5 Matrix | 2,800 runs, ablation, figures | not started | G5 | — |
| M6 Report + demo | report, runbook, viva | not started | G6 | — |
| M7 Freeze | tag, archive, clean-clone check | not started | G7 | — |

## Baseline results (30 days = 720 h, 15 % headroom everywhere)

| Policy | 30-day cost | Monthly equivalent (×730/720) | Availability | SLO-violation minutes | Node launches |
|---|---|---|---|---|---|
| P0 static peak | $5,068.80 | $5,138.40 | 100.00 % | 0 | 11 |
| P1 on-demand HPA + CA | $2,630.47 | $2,667.01 | 99.745 % | 1,224 | 2,735 |
| P2 fixed 70/30 ratio | $1,513.06 | $1,534.07 | 99.892 % | 302 | 4,866 |
| **P3 hedged** | **$1,942.20** | **$1,969.05** | **99.978 %** | **59** | 11,499 |

Artifacts: `experiments/results/`. P3 is **26.2 % cheaper than P1** with 0.023 pp
*higher* availability and 20× fewer violation minutes. P2 is cheaper still but sits
below the 99.9 % target and has 5× P3's violation minutes — the Pareto point is the
argument, not the single cheapest number.

P3's churn (11.5 k launches) is its weakest number; it is reported rather than hidden.

## Now / Next / Blocked

- **Now:** M2 — forecaster, hedged allocation, reclaim-aware provisioning, 20-seed runner.
- **Next:** G2 experiment (P3 ≥ 20 % cheaper than P1 at 65 % discount, ≤ 0.1 pp availability loss).
- **Blocked:** nothing. Docker daemon still stopped; needed at M3.

## Journal

Newest first.

- **2026-11-12** — **M2 policy implemented.** Seasonal-naive forecaster with EWMA residual correction and a P90 quantile; closed-form hedged allocation with survival, floor, diversity and share constraints; reclaim-aware pre-spin (the engine now holds a noticed node until spare capacity exists, so a policy that provisions for the deficit drains safely). Differential test against the MILP reference: mean **1.14×**, worst **1.24×** of the optimum. 20-seed G2 comparison running.
- **2026-11-12** — **Shape-stability finding.** Re-optimising instance shapes every tick produced **180,000 node launches and 93 % availability** (capacity emptied for the 90 s lead time). Holding one shape per run gives 11,500 launches and 99.98 %. Shape stability is now a documented correctness requirement (ADR-0002).
- **2026-11-12** — **PuLP pinned below 4.0.** v4 removes the bundled CBC solver and the classic `LpVariable` API; `listSolvers(onlyAvailable=True)` is empty on a clean install and the solver-plugin build hung on Windows.
- **2026-11-12** — **M1 complete.** Time-stepped engine, cost ledger, Erlang-C/Allen-Cunneen SLO model, interruption models I1–I4. Golden tests: **$4,672.00** continuous, **$5,139.20** discrete. 30-day run ≈ 6 s (19 s with the hedged policy). — commit: `975a769`.
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
| Tests | `python -m pytest` | **42 passed** |
| Golden: continuous P0 | `pytest tests/golden` | **$4,672.00**/month (proposal, exact) |
| Golden: discrete P0 | `pytest tests/golden` | **$5,139.20**/month (11 × 16 vCPU) |
| Determinism | `pytest tests/test_simulation.py` | identical results for identical seeds |
| MILP agreement | `pytest tests/test_milp_agreement.py` | mean 1.14×, worst 1.24× of optimum |
| 30-day runtime | `spothedge sim run` | ≈ 6 s (P0), ≈ 19 s (P3) |
| CI | GitHub Actions `ci` | pending this push |
| G2 | 20-seed P1 vs P3 at 65 % | running; smoke run: **20.3 % cheaper** |

## Deviations

- **ADR-0001 revised:** time-stepped loop instead of SimPy (see the ADR for why).
- **Trace smoothing (15 min)** added after measuring the raw jump distribution. The
  source data and the envelope are unchanged; only sampling noise is removed.
- **Hour-of-day is arbitrary** because the source uses relative timestamps. The
  report will state this; the daily amplitude and weekly pattern are preserved.
- Azure's implied spot discount (79 %) is deeper than the proposal's 65 % base. The
  base stays 65 % for comparability; the sweep covers 40–80 %.
- **P1's target utilisation is 1/1.15 ≈ 87 %**, not the usual 70 %, so that every
  baseline provisions the same 15 % headroom. The 70 % target is a sensitivity case;
  using it in the primary comparison would have made the hedge look better than it is.
- **Primary `q` is 1/6**, the proposal's illustrative loss fraction and the policy's
  own assumption. `q ∈ {1/3, 1/2, 1}` are stress cases that deliberately exceed it.
- **Violation minutes** count a minute when p95 exceeds 150 ms **or** per-minute
  availability falls below 99.9 %. The earlier definition (any failed request)
  over-counted one-request dips.

## Asks

| What | Why | Blocking |
|---|---|---|
| Docker Desktop login/UAC, when M3 starts | start the daemon for kind/KWOK | no, until M3 |
| GitHub usernames of Amina, Mahnoor, Rabia | collaborator access | no |
| AWS budget/credentials | optional live validation, ≤ US$50 | no |
