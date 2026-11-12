# Backlog

Estimates are in hours and assume one owner. "Done when" is the acceptance test, not a description.

---

## E1 — Foundations (25 h)

| ID | Ticket | Owner | Est | Depends | Done when |
|---|---|---|---|---|---|
| E1-01 | Create GitHub repo, branch protection, PR template, issue labels | Bilal | 2 | — | A PR cannot merge with red CI |
| E1-02 | Python project (`pyproject.toml`, ruff, mypy-lite, pytest) + lockfile | Bilal | 3 | E1-01 | `make lint test` passes on a clean clone |
| E1-03 | `make` targets: `sim-smoke`, `cluster-up`, `cluster-down`, `experiment`, `verify`, `report` | Bilal | 3 | E1-02 | Each target documented in `RUNBOOK.md` |
| E1-04 | `kind` + `kwokctl` smoke test on all laptops; record specs | Bilal | 3 | E1-02 | `kubectl get nodes` shows 1 real + 3 fake nodes on ≥3 machines |
| E1-05 | Freeze definitions: p95 threshold, availability formula, cost convention | Amina | 2 | — | One paragraph in `docs/decisions.md`, signed off by all |
| E1-06 | Reading notes: SkyServe §3, SpotKube, ROSS, Karpenter disruption | All | 4 | — | Four short notes in `docs/reading/` |
| E1-07 | `docs/decisions.md` ADR log (why SimPy, PuLP, kopf, KWOK) | Rabia | 3 | E1-06 | Six ADRs, each with the rejected alternative |
| E1-08 | CI workflow: lint, test, `make verify` (3 fixed cells) | Bilal | 5 | E1-03, E3-06 | Green on `main`; red on a deliberately broken policy test |

## E2 — Data layer (35 h)

| ID | Ticket | Owner | Est | Depends | Done when |
|---|---|---|---|---|---|
| E2-01 | Download Azure Functions 2021 trace; document licence/provenance | Mahnoor | 4 | — | Raw file + sha256 + source note |
| E2-02 | Trace→demand transform (normalise shape, rescale to 40–160 vCPU, tile 30 days) | Mahnoor | 6 | E2-01 | `demand_30d.csv` passes the five sanity checks in protocol §3 |
| E2-03 | Synthetic fallback generator (documented, seeded) | Mahnoor | 3 | — | Produces the same schema; clearly labelled in config |
| E2-04 | Price table + Azure Retail API fetch script | Mahnoor | 6 | — | `prices/base.yaml` + `prices/anchors_<date>.json` with the API response hash |
| E2-05 | Instance catalogue (2/4/8/16 vCPU) with allocatable overhead | Bilal | 3 | E2-04 | Node counts in the plan match a hand calculation |
| E2-06 | Interruption generators I1–I4 | Bilal | 8 | — | Seeded; `q=1` event produced on demand; event log replay matches |
| E2-07 | Common-random-number harness (same events for all policies) | Bilal | 4 | E2-06 | Two policies in the same seed see byte-identical event files |
| E2-08 | Volatile-price generator (±20%, 6 h period) | Mahnoor | 3 | E2-04 | Cost ledger monotonic; price series reproducible |

## E3 — Simulator (65 h)

| ID | Ticket | Owner | Est | Depends | Done when |
|---|---|---|---|---|---|
| E3-01 | Event loop + clock + seeded RNG discipline | Mahnoor | 8 | E1-02 | Same seed ⇒ identical event trace |
| E3-02 | Node lifecycle model (launch → ready after `leadTime` → drain → delete) | Mahnoor | 8 | E3-01 | A node is never schedulable before `readyAt` |
| E3-03 | Cost ledger (node-seconds × price, idle included) | Mahnoor | 5 | E3-02 | P0 = $4,672 ± 1% for 160 vCPU on-demand for 730 h |
| E3-04 | Capacity/replica model (`replicas = floor(cap/pod_cpu)`, PDB awareness) | Mahnoor | 8 | E3-02 | Drain headroom prevents eviction deadlock in a unit test |
| E3-05 | Queueing SLO model (Erlang-C + Allen–Cunneen, bucket p95) | Mahnoor | 10 | E3-04 | Model p95 monotonic in load; `ρ≥1` produces failures |
| E3-06 | Results writer (`summary.json`, `decisions.jsonl`, `env.txt`, hashes) | Rabia | 6 | E3-03 | Schema-valid; `make verify` diffs cleanly |
| E3-07 | Baselines P0–P2 as policy plugins | Mahnoor | 8 | E3-04 | Each matches its hand-computed cost on a flat trace |
| E3-08 | Multi-seed runner + bootstrap CI helper | Mahnoor | 6 | E3-06 | 20 seeds in one command; CI reported in `summary.json` |
| E3-09 | Performance: 30-day run < 3 s single core | Mahnoor | 6 | E3-05 | Timed in CI; regression fails the build |

