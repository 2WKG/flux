# Minnesota aggregate runtime build

This builder makes a new runtime DuckDB file from an existing runtime store and
the four Minnesota artifacts accepted by Gate 0. It never modifies the source
database. It refuses an existing output path and stages the copy in the output
directory before atomically publishing it.

Run it from the repository root:

```bash
uv run python -m pipelines.minnesota_aggregate_runtime \
  --source-db /absolute/path/to/grid.duckdb \
  --output-db /absolute/path/to/minnesota-aggregate-runtime.duckdb
```

The source opens with DuckDB read-only mode. The output retains the source
tables, initializes the `mn_*` contract schema, and persists one available
`model_result` artifact. Its canonical identity is derived from the checked-in
aggregate manifest, so the artifact ID is deterministic. With the current
accepted manifest, it is `mn:model_result:665b5ac415912f3f`; the builder derives
that value from the identity JSON rather than treating it as a selector constant.

Before the copy, the builder verifies the exact Gate 0 inventory and the
canonical-LF SHA-256 digests of these committed inputs:

| Gate 0 artifact | Committed input | SHA-256 |
| --- | --- | --- |
| `mn:aggregate:manifest:v1` | `pipelines/fixtures/inputs/minnesota_aggregate_manifest_v1.json` | `f287a1dfbafddff8bd9f0ec989d488ad6743609280b19338eca048c3d5858e05` |
| `mn:facility_capacity:county:2024` | `pipelines/fixtures/inputs/mn_county_plant_capacity_2024.csv` | `7757c6ece5c36a0ae15573acfe4dd2e02cb42e13a0aa9f8ac142663977e7d573` |
| `mn:facility_context:unassigned:2024` | `pipelines/fixtures/inputs/mn_unassigned_plant_capacity_2024.csv` | `926f6fb65715df19af1eb833df1560c6e592827d7ea47ed54091cf3cf08a4ed6` |
| `mn:ba_context:miso:2024-h1` | `pipelines/fixtures/inputs/miso_ba_context_2024_h1.csv` | `395dad9aea19226744f8be5f91ca30c783ab776d1720e6486ff64880b8366e6f` |

The only numeric metric is `miso_ba_peak_demand_mw`: the maximum `Demand (MW)`
across the 4,368 committed EIA-930 MISO balancing-authority records for 2024 H1.
Its unit is MW; its result stores the peak UTC end-of-hour and scored-hour count.
The metric is MISO balancing-authority context, not Minnesota demand.

The output stores this exact object shape in
`mn_score_results.score_components_json`: `artifact_version`,
`aggregate_manifest`, `stress_context`, and `prohibited_claims`.
`stress_context` names MISO explicitly and retains its UTC window, peak, hour
count, plus `min_index`, `mean_index`, and nearest-rank `p95_index` values
normalised to that window's MISO peak. `mn_model_results` is authoritative for
the metric value, formula, and unit. Its aggregate model fields `base_mva`,
`solver_version`, and `converter_version` are all `NULL`.

No geometry, facility point, county/service-area allocation, topology, line or
bus state, flow, loading, trip, cascade, outage, or interconnection claim is
read or produced. A missing county remains neither a zero-capacity claim nor an
asset.

Verify the builder and the Gate 0 boundary with:

```bash
uv run pytest pipelines/tests/test_minnesota_aggregate_runtime.py tests/test_minnesota_gate0_approval.py -q
```
