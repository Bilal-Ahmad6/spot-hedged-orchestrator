# Demand trace

`demand_30d.csv` is the demand series used by every simulator run.

## Provenance

- Source: **Azure Public Dataset — Azure Functions Invocation Trace 2021**
  (`AzureFunctionsInvocationTraceForTwoWeeksJan2021.rar`, 17.6 MB, 305 MB extracted,
  ~5 M individual invocations with `app, func, end_timestamp, duration`).
- Source SHA-256: `d56368ef194baa8d418304bd2f87cca67668ced0d117bd89ad4ef3cf836457d2`
- Derived file SHA-256: `7eb8f5f2ff455bcbe840af462fe170741bbef3551c893c48a2a4a89f94425148`
- 43,200 rows (30 days at 1-minute resolution), starting Monday 2026-01-05T00:00:00Z.

## Method

1. Aggregate individual invocations per minute at `floor(end_timestamp / 60)`.
2. **Smooth over 15 minutes** (centred rolling mean). Rationale: a capacity
   controller observes a rate over its metrics window, not a single minute's
   invocation count. The raw counts change by 16.6% on average between adjacent
   minutes (p99 109%), which is sampling noise, not demand — feeding it to a
   policy produces thrash that no real system exhibits. Smoothing reduces the
   mean jump to 2.1% (p99 17.5%) while leaving the diurnal and weekly structure
   untouched.
3. Tile the 14-day trace to 30 days. Fourteen days is exactly two weeks, so tiling
   preserves weekday alignment.
4. Apply a **rank transform** to hit the proposal's envelope:

   ```
   D(t) = 40 + (160 - 40) * F(t) ** gamma
   ```

   where `F` is the empirical CDF of the tiled series and `gamma` is solved so the
   mean is exactly 70 vCPU. The transform is monotone, so the temporal shape is
   preserved; only the scale changes.
5. Solved `gamma = 3.0002`.

## Observed properties

| Property | Value |
|---|---|
| min | 40.0 |
| mean | 70.0 |
| p95 | 142.9 |
| max | 160.0 |
| weekday mean | 76.1 |
| weekend mean | 53.3 |
| median daily peak | 150.8 |
| daily peak range | 93.7 – 160.0 |

The 30-day series spans 40–160 vCPU. Not every day reaches the maximum: the median
daily peak is 151 vCPU and the quietest day peaks at 94. That is a property of the
real trace (weekday/weekend variation), not a defect, and the `q = 1` stress case
plus the peak-hour interruption model exercise the upper envelope explicitly.

**Hour-of-day labels are arbitrary.** The source trace uses timestamps relative to
its own start, so the phase of the diurnal cycle is an artefact of where we map
t=0. The amplitude and the weekly pattern are real; the clock hour is not. The
report states this rather than pretending the peak is "3 p.m. traffic".

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
the **median of 46 ms** as the reference service time for a request/response API
(`configs/base.yaml: workload.serviceTimeS`), and records the full distribution in
`demand_30d.meta.json` for the calibration chapter.

## Rebuild

```bash
python -m spothedge trace build \
  --source experiments/traces/raw/extracted/AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt \
  --out experiments/traces/demand_30d.csv
```

Without `--source`, the command falls back to a documented synthetic profile
(diurnal + weekly + AR(1)) through the same transform, and marks the provenance as
`synthetic-fallback`.
