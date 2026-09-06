# Flux dataset registry

This directory is the reproducible entry point for Flux data. Bulk source data
is intentionally not committed to Git: several sources are hundreds of
gigabytes or larger, some change continuously, and GitHub rejects individual
files larger than 100 MB.

`catalog.json` records every currently identified source, why Flux may use it,
how it is accessed, and important licensing or modeling caveats. `download.py`
downloads bounded files with stable direct URLs into the ignored `raw/`
directory. API, cloud-archive, repository, and account-gated sources remain in
the catalog and print the correct acquisition route.

## Usage

List everything:

```powershell
py datasets/download.py --list
```

Preview the recommended first acquisition without downloading:

```powershell
py datasets/download.py --group core --dry-run
```

Preview the two regional demo bundles:

```powershell
py datasets/download.py --group demo-ny --dry-run
py datasets/download.py --group demo-tx --dry-run
py datasets/download.py --group demo-mn --dry-run
```

Where each loaded source came from, per state, is recorded in
`docs/data/texas-p0-curated-source-receipts.md` and
`docs/data/minnesota-p0-curated-source-receipts.md`, with per-source digests
under `data/sources/`.

Acquire `core` and `national` first, then the appropriate regional bundle. The
regional groups contain state-specific additions rather than duplicating the
shared sources.

Download the bounded files in the core group:

```powershell
py datasets/download.py --group core
```

Select individual sources:

```powershell
py datasets/download.py eia-860 census-tiger-counties fema-nri dod-bases-tx
```

Review every catalog entry, including sources requiring APIs, cloud tools, Git,
or manual access:

```powershell
py datasets/download.py --group all --dry-run
```

Large sources are never fetched accidentally. Add `--include-large` only after
checking disk and bandwidth. Existing files are preserved unless `--force` is
given.

## Data policy

- `datasets/raw/` is ignored. Keep immutable vendor files there.
- Derived Parquet/DuckDB artifacts belong under the repository's already
  ignored `data/parquet/` and `data/duck/` paths.
- Record the source ID, retrieval date, original filename, and transformations
  in generated metadata before using a derived dataset.
- Never describe ACTIVSg, RTS-GMLC, PyPSA-USA, or GridSFM networks as the real
  grid. They are synthetic or modeled systems.
- HIFLD geometry is map context, not verified electrical connectivity.
- Do not combine real line geometry with synthetic buses and claim the result is
  a real power-flow network.
- Restricted FERC, NERC, ERCOT MIS, SCADA, relay, or CEII data is not included.

## Regional demo strategy

The New York and Texas bundles use the same modeling dimensions so results can
be compared rather than becoming two unrelated demos. See
`REGIONAL_COVERAGE.md` for the cross-state coverage matrix, recommended joins,
and the acquisition order. A source tagged `national` is a reusable backbone;
`demo-ny` and `demo-tx` mark state-specific additions.

## Catalog statuses

- `direct`: the downloader can retrieve one or more bounded files.
- `api`: query parameters or credentials must be chosen at runtime.
- `cloud`: use the provider's object-store tooling and subset aggressively.
- `git`: clone or consume the upstream repository separately.
- `manual`: landing page, account gate, or interactive export.
- `restricted`: documented for completeness but unavailable for public ingest.
