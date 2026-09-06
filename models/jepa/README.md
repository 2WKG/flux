# Experimental EAGLE-I count JEPA

This is a bounded, self-supervised joint-embedding predictive architecture for
**historical EAGLE-I customers-out count trajectories**. It does not produce an
outage probability, weather forecast, grid-state claim, or cascade result.

Run it from the repository root with the verified annual EAGLE-I 2024 source:

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

The command emits JSON and NumPy weights. The JSON includes source lineage,
configuration, chronological holdout coverage and metrics, a backwards-
compatible `forecast`, and one exact held-out historical `county_forecasts`
timeline for every county represented in the holdout. Any requested county that
produced no contiguous window is listed by name in
`scope.unavailable_county_fips` with a reason, never silently dropped.

There is no consumer of this artifact yet; nothing in the repository reads it.
Wiring one — and the validation it would need (kind, status, forecast arrays,
county scope, weights digest, and showing `limitations` unchanged) — is a
2WKG-474 follow-up, not something this PR ships or tests.

`metrics` records three baselines beside the model: persistence, the
MAE-optimal constant (`best_constant_baseline_count_mae`, which no flat
forecast can beat), and the train-versus-holdout error and spread
(`train_to_holdout_count_mae_ratio`, `train_actual_count_std`,
`holdout_actual_count_std`). On the checked-in 2024 run the training slice
spans a large storm and the chronological holdout is a much calmer tail, so
the holdout MAE is far below the training MAE. Beating persistence on that
calm tail is not evidence of storm-time skill; the sixth entry in
`limitations` states the gap with the numbers.
