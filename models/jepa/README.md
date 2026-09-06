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
timeline for every county represented in the holdout. Consumers must show the
artifact's limitations unchanged and must return unavailable if its kind,
status, forecast arrays, county scope, or weights digest are invalid.
