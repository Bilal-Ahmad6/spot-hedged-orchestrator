# ADR-0006: Data sources for demand, price and interruption

**Status:** accepted (2026-11-12)

## Context

The study needs a demand trace with realistic diurnal and weekday structure, prices that are
anchored to something observable, and interruption behaviour calibrated to published ranges.
No cloud account is guaranteed.

## Decision

- **Demand:** Microsoft Azure Public Dataset, Functions invocation trace. Prefer the 2021
  two-week trace; if its RAR extraction is unreliable, use the 2019 functions dataset (zip).
  If neither is available, generate the documented synthetic profile and label it clearly.
- **Shape, not scale:** normalise the trace to its own mean, then rescale to the proposal's
  40–160 vCPU envelope, mean ≈ 70 vCPU, and tile to 30 days. Publish the transformed CSV and
  its SHA-256; every run records the hash.
- **Prices:** on-demand anchored at US$0.04/vCPU-hour (proposal) and cross-checked against the
  unauthenticated Azure Retail Prices API on the run date. Spot is modelled as a discount
  factor swept over {40, 50, 61, 65, 75, 80}%.
- **Interruptions:** calibrated to AWS's published "<5% average interruption frequency", with
  explicit models I1–I4 and a `q = 1` stress case. Never treat a spot placement score as a
  probability.
- **Provider semantics:** model AWS notice behaviour (2 minutes, best effort) for the base
  case, and sweep {0, 30, 120} s.

## Consequences

- No credential is required for the core results.
- The report must state that prices are modelled, not quoted, and that interruption rates are
  a range rather than measurements.
- Any substitution is recorded in `docs/PROGRESS.md` under Deviations.

## Alternatives rejected

- **Live spot price scraping**: requires credentials, gives no history, and makes runs
  irreproducible.
- **Synthetic-only demand**: loses the burstiness that makes the policy interesting.
