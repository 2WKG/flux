# Runtime store materialization

`scripts/materialize_runtime_store.py` publishes the ignored local DuckDB
artifact consumed by the Flux API. It accepts every source path explicitly and
checks the HRRR database, current ACTIVSg2000 AUX/MATPOWER pair, and both
published physical-inventory releases before writing anything.

It creates a temporary copy of the verified HRRR database, loads the current
synthetic Texas topology, registers only the persisted Uri and Beryl weather
windows, writes the two physical-inventory releases into `physical_*`, checks
the resulting schema/counts, and atomically replaces the requested output.
It refuses to replace an existing output without `--replace`; stop or serialize
all downstream DuckDB writers before using that flag. A store with persisted
cascade, prediction, siting, or line-score products also refuses replacement
unless `--discard-derived` is supplied. Cold starts consume the existing ready
store and do not rebuild it; use the destructive flag only for a deliberate
source refresh after preserving any derived work that must survive.

The operator receipt records source and output hashes, exact scenario windows,
counts, and limitations. The store never joins source-backed physical assets to
the synthetic ACTIVS topology. Minnesota inventory remains a map/provenance
artifact; it does not establish Minnesota topology, flows, outage predictions,
or cascade results.
