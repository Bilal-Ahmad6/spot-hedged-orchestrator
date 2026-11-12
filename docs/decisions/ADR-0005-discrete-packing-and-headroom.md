# ADR-0005: Discrete node packing and drain headroom in the capacity constraint

**Status:** accepted (2026-11-12)

## Context

The proposal models cost continuously in vCPU: 30 on-demand + 48 spot vCPU at US$0.04 and
US$0.014 per vCPU-hour gives $1,366.56/month and a 33.1% saving. Real capacity is bought in
whole nodes, has ~0.3 vCPU of system overhead, and needs spare room so that draining a node
does not evict pods into a full cluster.

## Decision

Model capacity as integer node counts, subtract system overhead from allocatable vCPU, and
add a **drain headroom** term equal to the largest node we are willing to lose:

```
D_eff = D̂_p90(t + leadTime) · (1 + h) + drainHeadroomVcpu
C_od + (1 − q) · C_spot ≥ D_eff
```

Log `D_eff`, `survivalSlack` and `drainHeadroomVcpu` in every decision record.

## Consequences

- Worked example (8-vCPU nodes, 7.7 allocatable): the hedge rises from $1,366.56 to $1,506.72
  without headroom, and to $1,822.08 with one spare node per pool; the discrete on-demand
  baseline rises from $2,044 to $2,336. The honest saving at a 65% discount is ~22%, not 33%.
- This is recorded as hypothesis **H2** in the experiment protocol and pre-registered before
  any result exists, so the report presents it as a finding rather than a failure.
- The survival constraint now also protects against the policy's own scale-downs, not just
  against provider reclaims.

## Alternatives rejected

- **Continuous vCPU**: matches the proposal's arithmetic but cannot be implemented and
  overstates savings by 10–25%.
- **Drain headroom omitted**: cheaper on paper, but produces SLO violations caused by the
  autoscaler itself, which is an indefensible experimental design.
