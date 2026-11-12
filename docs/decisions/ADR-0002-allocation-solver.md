# ADR-0002: PuLP/CBC for the allocation model

**Status:** accepted (2026-11-12)

## Context

Each decision tick must choose integer node counts across three pools and four instance
types subject to a survival inequality, an on-demand floor, a diversity cap, quotas and a
node limit. We must also be able to report **why** a plan was chosen, and to distinguish
"infeasible" from "expensive".

## Decision

Formulate the tick as a small integer program and solve it with **PuLP + CBC** (bundled
solver), with a hard `timeLimit` of 2 s and a deterministic tie-break.

## Consequences

- The model is ~40 variables, so CBC solves it in milliseconds; no external solver service.
- Constraint slack is available directly, which is what the decision record needs for
  auditability (objective 4 of the proposal).
- Infeasibility is a first-class, provable outcome, which drives the infeasibility ladder
  (relax headroom → disable spot → report).
- Risk: a bundled binary solver complicates platform support. Mitigated by a documented
  greedy fallback behind the same `allocate()` interface if CBC is unavailable.

## Alternatives rejected

- **Greedy heuristic**: cannot represent the diversity cap and floor simultaneously without
  ad-hoc branching; no infeasibility proof.
- **Genetic algorithm** (SpotKube's approach): non-deterministic, no slack, harder to explain
  per decision.
- **scipy.optimize.linprog**: continuous relaxation would need a rounding pass and could
  violate the survival constraint.
