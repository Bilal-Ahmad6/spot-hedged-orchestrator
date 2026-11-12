# Experiment Protocol

Written **before** running anything, so that the final report cannot be accused of choosing the analysis after seeing the results. If we deviate, the deviation is recorded in the report with a reason.

---

## 1. Hypotheses → objectives

| ID | Hypothesis | Proposal objective | Primary evidence |
|---|---|---|---|
| **H1** | The hedged policy reduces monthly compute cost by ≥30% vs. an on-demand HPA+CA baseline at a 65% spot discount, under discrete node packing. | O1 (cost) | T1 primary matrix; T3 spot-check |
| **H2** | At a 65% discount, 30% is **not** reachable once drain headroom is included; it becomes reachable at ≥75%. | O1 (disclose smaller savings) | T1 discount sweep + headroom ablation |
| **H3** | Availability stays ≥99.9% across independent, correlated and peak-hour interruptions, given a correctly provisioned on-demand floor. | O2 (service quality) | T1 + T2 |
| **H4** | With notice ≥ 30 s, in-flight request loss is zero for planned drains; with 0 s notice, loss is non-zero and predictable by Little's law. | O3 (response) | T3 drain tests + T1 formula |
| **H5** | Every decision is replayable from its record: same inputs ⇒ same plan. | O4 (explainability) | Property test over 10 k random records |
| **H6** | The same policy binary drives the simulator, KWOK and kind without code changes. | O5/O6 (lifecycle, comparison) | T2/T3 runs use `src/spothedge/policy` unmodified |

H2 is deliberately self-critical. Pre-registering it converts a likely reviewer objection ("your 33% was optimistic") into a finding.

---

## 2. Baselines (exact definitions)

All policies share: trace, seeds, node catalogue, price table, `h`, `leadTime`, `drainHeadroom`, PDB, pod CPU request, HPA parameters, and interruption model. Only the *purchasing/allocation rule* differs.

| Policy | Rule | Why it is the right comparator |
|---|---|---|
| **P0 — Static peak** | 160 vCPU on-demand, always on | The "do nothing clever" reference from the proposal's Table 4 |
| **P1 — On-demand HPA + CA** | Single Deployment; HPA target 70% CPU, 15 s sync, 300 s down-stabilisation; node autoscaler adds/removes on-demand nodes at `leadTime` | The state of practice, and the baseline objective 1 names |
| **P2 — Fixed spot ratio** | 70/30 spot/on-demand split held constant, replicas follow demand | Tests whether *any* spot use is enough; the proposal's "fixed-spot-ratio baseline" |
| **P3 — Hedged (ours)** | MILP each tick with survival, floor, diversity, lead-time and drain constraints | The contribution |
| **P4 — Oracle (upper bound)** | Perfect foresight of demand and interruptions, same constraints | Separates "policy is bad" from "forecasting is hard"; never presented as achievable |

P1 must be implemented with the *real* HPA algorithm (not a hand-waved "scale to demand"), including the 10% tolerance and the scale-down window; otherwise P1 is a straw man. In T1 this is a faithful reimplementation; in T2 it is the actual `autoscaling/v2` object.

---

## 3. Demand trace