## E4 — Policy and forecast (60 h)

| ID | Ticket | Owner | Est | Depends | Done when |
|---|---|---|---|---|---|
| E4-01 | Forecaster: seasonal naive + EWMA + residual P90 | Amina | 8 | E2-02 | MAPE and P90 coverage reported; coverage 0.85–0.95 |
| E4-02 | MILP model: survival, demand, floor, diversity, spot cap, quota | Amina | 12 | E3-03 | Solves in ≤200 ms on the 12-node catalogue |
| E4-03 | Lead-time shift (`D̂(t+L)`) and drain-headroom term | Amina | 5 | E4-02 | Ramp test provisions **before** demand rises |
| E4-04 | Hysteresis / churn penalty | Amina | 4 | E4-02 | Node churn on a flat trace ≤ 1 change/day |
| E4-05 | Infeasibility ladder (`RELAXED_HEADROOM` → `SPOT_DISABLED` → `INFEASIBLE`) | Amina | 5 | E4-02 | Each branch reachable by a unit test; no silent relaxation |
| E4-06 | Edge-case suite: `q=1`, peak loss, zero demand, quota exhaustion, `h=0` | Amina | 6 | E4-02 | All pass; documented expected outputs |
| E4-07 | Decision-record emitter (schema-valid, replayable) | Amina | 6 | E2-07, E4-02 | 1,000 random records replay to identical plans |
| E4-08 | P4 oracle policy (perfect foresight) | Amina | 4 | E3-07 | Oracle cost ≤ hedge cost on every seed |
| E4-09 | G2 experiment: 65% discount, 20 seeds, P1 vs P3 | Amina + Mahnoor | 8 | E4-04, E3-08 | Result recorded; go/no-go decision written down |

## E5 — Controller (55 h)

| ID | Ticket | Owner | Est | Depends | Done when |
|---|---|---|---|---|---|
| E5-01 | CRD `HedgedService` + validation (CEL) | Amina | 5 | E4-02 | `kubectl apply` rejects an invalid `q` or `p95LatencyMs` |
| E5-02 | kopf operator skeleton with reconcile + timers | Amina | 8 | E5-01 | Creates a decision record every tick in a dry run |
| E5-03 | Prometheus client: demand, CPU, p95, error rate | Amina | 6 | E5-02 | Missing metric ⇒ `DEGRADED`, not a crash |
| E5-04 | Wire allocator + actuator behind protocols | Amina | 6 | E5-02, E6-02 | Policy module imported unchanged (hash check in test) |
| E5-05 | Decision logger with fsync + rotation | Rabia | 4 | E4-07 | No record loss over a 2-hour run |
| E5-06 | Fail-static behaviour + test | Rabia | 4 | E5-02 | `kubectl delete pod` leaves the cluster unchanged for 5 min |
| E5-07 | RBAC: nodes, pods/eviction, nodeclaims, read metrics | Rabia | 3 | E5-01 | `kubectl auth can-i --list` shows nothing extra |
| E5-08 | Reclaim watcher (annotation and node-deletion paths) | Amina | 7 | E5-04 | Both paths drive the state machine; deadline logic tested |
| E5-09 | Leader-election design note (not implemented) | Rabia | 2 | E5-02 | One page in the report's design section |

## E6 — Cluster, actuator, injection (50 h)

| ID | Ticket | Owner | Est | Depends | Done when |
|---|---|---|---|---|---|
| E6-01 | KWOK cluster config (3 pools, labels, taints, prices as annotations) | Bilal | 5 | E1-04 | `kubectl get nodes -L pool` shows the expected mix |
| E6-02 | `kwok-node` actuator: create/patch/delete `Node`, wait for Ready | Bilal | 10 | E6-01 | Plan→cluster converges in ≤ `leadTime` + 10 s |
| E6-03 | App manifests: `svc-od`, `svc-spot`, Service, PDB, probes | Bilal | 5 | E6-01 | Rolling update of either Deployment loses no requests in T3 |
| E6-04 | Trace replayer: patch `kwok.x-k8s.io/usage-cpu` per pod each 15 s | Bilal | 6 | E6-03, R2 | HPA follows the trace within one sync period |
| E6-05 | Reclaim injector: graceful (annotate→drain→delete) and abrupt (delete) | Bilal | 6 | E6-02 | Both modes reproducible from one command |
| E6-06 | Karpenter KWOK spike (timeboxed 2 days) | Bilal | 8 | E6-01 | Go/no-go note: works, or documented fallback |
| E6-07 | Karpenter actuator adapter (only if E6-06 is green) | Bilal | 6 | E6-06 | Same policy module drives NodeClaims |
| E6-08 | Helm chart or Kustomize overlay for the full stack | Bilal | 4 | E6-03, E5-01 | One command installs and uninstalls |

