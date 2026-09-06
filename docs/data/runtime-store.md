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

## Inputs, and where each one comes from

| Flag | Default | Producer |
| --- | --- | --- |
| `--hrrr-receipt` | `data/sources/texas-hrrr-2021-2024-run.json` | checked in |
| `--activsg-receipt` | `data/sources/activsg2000.json` | checked in |
| `--inventory-root` | `data/artifacts/physical_inventory` | checked in |
| `--output` | `data/duck/grid.duckdb` | this command |
| `--receipt` | `data/duck/runtime-store-receipt.json` | this command |
| `--hrrr-db` | none — required | `python -m pipelines.hrrr --scenario uri_2021 --db <path>` then `--scenario beryl_2024`, over a database whose `counties` table is already loaded; the run that produced the checked-in receipt wrote `data/raw/hrrr/runs/20260906T054451Z/grid.duckdb` |
| `--aux` / `--case` | none — required | `scripts/data/fetch_activsg2000.sh`, which unpacks `ACTIVSg2000.aux` and `case_ACTIVSg2000.m` under `data/raw/activsg2000_current/` |

Every receipt therefore defaults to a path that is in the repository; only the
two bulk artifacts, which `.gitignore` keeps out of Git, have to be supplied.
A receipt path that does not exist is refused **by name** rather than reported
as malformed JSON, so a second operator learns which file is missing.

The full invocation, with repository-relative paths:

```console
$ uv run python scripts/materialize_runtime_store.py \
    --hrrr-db data/raw/hrrr/runs/20260906T054451Z/grid.duckdb \
    --aux data/raw/activsg2000_current/ACTIVSg2000.aux \
    --case data/raw/activsg2000_current/case_ACTIVSg2000.m \
    --replace
```

## The receipt, and re-verifying the store against it

The operator receipt records the input hashes, the receipt each hash was checked
against, the exact scenario windows, counts, `capture_method`, `verification`,
and limitations. Every path it records is repository-relative when the input
lives in the repository, so the handoff never names an ephemeral temp directory.

It does **not** record a SHA-256 of the published database file. DuckDB rewrites
its file on every read-write open, so a file hash is stale the first time the
API serves the store — a value like that is recorded but can never hold. The
receipt records `content_digest` instead: per table, the row count and an
order-independent MD5 over that table's row digests, and one SHA-256 over the
whole set. That digest survives re-opening the store and still moves when any
row moves.

```console
$ uv run python scripts/materialize_runtime_store.py --verify
```

`--verify` re-derives `content_digest` from `--output` and refuses a store that
no longer matches its `--receipt`, naming the tables that drifted. It reads only
those two paths, so it is safe to run on a cold start before serving.

The expected output counts are read from the input receipts
(`aux_check.bus_records`, `validation.total_weather_rows`,
`validation.beryl_2024.source_runs_total`) rather than hard-coded, so a source
refresh reports as a source change instead of as a materializer bug. The two
ACTIVS branch counts are not carried by any checked-in receipt and stay named in
`scripts/materialize_runtime_store.py`.

The store never joins source-backed physical assets to the synthetic ACTIVS
topology. Minnesota inventory remains a map/provenance artifact; it does not
establish Minnesota topology, flows, outage predictions, or cascade results.
