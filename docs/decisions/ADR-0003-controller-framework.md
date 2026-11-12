# ADR-0003: kopf for the Kubernetes controller

**Status:** accepted (2026-11-12)

## Context

The controller needs a CRD, a periodic reconcile loop (30–60 s), event handlers for node
deletion and interruption annotations, and structured logging. The team writes Python; the
timeline does not reward learning controller-runtime scaffolding.

## Decision

Use **kopf** (Python operator framework) with a `HedgedService` CRD, timer-based ticks and
handlers for node/annotation events.

## Consequences

- Declarative handlers keep the policy call site obvious: `plan = allocate(...)`, then
  `actuator.ensure(plan)`.
- Runs equally well against kind, KWOK and a real cluster; no code change per environment.
- Risk: kopf's async model can hide blocking calls. Mitigated by a bounded solver timeout and
  a hard rule that no handler performs network I/O without a timeout.
- Risk: kopf lags Kubernetes API versions. Mitigated by pinning `kubernetes`/`kopf` in the
  lockfile and testing against the cluster version we actually run.

## Alternatives rejected

- **controller-runtime (Go)**: excellent, but weeks of scaffolding for a 60 s loop.
- **Shell/CronJob**: no state, no event handling, untestable.
- **Kubernetes Operator SDK (Python/Ansible)**: heavier than needed and less direct than kopf.