**Source:** Azure Functions Invocation Trace 2021 (Azure Public Dataset), per-minute invocation counts ([dataset](https://github.com/Azure/AzurePublicDataset)). It supplies realistic burstiness and weekday/weekend structure.

**Construction**

1. Select one high-volume function (or aggregate the top decile), producing a per-minute series over 14 days.
2. Remove the absolute scale; keep the **shape** (normalise to its own mean).
3. Re-scale to the proposal's envelope: daily min 40 vCPU, daily max 160 vCPU, mean ≈ 70 vCPU.
4. Tile to 30 days, preserving two weekday/weekend cycles; add no synthetic noise beyond what the trace already contains.
5. Freeze as `experiments/traces/demand_30d.csv` with a content hash. Every experiment records the hash.

**Sanity checks:** mean within 70 ± 3 vCPU; p95 of the daily max ≈ 155–160; at least 20 ramp events with slope > 2 vCPU/min; no negative values; exactly 43 200 rows at 1-min resolution.

**If the trace cannot be downloaded** (the dataset has had availability problems), fall back to a documented synthetic profile: `D(t) = 100 + 55·sin(2π(t−9)/24) + 8·weekday_factor + AR(1) noise`, and say so in the report. Do **not** silently substitute.

---

## 4. Price model

- Base on-demand: US$0.04/vCPU-hour (proposal assumption), cross-checked against Azure Retail Prices API for a comparable SKU on the run date; record the comparison.
- Spot: `price = on_demand × (1 − discount)`, with `discount ∈ {0.40, 0.50, 0.61, 0.65, 0.75, 0.80}`.
  - 0.61 is the proposal's break-even-for-30%-saving point; 0.65 is the base case; 0.80 stress-tests the upside.
- Instance catalogue: 2, 4, 8, 16 vCPU; allocatable = vCPU − 0.3 (system overhead); price per node = vCPU × per-vCPU price × 1.0 (no size discount — state this assumption).
- No egress, storage, control-plane, or NAT charges; excluded consistently from every policy (as the proposal does).
- Prices are **static per run** except in the "volatile price" sensitivity slice (±20% sinusoid, 6 h period), because real spot prices move and a policy that only works on constant prices is fragile.

---

## 5. Interruption models

All models draw from a seeded RNG and are independent of policy.

| Model | Description | Parameters |
|---|---|---|
| **I1 Independent** | Per-node Poisson reclaim, hazard `λ_pool`; notice drawn from {30, 120} s; no correlation | `λ` calibrated so expected reclaims ≈ 1.5–4% of node-hours (AWS's published "<5% average") |
| **I2 Correlated** | Common-mode event: with probability `p_c` per hour, **all** spot pools lose `q` of capacity simultaneously | `p_c = 0.02/h`, `q ∈ {1/6, 1/3, 1/2, 1}` |
| **I3 Peak-correlated** | I2 restricted to the daily peak window (top 10% of demand), where the on-demand floor is most expensive | Peak window from the trace |
| **I4 Abrupt** | Notice = 0 s for a fraction `f_abrupt` of reclaims (represents a missed event or a provider without advance notice) | `f_abrupt ∈ {0, 0.1, 0.5}` |

The `q = 1` case is mandatory: it is the proposal's own stress test and must produce either a compliant plan (all on-demand) or a documented SLO failure. Both outcomes are acceptable; hiding the case is not.

---

## 6. Metrics (definitions used verbatim in the report)

| Metric | Definition | Instrument |
|---|---|---|
| Monthly cost | Σ node-seconds × price / 30 days × 730 h | Cost ledger (T1/T2), OpenCost cross-check (T3) |
| Availability | `1 − failed/total` requests; a failed request is a non-2xx/3xx, a timeout, or a connection reset | k6 (T3), analytic (T1) |
| SLO violation minutes | Minutes where the 1-min p95 exceeds 150 ms, plus minutes with zero capacity | Prometheus / model |
| Lost in-flight requests | Requests that were open when a pod died without completing | k6 `http_req_failed` during drain windows + request counter deltas |
| Recovery time | Interrupt signal → capacity ≥ plan (or success rate back to baseline), seconds | Event log |
| Reclaim response time | Notice → last pod on node terminated, seconds | Event log |
| Forecast MAPE / P90 coverage | Mean absolute percentage error; fraction of actuals ≤ P90 | Forecaster diagnostics |
| Audit completeness | Fraction of ticks with a schema-valid decision record | Log validator |
| Churn | Node launches + terminations per day | Cost ledger |
| Constraint slack | `survivalSlack` per tick (vCPU) | Decision log |

Averaging rules: report **mean and 95% CI across 20 seeds**, plus the **worst seed**. Never report only the best run. Percent changes are computed per seed and then averaged (paired), not from averaged raw values.

---

## 7. Run matrix

**Primary (answers H1/H3/H4)** — `4 policies × 3 interruption models (I1,I2,I3) × 5 discounts × 20 seeds = 1,200 runs` at `q = 1/3`, `h = 0.15`, notice = 120 s, 30 days.

**Headroom/feasibility (H2)** — `P1, P3 × {0, 8, 16} vCPU drain headroom × {0, 0.15, 0.30} h × 5 discounts × 20 seeds = 900 runs`.

**Sensitivity (secondary)** — `P3 only × q ∈ {1/6,1/3,1/2,1} × leadTime ∈ {30,90,180} s × notice ∈ {0,30,120} s × 10 seeds = 360 runs`; plus volatile-price slice (120 runs).

**Ablation** — remove each of {drain headroom, diversity β, lead-time shift, on-demand floor} one at a time; `4 × 3 discounts × 20 seeds = 240 runs`.

**Cluster validation** — T2: 3 runs × 4 h (independent, correlated, peak). T3: 6 runs × 20 min (3 loads × 2 notice windows). T4 (optional): 2 runs × 2 h.

Total simulator runs ≈ 2,820; at ~2 s single-core this is ~95 min on one core, ~25 min on four. That is cheap enough to re-run everything after a bug fix — which is the real requirement.

---

## 8. Fairness checklist (tick before every primary run)

- [ ] Same trace file **hash** for all policies
- [ ] Same seed list for all policies
- [ ] Same node catalogue and instance prices
- [ ] Same `h`, `leadTime`, `drainHeadroom` for P1–P3
- [ ] Same pod CPU request and PDB
- [ ] HPA parameters identical to the Kubernetes defaults unless stated
- [ ] Interruption events generated **once per seed** and replayed to all policies (common random numbers)
- [ ] Cost convention identical (node-seconds, no egress)
- [ ] No policy allowed to exceed `maxNodes` or quota
- [ ] Oracle clearly labelled as an upper bound

Common random numbers are the single biggest variance reducer here; without them, a 5% difference between policies can be pure noise.

---

## 9. Analysis plan

1. Paired per-seed differences (P3 − P1) for cost, availability, violation minutes.
2. Mean difference with 95% CI from 10 k bootstrap resamples over seeds.
3. Effect size (percent) and the **distribution** of per-seed savings — a policy that wins on average but loses on 30% of seeds is a different claim from a consistent winner.
4. For the discount sweep, report the **discount at which 30% is reached** with CI, not just the base-case number.
5. Failure analysis: every seed where availability < 99.9% is inspected individually and classified (infeasible constraint, late provisioning, correlated loss at peak, forecast miss). This table is likely to be the most interesting part of the report.
6. Figures: (a) cost vs. discount by policy; (b) cost-vs-availability Pareto; (c) time series of capacity mix and p95 during one correlated event; (d) CDF of per-seed savings; (e) constraint slack over a day; (f) forecast vs. actual.

No p-hacking: the primary endpoints are H1/H3/H4 and are fixed here. Everything else is labelled exploratory.

---

## 10. Acceptance criteria

| # | Criterion | Pass condition | If it fails |
|---|---|---|---|
| A1 | Reproducibility | `make experiment` reproduces the primary table bit-for-bit from seeds | Block release; this is non-negotiable |
| A2 | Cost | ≥30% saving vs. P1 at some discount in {0.61…0.80}, with CI excluding 0 | Report the achieved discount threshold and the shortfall |
| A3 | Availability | ≥99.9% (≤43.2 min/month) for P3 under I1 and I2 at `q ≤ 1/2` | Report the failing model and the mechanism |
| A4 | Abrupt loss | Documented, non-zero loss rate with 0 s notice; zero with ≥30 s notice on planned drains | If zero is not achieved at 30 s, report the measured loss and why |
| A5 | Explainability | 100% of ticks produce schema-valid records; replay of 1,000 records yields identical plans | Fix before demo |
| A6 | Portability | Same policy module runs in T1, T2, T3 (checked by import hash) | Refactor; the claim is central |
| A7 | Cluster evidence | T2 run shows node mix changing in response to injected reclaim; T3 shows drain with no failed requests | Reduce scope to T1 + T2 and say so |
| A8 | Lifecycle | Teardown script deletes all resources and emits a spend report | Complete before submission |

A2 is intentionally "at some discount", not "at 65%", because H2 predicts 65% will not suffice under discrete packing. The report must be explicit about which of these is the headline.

---

## 11. Threats to validity

| Threat | Direction | Mitigation / disclosure |
|---|---|---|
| Simulator fidelity | Overstates policy benefit (idealised scheduling) | T2/T3 cross-checks; report the gap |
| Analytic latency model | Could understate tail latency | Calibrate against T3; report error; fall back to empirical curve |
| Price assumptions | Savings sensitive to discount | Full sweep; report break-even discount |
| Trace provenance | Azure shape ≠ our service | State clearly that only the shape is borrowed; publish the transformed CSV |
| Discrete node packing | Reduces savings vs. proposal | Pre-registered as H2; reported as a finding |
| Small live sample | No statistical power from T4 | T4 is illustrative only; never used for the cost claim |
| Laptop hardware variance | T3 p95 varies by machine | Pin CPU quota in pod specs; report machine specs and run each config 3× |
| No real capacity errors | Policy may look more available than reality | Model launch failure probability in a sensitivity slice; state the omission |

---

## 12. Reproducibility contract

Every run writes a directory:

```
experiments/runs/<experimentId>/
├── config.resolved.yaml     # after defaults + CLI overrides
├── demand.csv.sha256
├── prices.json
├── interruptions.jsonl      # exact events, seeded
├── decisions.jsonl          # one record per tick
├── summary.json             # headline metrics + CIs
└── env.txt                  # git SHA, python version, package lock hash
```

`make verify` re-runs three fixed cells and diffs `summary.json`. CI runs it on every push. A result that cannot be regenerated does not go in the report.
