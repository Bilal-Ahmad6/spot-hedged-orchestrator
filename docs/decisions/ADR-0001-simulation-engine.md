# ADR-0001: SimPy for the discrete-event testbed

**Status:** accepted (2026-11-12)

## Context

We need 30-day simulated horizons, ~2,800 runs for the pre-registered matrix, deterministic
seeding, and a model detailed enough to represent node lead time, drain windows, reclaim
events and a tail-latency SLO. A real cluster cannot provide 30-day horizons at this scale,
and a spreadsheet cannot represent queueing.

## Decision

Use **SimPy** for the discrete-event engine, wrapped in our own typed domain model
(`spothedge.model`) so the policy never imports SimPy directly.

## Consequences

- Pure Python, installs cleanly on Python 3.14, deterministic under a seeded `random.Random`.
- 30-day runs at 1-minute buckets are seconds, so the full matrix fits in a coffee break.
- We own the node lifecycle and cost accounting, which is exactly the part we must be able to
  defend. SimPy provides only the event queue and process semantics.
- Risk: SimPy's process model can obscure control flow. Mitigated by keeping processes few and
  explicit (node, workload, checkpoint) and testing each in isolation.

## Alternatives rejected

- **CloudSim Plus**: JVM, VM-level abstractions, heavier integration than the policy is worth.
- **Custom event loop**: re-implementing priority queues and process scheduling adds bug surface.
- **Kubernetes-only**: no 30-day horizons on a laptop, and no controlled interruption statistics.
