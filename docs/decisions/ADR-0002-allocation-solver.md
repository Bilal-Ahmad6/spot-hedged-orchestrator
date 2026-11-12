# ADR-0002: Closed-form allocation with a MILP reference

**Status:** revised (2026-11-12) — supersedes the "MILP is the solver" decision.

## Context

Each tick must choose integer node counts across three pools and four instance
types subject to a survival inequality, an on-demand floor, a diversity cap,
quotas and a node limit. The original decision was to solve this with PuLP/CBC on
every tick.

Two measurements changed the plan:

1. A 30-day run has 43,200 ticks. At ~10 ms per MILP solve that is ~7 minutes per
   run, and the pre-registered matrix has ~2,800 runs.
2. The problem has a **single binding constraint** and constant per-vCPU prices,
   so its optimum is closed-form: buy spot until either the survival inequality or
   the diversity/share cap binds, then fill with on-demand.

## Decision

- The deployed policy uses the **closed form** plus whole-node rounding.
- A **MILP reference** (`policy/hedged_milp.py`, PuLP + CBC) is kept in the
  repository and exercised by a differential test on random scenarios. It is the
  evidence that the fast path is near-optimal, not an assumption.
- The node shape is chosen **once per run** (default 4 vCPU) and held. Re-packing
  shapes every tick is not a tuning detail: it drains and relaunches the cluster
  whenever rounding changes. Measured: 180,000 node launches and 93 % availability
  in a 30-day run, versus 11,500 launches and 99.98 % with a fixed shape.

## Consequences

- 30-day runs take ~19 s with the policy, versus ~7 minutes with a per-tick MILP.
- Measured gap to the MILP optimum over 18 random scenarios: **mean 1.14×, worst
  1.24×**. The gap is per-pool rounding overshoot, not a modelling error.
- The MILP remains available for offline "what would the ideal allocator do?"
  analysis, and for the report's shape/rounding discussion.
- PuLP is pinned below 4.0: v4 removes the bundled CBC solver and the classic
  `LpVariable` API, and the solver plugin build is not reliable on Windows.

## Alternatives rejected

- **MILP every tick**: correct but 20× too slow for the matrix.
- **Genetic algorithm** (SpotKube's approach): non-deterministic, no slack, harder
  to explain per decision.
- **Shape re-optimisation every tick**: strictly better cost on paper, catastrophic
  for churn and availability in practice.
