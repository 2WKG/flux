# Synthetic Texas graph dataset export

`python -m pipelines.graph_export --db data/duck/grid.duckdb --out data/graph/texas`
exports the populated Texas adapter as a graph dataset. The source database is opened read-only.
The output cannot be the source database's directory (or another directory containing it). A rerun
refuses any existing output path; the caller must remove a prior export explicitly.

The manifest labels the dataset `synthetic (ACTIVSg2000)`: it is a Texas-shaped research topology,
not ERCOT topology or a physical asset inventory. The exporter verifies that every source row it reads
is tagged `activsg2000`. It refuses an absent or empty source database instead of writing a
fixture-looking result.

- `nodes.json` contains one bus node per `buses.bus_id`, raw electrical/load/capacity features,
  per-fuel capacity, and categorical role/county/BA membership. Coordinates are held out, while
  county and BA remain available as coarse region labels.
- `edges.json` contains every `lines` branch. `source_edge_type` distinguishes lines from voltage-transition
  transformers; `solver_edge_type` records that those transformer branches import as pandapower impedance branches.
- `manifest.json` contains per-file SHA-256 values and a dataset SHA-256 over the schema, topology label, and
  content hashes. Loaders must read the manifest alongside the node and edge files.

All JSON is canonical (sorted keys, compact UTF-8, trailing newline), and source rows are ordered by their stable
IDs. Repeating an export from unchanged DuckDB content on the same machine and Python produces byte-identical files.
Numeric `features` preserve database `NULL` as JSON `null` and are never imputed. Role is a derived categorical:
a present zero load or generation capacity remains present, while a database `NULL` remains absent. Per-fuel maps
emit only fuels present on that bus; absent fuels are omitted rather than represented as zero. Feature scaling belongs
to training, which must fit normalization on the train split only.

The output directory must not equal or contain the source database, and it cannot be a symlink; unsafe overlap and
all existing output paths are rejected before publication. A completed temporary dataset is renamed into the
previously absent output path only after all files have been written.
