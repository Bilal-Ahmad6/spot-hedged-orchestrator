# Progress

> Last updated: 2026-11-12 16:20 UTC | Milestone: **M1 — simulator complete** | Gate: **G1 passed**
> This document is updated **with** the work it describes, never in a separate commit.

## Snapshot

Scope ladder target: **Tier 3** (see [docs/04-timeline.md](04-timeline.md#3-scope-ladder-how-far-to-go)).

| Milestone | Scope | Status | Gate | Evidence |
|---|---|---|---|---|
| M0 Foundations | repo, CI, env, definitions, trace, prices | **done** | **G0 ✅** | 28 tests, ruff clean, trace + anchors |
| M1 Data + simulator | lifecycle, ledger, queueing, interruptions | **done** | **G1 ✅** | golden cost tests; 30-day baseline runs |
| M2 Policy + G2 | forecast, hedged allocation, reclaim-aware provisioning | **done** | **G2 ✅** | 20-seed paired comparison: **−26.15 %** cost, **+0.023 pp** availability |
| M3 Controller + cluster | CRD, kopf, KWOK, reclaim | **in progress** | G3 | controller runtime + KWOK actuator working; 3 reclaims handled; fail-static passed |
| M4 Data plane | kind, load generator, drain | **in progress** | G4 | p95 24 ms in-cluster; 3,000 requests, **0 failures** on a graceful drain |
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

- **2026-11-13** — **G4 graceful drain passed, in-cluster.** kind cluster with 3 pool-labelled workers; svc-od/svc-spot behind one Service with PDB minAvailable=3. An in-cluster load Job drove 50 rps through the Service while a node hosting a spot pod was drained: **3,000 requests, 0 failures**, p95 **24.16 ms**, drain 7.6 s. Evidence: `experiments/results/g4_summary.json`.
- **2026-11-13** — **Methodology correction.** The first drain test used `kubectl port-forward`, which pins one TCP stream to one pod; the drained pod was never on that path, so the zero was meaningless. Re-ran with the load generator inside the cluster against the Service. This is recorded because it is exactly the kind of false positive the protocol is meant to catch.
- **2026-11-13** — **Abrupt-loss test inconclusive.** Force-deleting a spot pod at 50–200 rps produced 0 observed failures: achieved throughput was ~98 rps and endpoint removal is fast, so only a handful of connections were in flight on the killed pod. Reported as a limitation; needs higher load or per-pod pinning.

- **2026-11-13** — **M4 started.** Added the kind topology (1 control plane + 3 workers labelled on-demand/spot-a/spot-b), a FastAPI reference service with a CPU/latency knob and a readiness gate, a fixed-rate aiohttp load generator, and a drain harness that runs load, drains a node mid-flight, and reports failed requests in graceful and abrupt modes. k6 was dropped: its 30 MB download is slower than writing the 80-line generator, and the measurements are the same (p50/p95/p99, failures, achieved rps). — commit `e82cfd8`.

- **2026-11-12** — **G2 passed.** 20 paired seeds at a 65 % discount: P3 costs **$1,942.69 ± 0.26** versus P1's **$2,630.47**, a **26.15 % ± 0.01 pp** reduction, with availability **99.978 % ± 0.0006 pp** versus P1's 99.745 %. Evidence: `experiments/results/g2_comparison.json`.
- **2026-11-12** — **M3 controller works against the real API server.** KWOK cluster (v1.36.1 control plane, 16 CPUs), `HedgedService` CRD, `KwokNodeActuator` creating nodes with correct allocatable capacity. Three injected reclaims were each replaced before the drain; logged capacity stayed at 66.6 vCPU. Fail-static: 21 nodes unchanged after 45 s with the controller killed. Evidence: `experiments/results/controller_demo.log`, `controller_decisions.jsonl`, `decision_sample.jsonl`.
- **2026-11-12** — **Actuator bugs found and fixed in the cluster** (both invisible in simulation): terminating nodes were counted as capacity, and a surplus that was already draining was drained again. The second caused capacity to collapse to zero. This is why T2 exists.
- **2026-11-12** — **kopf timer does not fire against this CRD** on Windows; the shared `ControllerRuntime` is therefore driven by `scripts/run_controller.py` for the demo. The kopf operator remains the deployment path and needs a review when the cluster tier is completed.
- **2026-11-12** — **M2 policy implemented.** Seasonal-naive forecaster (EWMA + P90), closed-form survival allocation, reclaim pre-spin, shape stability. Differential test vs MILP: mean **1.14×**, worst **1.24×** of the optimum. 45 tests passing.
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
| G2 | 20 paired seeds, P1 vs P3 at 65 % | **PASSED**: −26.15 % ± 0.01 pp cost, +0.023 pp availability |
| Controller vs API | 21 nodes, 3 reclaims | node replaced before drain; capacity constant at 66.6 vCPU |
| Fail-static | kill controller, 45 s | 21 nodes before and after: **PASSED** |

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
- **T2 demo runs the shared runtime directly** (`scripts/run_controller.py`) rather
  than through kopf, whose timer does not fire against the CRD on this Windows
  build. The kopf operator is still the deployment path; this is a test-harness
  substitution, not a change to the policy.

## Asks

| What | Why | Blocking |
|---|---|---|
| Docker Desktop login/UAC, when M3 starts | start the daemon for kind/KWOK | no, until M3 |
| GitHub usernames of Amina, Mahnoor, Rabia | collaborator access | no |
| AWS budget/credentials | optional live validation, ≤ US$50 | no |
