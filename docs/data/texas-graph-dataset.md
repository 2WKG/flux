# Synthetic Texas graph dataset export

`python -m pipelines.graph_export --db data/duck/grid.duckdb --out data/graph/texas`
exports the populated Texas adapter as a graph dataset. The source database is opened read-only.
The output cannot be the source database's directory (or another directory containing it). A rerun
replaces only a prior, complete graph export with the matching schema and topology label; it refuses
to delete any other existing directory.

The output is deliberately labelled `synthetic (ACTIVSg2000)`: it is a Texas-shaped research topology,
not ERCOT topology or a physical asset inventory. The command refuses an absent or empty source database
instead of writing a fixture-looking result.

- `nodes.json` contains one bus node per `buses.bus_id`.
- `edges.json` contains every `lines` branch. `source_edge_type` distinguishes lines from voltage-transition
  transformers; `solver_edge_type` records that those transformer branches import as pandapower impedance branches.
- `normalization.json` persists population z-score statistics for every numeric node and edge feature.
- `manifest.json` contains per-file SHA-256 values and a dataset SHA-256 over the schema, topology label, and
  content hashes.

All JSON is canonical (sorted keys, compact UTF-8, trailing newline), and source rows are ordered by their stable
IDs. Repeating an export from unchanged DuckDB content produces byte-identical files. Database `NULL` values remain
JSON `null` in both raw and normalized feature maps; the exporter never substitutes zero or another plausible value.
