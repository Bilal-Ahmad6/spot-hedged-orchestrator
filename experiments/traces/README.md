# Demand trace

`demand_30d.csv` is the demand series used by every simulator run.

## Provenance

- Source: **Azure Public Dataset — Azure Functions Invocation Trace 2021**
  (`AzureFunctionsInvocationTraceForTwoWeeksJan2021.rar`, 17.6 MB, 305 MB extracted,
  ~5 M individual invocations with `app, func, end_timestamp, duration`).
- Source SHA-256: `d56368ef194baa8d418304bd2f87cca67668ced0d117bd89ad4ef3cf836457d2`
- Derived file SHA-256: `6a93a6791d3bc9d276a2b7525a8ac3f715f8c92bcf1c023ab991386569ea5ad8`
- 43,200 rows (30 days at 1-minute resolution), starting Monday 2026-01-05T00:00:00Z.

## Method

1. Aggregate invocations per minute by summing individual invocations at
   `floor(end_timestamp / 60)`.
2. Tile the 14-day trace to 30 days. Fourteen days is exactly two weeks, so tiling
   preserves weekday alignment; the last two days repeat the pattern.
3. Apply a **rank transform** to hit the proposal's envelope:

   ```
   D(t) = 40 + (160 - 40) * F(t) ** gamma
   ```

   where `F` is the empirical CDF of the tiled series and `gamma` is solved so the
   mean is exactly 70 vCPU. The transform is monotone, so the trace's temporal
   shape is preserved exactly; only the scale changes.
4. Solved `gamma = 3.0001`.

## Observed properties

| Property | Value |
|---|---|
| min | 40.0 |
| mean | 70.0 |
| p95 | 142.9 |
| max | 160.0 |
| weekday mean | 75.3 |
| weekend mean | 55.3 |
| peak hour (mean) | 15:00 UTC |
| daily max, median across days | 156.9 |

Every individual day spans 40 → ~157 vCPU, matching the proposed 40–160 swing.

## Service time

The same trace yields a service-time distribution from the `duration` column:

| Statistic | Value |
|---|---|
| median | 46 ms |
| p90 | 2.30 s |
| p95 | 19.2 s |
| p99 | 77.6 s |
| mean | 3.66 s |

The mean is dominated by long-running Azure Functions. The simulator therefore uses
the **median of 46 ms** as the reference service time for a request/response API, and
records the distribution in `demand_30d.meta.json` for the calibration chapter.

## Rebuild

```bash
python -m spothedge trace build \
  --source experiments/traces/raw/extracted/AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt \
  --out experiments/traces/demand_30d.csv
```

Without `--source`, the command falls back to a documented synthetic profile
(diurnal + weekly + AR(1)) through the same rank transform, and marks the provenance
as `synthetic-fallback`.
