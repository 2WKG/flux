# EIA-860 2025 Early Release physical-observation receipt

[`eia860-2025er-physical-observed.json`](../../data/sources/eia860-2025er-physical-observed.json)
records the official EIA archive URL, retrieval checksum, source scope, and the
counts produced by `pipelines.eia860_physical` on 2026-09-06.

| State | Schedule 2 plant rows | Schedule 3.1 generator rows | Schedule 3.4 storage rows | Invalid/out-of-range plant points |
| --- | ---: | ---: | ---: | ---: |
| Texas | 1,514 | 3,393 | 460 | 1 |
| Minnesota | 850 | 1,555 | 11 | 0 |

Schedule 3.4 rows duplicate the corresponding Schedule 3.1 generator identity.
The publisher emits one storage asset for each duplicate identity, preserving its
Schedule 3.4 source record rather than manufacturing a second co-located asset.

`build_physical_inventory_artifact` produces one state artifact at a time and
`publish_physical_inventory_artifact` writes it through the 2WKG-441 contract.
For Texas 1.0.0, the checked artifact has 4,907 assets: 1,514 plant records,
2,933 non-storage generator-unit records, and 460 storage-unit records. The
EIA plant point is retained only for the plant record; all 3,393 unit records
have unavailable native geometry, no terminals, and no connectivity edges.

For Minnesota 1.0.0, the checked artifact has 2,405 assets: 850 plant records,
1,544 non-storage generator-unit records, and 11 storage-unit records. Its
coverage reports 2,394 generation assets with 1,544 unavailable native
geometries, plus 11 storage assets with 11 unavailable native geometries.

The EIA 2025 Early Release is not fully edited, may omit records pending
validation, and is inappropriate for aggregation. These are source-scoped
observations, not a claim of complete statewide physical coverage. EIA does not
publish unit coordinates, terminal/edge connectivity, facility polygons, or
storage state of charge in these schedules.
