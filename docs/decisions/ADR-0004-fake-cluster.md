# ADR-0004: KWOK (+ kind) for control-plane realism

**Status:** accepted (2026-11-12)

## Context

We must show that the policy is implementable, not merely simulable. Real cloud spend is
optional and capped, and 30-day runs on real nodes are impossible. We need real API objects,
the real scheduler, the real eviction/PDB path and node lifecycle, without a kubelet per node.

## Decision

Run the controller against **KWOK** nodes (simulated kubelet) inside a real control plane,
with KWOK's metrics-server integration and `kwok.x-k8s.io/usage-cpu` annotations driving HPA.
Use **kind** with real pods and k6 only for the data-plane measurements (latency, drain,
lost requests). Keep **Karpenter's KWOK provider** as an optional adapter, not a dependency.

## Consequences

- The M3 gate is about API semantics (taint → evict → terminate, PDB, node readiness), which
  KWOK reproduces faithfully.
- KWOK **cannot** measure latency or lost requests. That limitation is explicit in the report
  and is why T3 exists.
- Metrics are declared, not measured; the trace replayer is responsible for realism, and the
  T3 calibration is the check on it.
- Risk: Karpenter's KWOK provider requires building/pushing an image. Mitigated by making the
  default actuator create `Node` objects directly.

## Alternatives rejected

- **kind only**: one real kubelet per node; 20+ nodes exhaust a laptop and cannot model launch
  latency or abrupt loss cleanly.
- **kube-scheduler-simulator**: scheduler-focused, no node/pod lifecycle over time.
- **Live cloud only**: cost, quota, and no statistical power at 30 days.
