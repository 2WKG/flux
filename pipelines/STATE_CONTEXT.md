Public state context is loaded into the canonical `data/duck/grid.duckdb` shared store. State selection controls replacement slices, not database paths; topology acquisition remains restricted to the existing Texas build.

`eaglei_ingest_quality_by_state` is additive ingest metadata keyed by `(source_year, state_fips)`. It records source file and timezone, raw/valid/missing row counts, rejected-value counters, county count, and load time. Successful empty refreshes record zero counts for the selected state. Invalid timestamps, FIPS/state mismatches, negative counts, and duplicate observations fail before curated replacements. The legacy `eaglei_ingest_quality` relation remains populated with Texas-only counts whenever Texas is selected.

Scoped artifact log entries use `source_release` values such as `2024;scope=mn` or `2024;scope=mn-wi`, preserving separate acquisition evidence for the same national artifact loaded for different scopes. These entries describe load executions; the per-state quality relation describes each state's current curated source-year slice.

The context CLI stages a copy of the existing database and Parquet, runs all requested loads and schema validation, and promotes only a successful release using the shared publication helper. A failed loader leaves the live release untouched.
