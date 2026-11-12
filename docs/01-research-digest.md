# Research Digest

**Purpose.** Everything below was checked against primary sources (vendor docs, the papers themselves, project repositories) rather than recalled. Each finding ends with *what it changes* in our build. The goal is that no design choice in this project is defensible only by "it seemed reasonable".

---

## 1. The problem, restated as an engineering target

We are not building "a cheaper autoscaler". We are building a **policy** that answers one question every decision tick:

> Given a forecast demand distribution, a price for each capacity type, an interruption model with a notice window, and a service whose p95 must stay under a threshold — which node mix minimises cost while surviving the loss of spot capacity?

That is a constrained stochastic allocation problem wrapped in a control loop. Three consequences follow:

1. **The policy is the contribution**, not the YAML. The actuator (Kubernetes, Karpenter, KWOK) is a replaceable dependency.
2. **The constraint must be falsifiable.** "Reclaim-survival" has to be written as an inequality whose slack we log every tick, and whose violation we can demonstrate in a test (q = 1, loss at peak).
3. **Every number must be reproducible** from a seed, a trace file, and a price table — otherwise the comparison is a demo, not an experiment.

---

## 2. Prior art: what exists, what we reuse, what is left

| System | What it actually does | What we reuse | What it leaves open for us |
|---|---|---|---|
| **SkyServe / SpotHedge** (EuroSys '25) | Spreads spot replicas across regions/clouds, overprovisions cheap spot replicas, dynamically falls back to on-demand when spot replicas are lost. Reports 43% lower cost than on-demand and 2.1–2.3× better P90/P99 latency. | The *idea* of an overprovisioned spot tier plus a dynamic on-demand fallback, and the formula-shaped rule "keep `N_Tar + N_Extra` spot replicas ready, launch on-demand when `S_ready` falls short". | It is a **multi-region serving system for AI models**, with a global load balancer and a service controller. It does not expose a Kubernetes-local node-purchasing policy with a per-tick, auditable cost/SLO margin, and it does not study the discrete-node + drain-headroom problem for CPU web services. |
| **SpotKube** (CloudCom '24) | Application-characterisation tool + elastic cluster autoscaler using a **genetic algorithm** over spot pricing, deployed on a real public cloud. | The two-layer decomposition (characterise the app once → autoscale with an optimiser), and the evaluation style (compare against alternative optimisation strategies). | Genetic search gives no constraint-slack guarantee and no per-decision explanation. We need a convex/integer program whose duals and slack are loggable, and which can prove infeasibility instead of returning a mediocre genome. |
| **ROSS** (INFOCOM '26) | Proves any deterministic spot/on-demand policy has competitive ratio Ω(K) (K = price ratio), and gives a randomised policy achieving √K for deadline-constrained jobs. | A theoretical anchor: it explains *why* naive thresholds lose, and gives us a defensible reason to evaluate against worst-case market conditions rather than only the average. | Jobs with deadlines, not long-running replicated services with tail-latency SLOs. Our constraint is availability + p95, not job completion. |
| **Kubernetes HPA / Cluster Autoscaler** | HPA scales replicas from metrics (15 s sync, ~10% tolerance, default 300 s scale-down stabilisation). CA adds nodes when pods are unschedulable. | The **baseline we must beat**, and its exact parameters, so the comparison is fair. | Purely reactive; no notion of purchasing options, price, or reclaim risk. |
| **Karpenter** | Just-in-time node provisioning; handles interruption by watching an **SQS queue**, taints `karpenter.sh/disrupted:NoSchedule`, evicts via the Eviction API (respecting PDBs), then terminates the instance. | The **production actuator pattern** we imitate: taint → evict → terminate, with a finaliser so a node object cannot vanish before drain. | It decides *when to replace capacity*, not *what spot/on-demand mix to buy under an SLO constraint*. It is also provider-specific. |
| **AWS Node Termination Handler** | Watches interruption/maintenance events, cordons, then drains the node. | The reclaim-signal handler shape (event → cordon → drain). | Same gap: no purchasing policy, no cost/SLO audit trail. |
| **OpenCost** | Real-time/historical Kubernetes cost allocation via `/allocation`. Defaults to **on-demand list pricing** unless you supply cloud cost data. | Cost observability and an independent cross-check of our own ledger in the real-cluster tier. | It measures spend; it does not choose an allocation. And it will not produce meaningful spot prices in a simulated cluster — see §5.4. |
| **CloudSim Plus spot modelling** (2025) | Trace-driven simulation of spot marketplaces and scheduling. | Justification that trace-driven spot simulation is an accepted method, and a sanity check on our event model. | General-purpose cloud simulator, not a Kubernetes control-loop testbed; wiring our policy into it would cost more than a focused SimPy model. |

**Novelty boundary (unchanged from the proposal, now sharper).** The contribution is a *Kubernetes-local, per-tick, auditable allocation policy* for CPU web services, with (a) an explicit reclaim-survival inequality, (b) discrete node packing with drain headroom, (c) a decision record that a reviewer can replay. Spot/on-demand hedging itself is explicitly **not** claimed as new.

---

## 3. Verified facts that constrain the design

### 3.1 Interruption notice windows

| Provider | Notice | Source | Design consequence |
|---|---|---|---|
| **AWS EC2 Spot** | **2 minutes**, best effort, delivered via EventBridge event and instance metadata; AWS recommends polling every 5 s. Hibernation gets no 2-minute warning. | [AWS docs](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-instance-termination-notices.html) | 120 s is enough for a 20–40 s drain *if* the controller is watching. This is the "easy mode" case and the one we should demo. |
| **Azure Spot VM** | **30 seconds**, best effort, via Scheduled Events. | [Azure docs](https://learn.microsoft.com/en-us/azure/virtual-machines/spot-vms) | Enough to stop accepting traffic and finish short requests, not enough to migrate state. Forces a small pod termination grace period and a fast readiness flip. |
| **GCP Spot VM** | Preemption notice is **configurable**, with **120 s recommended** for workloads that need longer than 30 s. | [GCP Spot VMs](https://docs.cloud.google.com/compute/docs/instances/spot) | Validates the proposal's "optional 120 s" claim. Also means the notice window is a *policy parameter we choose*, not a constant — good for the sensitivity study. |

**What it changes.** The notice window must be a first-class experiment factor `{0, 30, 120} s`, with 0 s representing the worst case where the controller only sees the node disappear. Our state machine must have a **deadline-aware branch**: if `notice_window < estimated_drain_time`, do not attempt a graceful drain of that node; instead fail traffic over first (readiness flip), then let the node die, and account for the loss explicitly. Pretending a 0 s notice can be drained gracefully would be dishonest and easy for an examiner to catch.

### 3.2 How often reclamation actually happens

- AWS states the **average interruption frequency across all regions and instance types has historically been < 5%**, varying by region, instance type and time ([AWS Spot](https://aws.amazon.com/ec2/spot/instance-advisor/)).
- **Spot placement scores are relative 1–10 availability indicators, not calibrated interruption probabilities.** The proposal already says this; the research confirms it. We must never convert a placement score into a hazard rate and call it a probability.
- **SpotLake** (IISWC '22) archives historical spot **price, availability and interruption-ratio** datasets, precisely because vendor APIs expose little history ([arXiv:2202.02973](https://arxiv.org/abs/2202.02973)). Treat it as an optional calibration source, not a dependency — its service availability is not guaranteed.

**What it changes.** We parameterise the interruption model explicitly rather than pretending to know it: `λ_spot` per pool-hour (baseline calibrated so that expected loss ≈ a few percent per day), `q` = simultaneous-loss fraction, `p_correlated`, plus a peak-hour multiplier. Sensitivity over λ, not a single guess. This also protects us in the viva: "we did not claim to know the true rate, we showed the policy's behaviour across the plausible range."

### 3.3 What "spot discount" can honestly be claimed

- GCP advertises **up to 91%** off on-demand for Spot VMs ([GCP](https://docs.cloud.google.com/compute/docs/instances/spot)).
- The proposal's 65% base assumption is therefore *plausible but not universal*, and its own sensitivity table (break-even at 16.67%) is the right response.
- **Azure Retail Prices API is free and unauthenticated**, which makes it the only provider whose prices we can pull programmatically without an account ([Azure Retail Prices](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)). AWS and GCP price APIs require credentials or a billing account.

**What it changes.** Prices are **inputs to the simulator**, not live dependencies. We ship `prices/base.yaml` with an anchored on-demand table (cross-checked against Azure Retail API where possible) and an explicit `spot_discount` factor swept from 40% to 80%. The report must say: "modelled prices, anchored on date X, not a quote."

### 3.4 Kubernetes mechanics we must get right

- **HPA**: default sync period 15 s; utilisation is computed against **requests**, not limits; the algorithm scales by `desired = ceil(current × currentMetric / targetMetric)` with a ~10% tolerance and a 300 s scale-down stabilisation window by default ([HPA docs](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/)).
- **PDB + Eviction API**: PDBs constrain *voluntary* disruptions only; `kubectl drain` retries evictions rather than deleting pods. Direct pod deletion bypasses PDBs entirely ([Disruptions docs](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)).
- **Karpenter termination**: finaliser → taint `karpenter.sh/disrupted:NoSchedule` → evict respecting PDBs → wait for full drain → terminate instance ([Karpenter disruption docs](https://karpenter.sh/docs/concepts/disruption/)).

**What it changes.** Two things that will otherwise silently ruin the evaluation:

1. **Drain headroom is mandatory.** If the cluster is packed to exactly the forecast demand, every scale-down or reclaim event evicts pods with nowhere to go, and the *policy's own housekeeping* creates the SLO violation. The capacity constraint must be `D(1+h) + C_drain`, where `C_drain` is the largest node we are willing to lose. We log `C_drain` as part of the decision.
2. **Fairness rules for the baseline.** Same headroom, same node catalogue, same lead time, same PDB, same HPA parameters for all policies. Otherwise the "30% cheaper" claim is an artefact of giving our policy more slack.

### 3.5 Simulating Kubernetes without a cloud account

This is the finding that makes the project feasible on four laptops.

- **KWOK** (Kubernetes WithOut Kubelet, SIG Scalability) simulates node and pod lifecycle. `kwokctl create cluster --enable-metrics-server --config metrics-usage.yaml` gives a working metrics-server, and fake CPU usage is set per-pod via the annotation `kwok.x-k8s.io/usage-cpu`. The project publishes a **worked HPA example**, including the exact patch commands to drive a scale-up and observe the HPA event ([KWOK HPA example](https://kwok.sigs.k8s.io/docs/examples/scalability/scale-using-hpa/)).
- **Karpenter has a KWOK cloud provider** (`KWOKNodeClass`, labels `karpenter.kwok.sh/instance-type`, `-instance-cpu`, etc.), so the real Karpenter provisioning/disruption controllers can run against fake nodes ([kwok/README](https://github.com/kubernetes-sigs/karpenter/tree/main/kwok)). Caveat: it expects you to build and push an image, and it is a development provider — budget a timeboxed spike, not a hard dependency.
- **Limitation**: KWOK's metrics are *declared*, not measured. There is no real kubelet, no cgroup, no network. So KWOK can validate the control plane (scheduling, eviction, PDB, node lifecycle, HPA arithmetic) but **cannot measure latency or lost requests**. Those need tier T3.

**What it changes.** The architecture becomes a deliberate split: **KWOK for control-plane realism at scale, kind with real pods for data-plane truth, SimPy for 30-day statistics.** One testbed cannot do all three, and pretending otherwise is the most likely way this project fails.

### 3.6 Cost observability

- OpenCost's `/allocation` API supports `window`, `aggregate` (including `label:...`), `step`, `resolution`, `includeIdle`, `shareIdle` ([OpenCost API](https://opencost.io/docs/integrations/api/)). Default pricing is **on-demand list price**.
- In a KWOK cluster there are no real instances and often no cloud pricing feed, so OpenCost will not produce the spot/on-demand split we need.

**What it changes.** Our own **cost ledger** is authoritative: `cost = Σ over nodes Σ node-seconds × price(instance_type, capacity_type, timestamp)`. It is exact, auditable, and identical in simulator and cluster. OpenCost is used in T3 as an independent sanity check on the on-demand portion, and as a dashboard for the demo. Do not make OpenCost the source of truth for the headline cost numbers.

---

## 4. Tooling evaluation

| Need | Chosen | Why | Rejected alternative |
|---|---|---|---|
| Discrete-event simulation | **SimPy** (Python) | Mature, deterministic with seeded RNG, easy to unit-test; the team already writes Python | CloudSim Plus (Java, heavy, geared to VM-level cloud sim); custom event loop (needless risk) |
| Optimisation | **PuLP + CBC** | Tiny integer programs (≤ dozens of variables); human-readable model; CBC ships with PuLP | Genetic algorithm (no slack/duality, non-deterministic); hand-rolled greedy (fragile at boundaries) |
| Kubernetes operator | **kopf** (Python) | Declarative handlers, minimal boilerplate, good for a 30–60 s reconcile loop; 1,100+ indexed snippets | Go controller-runtime (too much scaffolding for the timeline); shell scripts (no state, untestable) |
| Fake cluster | **kwokctl + metrics-server** | Real API server + scheduler + controllers; worked HPA example | k3d only (real kubelet, too heavy for 30-day runs); kube-scheduler-simulator (scheduler-focused, no node lifecycle) |
| Data-plane test | **kind + k6** | Real containers, real HTTP, real eviction; k6 gives p95 and error counts natively | Locust (Python GIL limits high-rps tests); vegeta (less scriptable) |
| Metrics | **Prometheus + Grafana** | Standard, and HPA/KWOK/Prometheus integrate cleanly | Custom CSV-only instrumentation (no demo value) |
| Charts | **matplotlib** | Deterministic, scriptable, no notebook state | Excel (not reproducible) |

---

## 5. What this changes in our design

### 5.1 Three logical pools, two Deployments, one actuator interface

The proposal's Figure 1 has three pools (on-demand floor, spot A, spot B). Implement that literally:

- `svc-od` Deployment → `nodeSelector: pool=on-demand`
- `svc-spot` Deployment → `nodeSelector: pool in (spot-a, spot-b)` with a topology-spread constraint across pools
- one Service in front of both, with readiness gating

Then **capacity** is a node-pool decision and **replica count** is a consequence (`replicas = floor(allocatable_cpu / pod_cpu_request)`), which keeps the policy's objective linear and the actuator replaceable (`kwok-node` adapter by default, `karpenter` adapter optional).

### 5.2 The constraint gets two extra terms

Proposal Eq. (1): `C_OD + (1−q)·C_S ≥ D(1+h)`.

We keep it and add:

```
C_OD + (1−q)·C_S  ≥  D̂_90(t+L)·(1+h) + C_drain          (survival + drain headroom)
C_OD              ≥  max(D_floor, C_S_max_node)          (fast-failover floor)
Σ_{spot in one pool/AZ} ≤ β · C_S                        (diversity, β ≈ 0.6–0.7)
```

where `L` is the provisioning lead time (node launch → Ready → pod Ready). Without `L`, the policy always provisions one tick too late at the morning ramp; this is the most common way simulated autoscalers look better than real ones.

### 5.3 The cost model must be discrete — and the headline number will move

Worked example with 8-vCPU nodes, 7.7 vCPU allocatable after system overhead, same prices as the proposal (US$0.04 on-demand, US$0.014 spot per vCPU-hour, 730 h/month):

| Model | On-demand | Spot | Monthly | vs. autoscaled on-demand |
|---|---|---|---|---|
| Proposal, continuous vCPU | 30 vCPU | 48 vCPU | **$1,366.56** | −33.1% |
| Discrete: ceil(30/7.7)=4 nodes, ceil(48/7.7)=7 nodes | 32 vCPU | 56 vCPU | **$1,506.72** | −35.5% vs. $2,336 discrete baseline |
| Discrete + 1 drain-headroom node per pool | 40 vCPU | 64 vCPU | **$1,822.08** | −22.0% |

And the discrete on-demand baseline itself rises: `ceil(70/7.7)=10` nodes → 80 vCPU → **$2,336/mo**, not $2,044.

**Implication.** At a 65% discount, the honest expectation is **~20–25% saving**, not 33%. The 30% objective is reachable at higher discounts (≥ ~75%) or with larger instance types/finer packing. We pre-register this now, and the report states the discount at which 30% is achieved — which is exactly what objective 1 asks for ("disclose smaller savings ... at other discount levels"). This is a strength, not a failure, provided we are the ones who surface it.

### 5.4 OpenCost is a cross-check, not the ledger

Headline cost comes from our node-seconds ledger. OpenCost appears in the report as an independent measurement in the real-cluster tier, with an explicit note that it defaults to on-demand list pricing and therefore *overstates* the cost of spot nodes unless custom pricing is loaded.

### 5.5 Latency has to be modelled, then calibrated

Thirty days at ~100 rps is ~260 M requests — request-level simulation is not viable. Use a **fluid capacity model with an analytic tail**:

- per replica, service time `S ~ LogNormal(mean 40 ms, cv 1.2)` (calibrate in T3)
- per 10 s bucket, compute offered load `ρ = λ·E[S]/c` and p95 via Erlang-C with the Allen–Cunneen correction for `G/G/c`
- when `ρ ≥ 1` or capacity is zero, requests queue/fail and the bucket contributes to SLO-violation minutes

Validate this model against the real k6 run for 2–3 hours; report the error. If the model is off by more than ~15% at p95, say so and use the empirical curve instead.

### 5.6 Lost in-flight requests have a clean formula

By Little's law, a replica serving `λ_r` rps with mean service time `E[S]` has `λ_r·E[S]` requests in flight. On an abrupt loss with no notice, essentially all of them are lost; on a drain with `notice ≥ drain_time`, zero are. This gives us a testable prediction:

```
lost_per_reclaim ≈ λ_r · E[S] · 1{notice_window < drain_time}
```

Objective 3 becomes measurable rather than aspirational, and the 0 s-notice case gives us a non-zero number we can report honestly.

---

## 6. Things we could not verify (state these as limitations)

1. **Real interruption rates for our chosen instance types/regions** — we use a calibrated range, not measurements. SpotLake may help; it is not guaranteed available.
2. **Real node startup latency** on the provider — modelled as 60–180 s, which matches common experience but is not measured by us.
3. **Whether the KWOK-Karpenter provider builds cleanly on all four laptops** — timeboxed spike during M0/M1, with a documented fallback (our own node actuator).
4. **Actual spot availability** (capacity errors on launch) — modelled as a probability, not observed.

Each of these belongs in the "Threats to validity" section of the final report. Claiming otherwise is the easiest way to lose marks in a viva.

---

## 7. Sources

**Papers**

1. Z. Mao et al., *SkyServe: Serving AI Models across Regions and Clouds with Spot Instances*, EuroSys '25. https://arxiv.org/abs/2411.01438
2. D. Edirisinghe et al., *SpotKube: Cost-Optimal Microservices Deployment with Cluster Autoscaling and Spot Pricing*, CloudCom '24. https://arxiv.org/abs/2405.12311
3. N. Bhuyan et al., *Exploiting Spot Instances for Time-Critical Cloud Workloads Using Optimal Randomized Strategies*, INFOCOM '26. https://arxiv.org/abs/2601.14612
4. S. Lee et al., *SpotLake: Diverse Spot Instance Dataset Archive Service*, IISWC '22. https://arxiv.org/abs/2202.02973
5. C. Goldgruber et al., *Simulating Dynamic Cloud Marketspaces ... with CloudSim Plus*, 2025. https://arxiv.org/abs/2511.18137

**Provider documentation**

6. AWS — *Spot Instance interruption notices*. https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-instance-termination-notices.html
7. Azure — *Azure Spot Virtual Machines*. https://learn.microsoft.com/en-us/azure/virtual-machines/spot-vms
8. GCP — *Spot VMs* (preemption + configurable notice). https://docs.cloud.google.com/compute/docs/instances/spot
9. Azure — *Retail Prices API* (unauthenticated). https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices

**Kubernetes ecosystem**

10. Kubernetes — *Horizontal Pod Autoscaling*. https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/
11. Kubernetes — *Disruptions* (PDB, Eviction API). https://kubernetes.io/docs/concepts/workloads/pods/disruptions/
12. Karpenter — *Disruption* (SQS, taint, evict, finaliser). https://karpenter.sh/docs/concepts/disruption/
13. Karpenter — *KWOK provider*. https://github.com/kubernetes-sigs/karpenter/tree/main/kwok
14. KWOK — *Horizontal pod autoscaling example*. https://kwok.sigs.k8s.io/docs/examples/scalability/scale-using-hpa/
15. KWOK — *Metrics server example*. https://kwok.sigs.k8s.io/docs/examples/metrics-server/
16. OpenCost — *API*. https://opencost.io/docs/integrations/api/
17. AWS — *Node Termination Handler*. https://github.com/aws/aws-node-termination-handler
18. Microsoft — *Azure Public Dataset* (Functions 2021 trace). https://github.com/Azure/AzurePublicDataset