## E7 — Data-plane validation (30 h)

| ID | Ticket | Owner | Est | Depends | Done when |
|---|---|---|---|---|---|
| E7-01 | FastAPI service with CPU-burn endpoint + health/readiness | Bilal | 4 | — | `/work?ms=50` consumes a predictable amount of CPU |
| E7-02 | kind 3-worker cluster + app + k6 | Bilal | 5 | E7-01 | 100 rps sustained; p95 reported |
| E7-03 | Drain test: 30 s notice, assert 0 failed requests | Bilal | 5 | E7-02 | k6 summary shows `http_req_failed = 0` |
| E7-04 | Abrupt test: 0 s notice, measure loss | Bilal | 4 | E7-02 | Loss count recorded and compared with Little's law |
| E7-05 | Calibrate analytic latency model against E7-02 | Amina | 6 | E7-02, E3-05 | Error ≤15% at target load, or empirical curve adopted |
| E7-06 | OpenCost install + cost cross-check | Mahnoor | 4 | E7-02 | Ledger vs OpenCost difference explained in one paragraph |
| E7-07 | Teardown + spend report scripts | Rabia | 2 | E6-08 | Cluster deleted; report lists every resource and its modelled cost |

## E8 — Experiments and analysis (55 h)

| ID | Ticket | Owner | Est | Depends | Done when |
|---|---|---|---|---|---|
| E8-01 | Primary matrix config (1,200 cells) + runner | Mahnoor | 6 | E3-08, E4-04 | Completes in <45 min on 4 cores |
| E8-02 | Headroom/feasibility matrix (900 cells) | Mahnoor | 4 | E8-01 | Results stored with config hashes |
| E8-03 | Sensitivity + ablation matrices | Amina | 5 | E8-01 | Every ablation removes exactly one mechanism |
| E8-04 | Failure analysis: classify every seed with availability <99.9% | Amina | 8 | E8-01 | Table with mechanism per seed |
| E8-05 | Figures (a)–(f) from artifacts | Mahnoor | 8 | E8-01 | Every figure regenerated by `make report` |
| E8-06 | Cross-tier consistency check (T1 vs T2 vs T3) | Mahnoor | 5 | E7-05, E6-05 | Discrepancies quantified, not hand-waved |
| E8-07 | Reproducibility audit: clean clone, one command | Bilal | 4 | E8-01 | `make verify` passes on a machine that never ran it |
| E8-08 | Archive runs (tag, checksums, download link) | Rabia | 3 | E8-01 | Hash list in the report appendix |

## E9 — Report, demo, viva (60 h)

| ID | Ticket | Owner | Est | Depends | Done when |
|---|---|---|---|---|---|
| E9-01 | Report skeleton with generated tables wired in | Rabia | 5 | E3-06 | No number typed by hand |
| E9-02 | Problem/architecture/feasibility chapters refreshed from A1 | Rabia | 8 | — | Consistent with the implemented system |
| E9-03 | Results + discussion, including the H2 finding | Amina | 10 | E8-04 | States the discount threshold and the honest shortfall |
| E9-04 | Threats to validity + limitations | Mahnoor | 5 | E8-06 | Every item in protocol §11 addressed |
| E9-05 | Lifecycle/runbook chapter | Rabia | 5 | E7-07 | A reader can deploy, run, and tear down |
| E9-06 | Demo script + rehearsal ×2 | Rabia | 6 | E6-05, E7-03 | Runs twice without intervention |
| E9-07 | Viva Q&A bank (25 questions) + cross-training | All | 8 | — | Each member answers any question in a mock viva |
| E9-08 | Submission checklist, PDF build, archive | Rabia | 4 | All | Submitted 48 h early |

---

## First ten tickets to open today

1. **E1-05** Freeze definitions (p95, availability, cost convention) — unblocks everything.
2. **E1-01/E1-02** Repo + tooling.
3. **E2-01** Trace download (highest external risk).
4. **E1-04** kind/KWOK smoke test on all laptops.
5. **E2-04** Price table + anchor.
6. **E3-01/E3-03** Event loop + cost ledger (gets to a trustworthy number fast).
7. **E3-07** P0 baseline (validates the ledger against the proposal's $4,672).
8. **E4-01** Forecaster (needed by both tiers).
9. **E4-02** MILP.
10. **E7-01** FastAPI app (cheap, unblocks data-plane work later).

Deferred until G2 passes: everything in E5/E6. Building a controller for a policy that has not yet beaten the baseline is the most expensive mistake available.
