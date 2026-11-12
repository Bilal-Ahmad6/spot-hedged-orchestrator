# Verified claims

Every load-bearing fact in the project, with the primary source it was checked
against and where it is used. If a claim is not in this table, it does not go in the
report.

Checked: **2026-11-12**. Vendor documentation drifts; re-check before submission.

| # | Claim | Source | Used in |
|---|---|---|---|
| C1 | AWS Spot interruption notice is **2 minutes**, best effort, delivered via EventBridge and instance metadata; AWS recommends polling every 5 s. Hibernation gets no 2-minute warning. | [AWS EC2 docs](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-instance-termination-notices.html) | Notice-window model, drain deadline logic |
| C2 | Azure Spot VMs are evicted with **30 seconds** notice; in-VM notifications are best effort via Scheduled Events. | [Azure Spot VMs](https://learn.microsoft.com/en-us/azure/virtual-machines/spot-vms) | Stress case, `drain_seconds` sizing |
| C3 | GCP Spot VM preemption notice is **configurable**, with **120 s recommended** for workloads needing more than 30 s. | [GCP Spot VMs](https://docs.cloud.google.com/compute/docs/instances/spot) | Justifies sweeping notice ∈ {0, 30, 120} s |
| C4 | AWS states the **average interruption frequency** across regions and instance types has historically been **< 5 %**. | [AWS Spot advisor](https://aws.amazon.com/ec2/spot/instance-advisor/) | Calibration range for `hazard_per_node_hour` |
| C5 | Spot placement scores are relative availability indicators, **not calibrated interruption probabilities**. | Proposal [9]; AWS docs describe the score as 1–10 relative availability | Why `q` is an explicit assumption, not a measured probability |
| C6 | Karpenter watches an **SQS interruption queue**, taints `karpenter.sh/disrupted:NoSchedule`, evicts via the **Eviction API respecting PDBs**, then terminates the instance; a finaliser blocks node deletion until drain completes. | [Karpenter disruption](https://karpenter.sh/docs/concepts/disruption/) | Reclaim state machine, actuator design |
| C7 | HPA default sync period is **15 s**; utilisation is computed against **requests**; the algorithm has a **10 % tolerance** and a **300 s** scale-down stabilisation window. | [HPA docs](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/) | P1 baseline implementation |
| C8 | PDBs constrain **voluntary** disruptions only; `kubectl drain` uses the Eviction API and retries rejected evictions. Direct pod deletion bypasses PDBs. | [Disruptions docs](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/) | Drain tests, why the controller must not delete pods directly |
| C9 | KWOK can run a **metrics-server** with `--enable-metrics-server`, and fake CPU usage is declared per pod via `kwok.x-k8s.io/usage-cpu`. A worked HPA example exists. | [KWOK HPA example](https://kwok.sigs.k8s.io/docs/examples/scalability/scale-using-hpa/) | T2 testbed |
| C10 | Karpenter ships a **KWOK provider** (`KWOKNodeClass`, `karpenter.kwok.sh/*` labels) that requires building and pushing an image. | [Karpenter KWOK README](https://github.com/kubernetes-sigs/karpenter/tree/main/kwok) | Why KWOK is an optional adapter, not a dependency |
| C11 | OpenCost `/allocation` accepts `window`, `aggregate`, `step`, `resolution`, `includeIdle`, `shareIdle`, and defaults to **on-demand list pricing**. | [OpenCost API](https://opencost.io/docs/integrations/api/) | Cost cross-check and its stated limitation |
| C12 | Azure Retail Prices API is **unauthenticated**; on 2026-11-12 it returned D2s/D4s/D8s v5 Linux on-demand at $0.10/$0.19/$0.38 per hour and spot at $0.02/$0.04/$0.08 — an implied **79 %** discount, median **$0.048/vCPU-h**. | [Azure Retail Prices](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices); measured by `scripts`/`spothedge prices fetch` | Price anchoring; justifies the 40–80 % sweep |
| C13 | The Azure Functions 2021 invocation trace is a 17.6 MB RAR expanding to a 305 MB text file with columns `app, func, end_timestamp, duration`; median duration 46 ms, p99 77.6 s. | Measured locally from [AzurePublicDataset](https://github.com/Azure/AzurePublicDataset); hash in `experiments/traces/README.md` | Demand series and service-time model |
| C14 | ROSS proves a **Ω(K)** lower bound for deterministic spot/on-demand policies and achieves **√K** with randomisation. | [arXiv:2601.14612](https://arxiv.org/abs/2601.14612) | Why the comparison includes adversarial market conditions |
| C15 | SkyServe's SpotHedge spreads spot replicas across failure domains, over-provisions spot, and falls back to on-demand; reports **43 %** lower cost and 2.1–2.3× better P90–P99 latency. | [arXiv:2411.01438](https://arxiv.org/abs/2411.01438) | Prior art and novelty boundary |
| C16 | SpotKube uses a **genetic algorithm** for cost-optimal cluster autoscaling with spot pricing, evaluated on a real cloud. | [arXiv:2405.12311](https://arxiv.org/abs/2405.12311) | Prior art; why we chose a constraint-based solver instead |
| C17 | PuLP 4.x removes the bundled CBC solver and the classic `LpVariable` API; `listSolvers(onlyAvailable=True)` returns empty on a clean install. | Measured locally (PuLP 4.2.0) | Dependency pin `pulp>=3.2,<4` and ADR-0002 |

## Notes on claims we deliberately do **not** make

- We do not claim a real interruption probability for any instance type. `q` is an
  assumption, and the sensitivity sweep shows what happens when it is wrong.
- We do not claim a live price. Prices are modelled inputs anchored on a date.
- We do not claim that the source trace's clock hour is meaningful; its timestamps
  are relative, so only the amplitude and weekly pattern are preserved.
