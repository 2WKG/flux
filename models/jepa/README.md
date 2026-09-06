# Experimental EAGLE-I count JEPA

This is a bounded, self-supervised joint-embedding predictive architecture for
**historical EAGLE-I customers-out count trajectories**. It does not produce an
outage probability, weather forecast, grid-state claim, or cascade result.

Run it from the repository root only after the annual EAGLE-I 2024 source and
its acquisition receipt have been verified:

```bash
uv run python -m models.jepa \
  --source data/raw/event-baseline/annual-source/eaglei_outages_2024.csv \
  --source-reference data/raw/event-baseline/annual-source/eaglei_outages_2024.csv \
  --output-dir data/artifacts/jepa/eaglei-2024-count-v1 \
  --epochs 80 --max-windows 2400
```

The source must hash to
`d5d75ea4ef3943446aaf0623e9b451cb4e7796d20cc379de9cf497106ebab2e6`, as
recorded in `data/sources/texas-eaglei-2021-2024.json`. The source acquisition
and its ORNL Figshare provenance are owned by the data pipeline; this command
only reads the local source.

The production configuration uses a fixed UTC holdout interval from
`2024-10-01T00:00:00Z` through `2024-12-31T23:45:00Z`. A training window must
end before the interval starts. An evaluation window's context must start on or
after the interval starts and its target must end within the interval. Windows
that cross the boundary are discarded, so no timestamp can be used by both
training and evaluation. This is a temporal rule across all counties; equal
timestamps in different counties have the same membership and county order has
no role in the split.

The command emits fresh JSON and NumPy weights. The JSON records source lineage,
configuration, fixed temporal bounds, train and evaluation timestamp bounds,
boundary-discard counts, deterministic membership digest, and each forecast's
context and target start/end timestamps. Any requested county that produced no
contiguous window is listed by name in `scope.unavailable_county_fips` with a
reason, never silently dropped.

`web/src/explainer/jepa/recordedEvaluation.ts` reads a vendored copy of an
artifact from this module and fails closed in `assertRecordedEvaluation` unless
`metrics` carries `holdout_count_mae`, `holdout_count_rmse`,
`persistence_baseline_count_mae`, `persistence_baseline_count_rmse`,
`holdout_embedding_mse`, `train_count_mae` and
`train_to_holdout_count_mae_ratio`. That copy is a *chronological-split* run
recorded before this fixed-interval policy; it is not regenerated here, and the
explainer keeps naming the split it actually came from. Any artifact this module
emits must keep every one of those metrics.

`metrics` records three baselines beside the model: persistence, the
MAE-optimal constant (`best_constant_baseline_count_mae`, which no flat forecast
can beat), and the train-versus-holdout error and spread
(`train_to_holdout_count_mae_ratio`, `train_actual_count_std`,
`holdout_actual_count_std`). The last entry in `limitations` states the
train/holdout regime gap with those numbers.

There is no checked-in result for this fixed-interval policy. Metrics and artifacts must be
generated together from the verified pinned source; an older artifact or its
weights cannot support this temporal-holdout claim. `metrics` records the JEPA
and persistence values for the fresh holdout only. It does not claim storm,
contingency, geographic, or label-axis disjointness.
