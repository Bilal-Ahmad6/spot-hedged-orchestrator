# Spot-Hedged Elastic Orchestrator

Implementation workspace for **SE-315 Cloud Computing — Track A, Assignment 1: "Spot-Hedged Elastic Orchestrator"**.

Team: Amina Nauman (505389), Bilal Ahmad (501603), Mahnoor Amjad (503202), Rabia Ashfaq (501656).

This folder currently contains the **research + build plan** produced before writing production code:

| Doc | What it is |
|---|---|
| [docs/01-research-digest.md](docs/01-research-digest.md) | Verified facts, prior art, tooling evaluation, and what each finding changes in our design |
| [docs/02-architecture.md](docs/02-architecture.md) | Testbed tiers, components, CRD, decision record, algorithms, cost/SLO models, failure behaviour |
| [docs/03-experiment-protocol.md](docs/03-experiment-protocol.md) | Baselines, traces, interruption models, metrics, run matrix, fairness rules, acceptance criteria |
| [docs/04-timeline.md](docs/04-timeline.md) | Milestone plan, scope ladder, gates, ownership, effort budget, risk register |
| [docs/05-backlog.md](docs/05-backlog.md) | Epics and tickets with estimates and definitions of done |

## The plan in one page

**What we are building.** A Kubernetes-local control loop that, every 30–60 s, forecasts CPU demand, prices the available spot/on-demand options, and chooses a node mix that minimises cost *subject to an explicit reclaim-survival constraint* — plus a decision log that makes every choice auditable.

**How we prove it without a cloud bill.** Four tiers, each proving a different thing:

| Tier | Technology | Proves | Scale |
|---|---|---|---|
| **T0** Trace & price layer | Azure Functions 2021 trace, price table, synthetic interruption models | Realistic workload + market conditions, reproducible seeds | 30 days, 1-min resolution |
| **T1** Discrete-event simulator | Python + SimPy | Policy comparison, sensitivity, statistics | 30-day run in seconds, 1,000+ runs |
| **T2** Kubernetes control plane | kind + KWOK + fake metrics-server (+ optional Karpenter KWOK provider) | The policy is implementable against the real Kubernetes API, with real scheduler, HPA, eviction and PDB semantics | Hours-long runs, tens of nodes |
| **T3** Data-plane validation | kind + real app + k6 | Real p95, real drain, real "zero lost in-flight requests" evidence | 3–6 nodes, minutes |
| **T4** Optional live cloud | AWS, ≤ US$50 credit | One credential-grade validation of the interruption path | 2 × 2-hour runs |

The simulator produces the headline numbers; the cluster proves they are not fiction; the live run (optional) proves the provider path.

**The single most important research finding.** The proposal's cost model is continuous in vCPU (30 on-demand + 48 spot = $1,366.56/mo). Real nodes are discrete, need ~0.3 vCPU of system overhead, and need one spare node's worth of headroom per pool so that draining does not itself cause an SLO violation. Re-running the same arithmetic with 8-vCPU nodes adds roughly 10–25%. That does **not** invalidate the 30% objective, but it means we must pre-register the discrete-node result and the discount level at which 30% is reachable — otherwise the final report will look like a failure when it is actually the honest answer. See [docs/01](docs/01-research-digest.md#5-what-this-changes-in-our-design) §5.3.

## Decisions needed from the team (blocking)

1. **p95 threshold.** Must be fixed *before* testing (the proposal correctly refuses to invent one). Proposed: **p95 ≤ 150 ms at ingress** for the FastAPI reference service at target throughput, measured over 1-minute windows. Alternative if the service is heavier: 250 ms.
2. **Cloud spend.** Is the optional US$50 AWS validation approved, or is the project laptop-only?
3. **Provider model.** Recommendation: **AWS** as the modelled provider (2-minute notice, mature Karpenter/NTH ecosystem), with Azure Retail Prices API used only as a free, unauthenticated price anchor. Traces and prices are deliberately decoupled; state this in the report.
4. **Scope ceiling.** There is no fixed deadline, so the constraint is effort and quality, not calendar. Confirm the target rung on the [scope ladder](docs/04-timeline.md#3-scope-ladder-how-far-to-go) — the recommendation is Tier 3 (core + controller + data plane + optional live run) and only then Tier 4.

## Immediate next actions

- [ ] Read [docs/04-timeline.md](docs/04-timeline.md) and confirm owner assignments
- [ ] Confirm the five decisions above
- [ ] Bilal: smoke-test `kind` + `kwokctl` on all four laptops (Docker/WSL2, ≥16 GB RAM, 4 cores)
- [ ] Mahnoor: download the Azure Functions trace and produce the first 30-day demand CSV
- [ ] Amina: draft the policy spec from [docs/02](docs/02-architecture.md#7-algorithms) §7
- [ ] Rabia: stand up the decision-record schema and runbook skeleton
