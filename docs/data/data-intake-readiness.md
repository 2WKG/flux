---
title: "Data-intake readiness receipt and safe rebuild"
issue: 2WKG-412
created: 2026-09-05
---

# Data-intake readiness receipt

The current hackathon demo is Minnesota. The legacy Texas / ACTIVSg2000 P0
path is useful research and loader evidence, but is **not hackathon-ready** and
must never be relabelled as Minnesota. Flux can stage genuinely supplied public
context for any U.S. state; geographic inputs never imply topology. A state
topology result requires an accepted source decision covering the electrical,
terms, and solver contract. Otherwise choose a transparent aggregate metric or
report unavailable. A Minnesota result remains unavailable until MN01 records
that decision. The receipt makes these boundaries explicit.

`pipelines.preflight` is read-only. It emits JSON containing one raw receipt per
P0 artifact: selected path, bytes, observed SHA-256, and a cheap schema
fingerprint for CSV/Parquet inputs. It only calls an input *verified* if a
tracked source receipt supplies a matching SHA-256 and byte count. An observed
hash is reproducibility evidence, not publisher provenance.

## Inspect the old checkout safely

Run this before copying or rebuilding anything. The `--database` connection is
DuckDB read-only and the receipt records its before/after SHA-256. A legacy
contract is diagnosed, never migrated.

```powershell
uv run python -m pipelines.preflight `
  --state TX `
  --raw-dir <legacy-worktree>/data/raw `
  --database <legacy-worktree>/data/duck/grid.duckdb `
  --report run-artifacts/texas-p0-receipt.json
```

If all artifacts are present and no supplied checksum mismatches, the receipt
sets `texas_p0_safe_to_stage: true`. `strict_provenance_ready` stays false when
a raw artifact has no tracked checksum/provenance receipt. That is intentional:
do not call an unrecorded raw file verified.

For a custody-complete Texas rebuild, require every P0 lock. This currently
fails until source receipts are recorded for each P0 input; the failure is a
useful blocker, not an instruction to trust changed files.

```powershell
uv run python -m pipelines.preflight `
  --state TX `
  --raw-dir <legacy-worktree>/data/raw `
  --strict-provenance `
  --report run-artifacts/texas-p0-strict-receipt.json
```

`datasets/download.py` writes its own catalog-shaped directory and does not
produce the P0 builder layout. Do not point the builder at it blindly; compare
the receipt's `acceptable_paths` and explicitly curate/copy artifacts into the
documented layout first.

## Rebuild only into fresh output

Use a new worktree and a new output directory. Do **not** pass the legacy
DuckDB as `--db`. The builder creates a staged database and staged Parquet
directory, runs P0 checks there, and only then promotes that fresh output.

```powershell
uv run python -m pipelines.build `
  --raw-dir <legacy-worktree>/data/raw `
  --db run-artifacts/texas-p0/grid.duckdb `
  --eaglei-source-tz UTC

uv run python -m pipelines.preflight `
  --state TX `
  --raw-dir <legacy-worktree>/data/raw `
  --database run-artifacts/texas-p0/grid.duckdb `
  --report run-artifacts/texas-p0/post-build-receipt.json
```

The P0 build checks synthetic case counts/coordinates, Texas county and FEMA
coverage, EAGLE-I quality, and populated storm/BA/critical-load/candidate
domains. It does not ingest HRRR or seed scenarios. Therefore it cannot support
an outage, cascade, or “full Flux” claim. Make that dependency a hard check:

```powershell
uv run python -m pipelines.preflight `
  --state TX `
  --raw-dir <legacy-worktree>/data/raw `
  --database run-artifacts/texas-p0/grid.duckdb `
  --require-scenario-weather `
  --scenario uri_2021 --scenario beryl_2024
```

This exits nonzero until every requested scenario has one hourly weather row
for every loaded county in each selected state across its stored start/end
window. Unrelated state weather or rows outside the scenario window do not
count.
It also reports `operations_alignment`; unmatched curated `source_name` values
block dashboard release because the offline quality gate cannot reconcile them
with `datasets/operations.json`. No receipt marks the current Minnesota
hackathon as ready: that status stays blocked until the Minnesota source and
model-mode gates are satisfied.

## Stage public context for another state

Use USPS, a full state name, or a one/two-digit FIPS code. State context is
only built from explicit local artifacts; there is no implicit downloader and
no fabricated topology fallback. The receipt can cover several states.

```powershell
uv run python -m pipelines.preflight `
  --state Minnesota --state "New York" `
  --context-tiger <county-boundaries.zip> `
  --context-nri <nri-data.zip> `
  --context-eaglei 2024=<eaglei-2024.csv> `
  --context-eaglei-source-tz UTC `
  --report run-artifacts/mn-ny-context-receipt.json

uv run python -m pipelines.build_state_context `
  --state Minnesota --state "New York" `
  --db-root run-artifacts/mn-ny/duck `
  --parquet-dir run-artifacts/mn-ny/parquet `
  --tiger <county-boundaries.zip> --nri <nri-data.zip> `
  --eaglei 2024=<eaglei-2024.csv> --eaglei-source-tz UTC
```

`ready_to_stage` means the declared public-context files are present; it is not
a topology, power-flow, cascade, outage-replay, or dashboard-release verdict.
