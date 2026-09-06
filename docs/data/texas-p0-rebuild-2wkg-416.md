---
title: "Texas P0 rebuild from verified raw data (legacy/research evidence)"
issue: 2WKG-416
parent: 2WKG-412
created: 2026-09-06
scope: Texas (FIPS 48) only
status: legacy/research evidence — NOT hackathon-ready, NOT Minnesota demo evidence
---

# Texas P0 rebuild — 2WKG-416

> **Truth label.** Everything on this page is **Texas P0 / ACTIVSg2000 legacy
> research evidence**. ACTIVSg2000 is a **synthetic** Texas-shaped case, not the
> real ERCOT network and not a Minnesota network. Nothing here is Minnesota
> demo evidence, and nothing here makes any artifact dashboard-eligible or
> hackathon-ready. The current demo authority remains
> [`docs/specs/10-minnesota-demo.md`](../specs/10-minnesota-demo.md).

This page records a clean rebuild executed on current `master` from the
verified raw inputs, following the safe-rebuild procedure in
[`data-intake-readiness.md`](data-intake-readiness.md) (2WKG-412). It records
what ran, what it produced, and — with equal prominence — what could not run.

Machine-readable receipts for every step are in
[`acceptance_receipts/`](acceptance_receipts/): `2wkg-416-preflight-legacy.json`,
`2wkg-416-acquisition-probe.json`, `2wkg-416-fetch.json`,
`2wkg-416-postbuild-receipt.json`, `2wkg-416-quality-report.json`.

## 1. Preflight — the legacy database was never touched

Run first, before anything was fetched or built:

```
uv run python -m pipelines.preflight --state TX --raw-dir data/raw \
  --database data/duck/grid.duckdb --report run-artifacts/2wkg-416-preflight.json
```

| Field | Value |
|---|---|
| `database.path` | `data/duck/grid.duckdb` |
| `database.status` | `missing` |
| `database.compatibility` | `no_existing_release` |
| `database.write_performed` | `false` |
| exit code | 1 (`texas_p0_safe_to_stage` false — no raw inputs yet) |

**Finding: there is no legacy Texas P0 DuckDB on this machine.** A search of the
whole checkout (all 40 worktrees) found no `data/duck/grid.duckdb` and no
`*.duckdb` larger than 10 MB outside pytest temp directories, and `data/raw/`
was empty everywhere. There was therefore nothing to migrate, overwrite, or
mutate; the preflight recorded the absence rather than creating a file at that
path. Every later step used the fresh output path below.

## 2. Input acquisition and provenance

`datasets/catalog.json` alone cannot reproduce this build. The probe
(`scripts/data/texas_p0_acquisition_probe.py --network`, receipt
`2wkg-416-acquisition-probe.json`) recorded, against live publishers:

* 17 P0 raw inputs; **0** present locally at the start.
* 10 had a catalog `downloads` entry (all reachable, HTTP 206 with exact
  `Content-Range` byte counts); 5 were `manual_only`; 2
  (`nws_zone_county/*.dbx`) had **no declared retrieval in the catalog at all**.
* 9 needed manual curation because the catalog's filename or version differs
  from the layout `pipelines.build` reads — notably PUDL, where the catalog
  declares the *nightly* `core_eia860__scd_plants.parquet` and the builder
  requires the pinned `v2026.2.0/out_eia__yearly_plants.parquet`. Substituting
  the nightly file would have been a silent version swap; it was not done.

The authoritative provenance was already tracked in `data/sources/*.json`
(publisher, source URL, license, retrieval time, bytes, SHA-256 per file).
`scripts/data/fetch_texas_p0_raw.py` (added here) is driven by those receipts:
every URL it requests is stated verbatim in a receipt or composed from that
receipt's own directory `source_url` plus its own filename, and every file is
verified against the receipt's SHA-256 and byte count before use.

```
uv run python scripts/data/fetch_texas_p0_raw.py --raw-dir data/raw \
  --report run-artifacts/2wkg-416-fetch.json
```

Result (`2wkg-416-fetch.json`): **17 / 17 artifacts present and SHA-256 verified
against their tracked receipts, 0 mismatches, 0 unavailable.**

| Input | Bytes | Provenance |
|---|---|---|
| `activsg2000_current/ACTIVSg2000.aux` | 6,255,512 | TAMU current-version bundle (zip 125,303,682 B, sha256 `817a6dc5…`) |
| `activsg2000_current/case_ACTIVSg2000.m` | 659,545 | same bundle |
| `tiger/2024/tl_2024_us_county.zip` | 83,913,260 | Census TIGER/Line 2024 |
| `nri/v1.20/NRI_Table_Counties.zip` | 24,966,535 | FEMA NRI v1.20 |
| `pudl/v2026.2.0/out_eia__yearly_plants.parquet` | 3,228,519 | PUDL v2026.2.0 |
| `pudl/v2026.2.0/out_eia__yearly_generators.parquet` | 10,247,414 | PUDL v2026.2.0 |
| `eia930/2021_h1/EIA930_BALANCE_2021_Jan_Jun.csv` | 43,073,764 | EIA-930 six-month files |
| `eia930/2024_h2/EIA930_BALANCE_2024_Jul_Dec.csv` | 47,928,993 | EIA-930 six-month files |
| `nws_zone_county/bp10nv20/bp10nv20.dbx` | 321,354 | NWS edition pinned to the Uri window |
| `nws_zone_county/bp05mr24/bp05mr24.dbx` | 339,683 | NWS edition pinned to the Beryl window |
| `storm_events/2021/…_d2021_c20260323.csv.gz` | 10,563,953 | NOAA NCEI |
| `storm_events/2024/…_d2024_c20260728.csv.gz` | 12,693,243 | NOAA NCEI |
| `eaglei/support/MCC.csv` | 40,584 | ORNL via figshare, CC BY 4.0 |
| `eaglei/support/coverage_history.csv` | 11,965 | ORNL via figshare |
| `eaglei/2021/eaglei_outages_2021.csv` | 1,141,058,232 | ORNL via figshare |
| `eaglei/2024/eaglei_outages_2024.csv` | 1,444,846,424 | ORNL via figshare |
| `ntad_military_bases/fy2024/texas.geojson` | 534,134 | NTAD FY2024 |

### ACTIVSg2000 AUX ↔ case identity, re-verified

`scripts/data/record_source.py` was re-run against the freshly downloaded
files. It reproduced `data/sources/activsg2000.json` **byte-identically except
the `retrieved_at` timestamp** — 2,000 bus records, 2,000 with coordinates,
1,250 substations all with coordinates, `bus_ids_match: true`,
`ids_only_in_mpc: 0`, `ids_only_in_aux: 0`, `kv_mismatches: 0`,
`mpc_buses_without_coords: 0`, extent
lon −104.6245…−94.3673 / lat 25.9131…35.8308. The tracked receipt was then
restored so this PR does not churn it. The product invariant holds: the
current-version AUX coordinates match the electrical case, and the June-2016
bundle was not used.

### Preflight immediately before the build

```
uv run python -m pipelines.preflight --state TX --raw-dir data/raw \
  --database run-artifacts/texas-p0-2wkg-416/grid.duckdb --strict-provenance
```

`all_present: true`, `no_checksum_mismatch: true`,
`all_locked_with_provenance: true`, `strict_provenance_ready: true`,
`texas_p0_safe_to_stage: true`; the output database still `missing`
(`write_performed: false`). Exit code 0.

## 3. The rebuild

```
uv run python -m pipelines.build \
  --raw-dir data/raw \
  --db run-artifacts/texas-p0-2wkg-416/grid.duckdb \
  --eaglei-source-tz UTC
```

Exit 0 in 3 m 36 s. Configuration: state scope **Texas only** (the builder's
default), EAGLE-I source timezone **UTC** (explicit; the receipt records that
applying `America/Chicago` to these timezone-naive UTC values would create
artificial spring-DST duplicates).

| Artifact | Value |
|---|---|
| Database | `run-artifacts/texas-p0-2wkg-416/grid.duckdb`, 829,435,904 B |
| Database SHA-256 | `bf8f53639558703e2b7a2bbf2cbe431b4490c85af7604a3acd414a686044fb7b` |
| Parquet export | `data/parquet/` (20 files + `manifest.json`) — see the finding below |
| Schema contract | `2.1.0`, all 19 contract tables present |
| Manifest `state_scope` | `tx` |

Row counts written:

```
ba_load_hourly 35040   buses 2000            bus_county 2000
counties 254           county_customers 254  critical_load_bus 19
critical_loads_dod 20  eaglei_2021 2443041   eaglei_2024 2921200
eaglei_coverage 5      eia_plants 1584       gens 544
lines 3206             loads 1125            nri 254
site_candidates 11     storm_events_2021 3198  storm_events_2024 3351
synthetic_branch_electrical 3206  synthetic_bus_electrical 2000
synthetic_generator_electrical 544  synthetic_substations 1250
```

The build manifest classifies `buses`, `lines`, `gens`, `loads` as
`classification: "synthetic"` and the county/hazard/outage/BA/critical-load
tables as `"real"`, so the synthetic boundary survives into the artifact.

## 4. Quality and readiness results

### Structural and referential — all pass

`pipelines.checks.run_checks` on the built database, read-only:

| Check | Result | Detail |
|---|---|---|
| `synthetic-case-counts` | **PASS** | buses=2000, branches=3206, transformers=847, loads=1125 |
| `synthetic-coordinates` | **PASS** | invalid/missing AUX coordinates=0 |
| `texas-counties` | **PASS** | counties=254, invalid_fips=0 |
| `fema-nri-texas` | **PASS** | county rows=254, missing composite score=0 |
| `eaglei-target-quality` | **PASS** | loaded years=2, negative-or-duplicate releases=0 |
| `loaded-p0-domains` | **PASS** | storm=6549, ba=35040, critical_invalid=0, candidate_invalid=0 |

The 847 transformers are the `net.impedance` branches the cascade path must
include (spec 03 correction 3), and the bus kV classes are
13.2/13.8/18/20/22/24/115/161/230/500 — **no 345 kV**, matching correction 4.

The read-only inspection is provably non-mutating: `file_sha256_before` ==
`file_sha256_after` == `bf8f5363…`, `access_mode: read_only`,
`write_performed: false`.

### Coordinate / spatial

* 2,000 / 2,000 buses carry coordinates; `coord_source = 'tamu_aux'` for all.
* Bus extent lon −104.6245…−94.3673, lat 25.9131…35.8308 (inside Texas).
* 254 / 254 counties carry `geom_wkb`; curated CRS EPSG:4326.
* 19 of 20 loaded DoD installations bound to a nearest synthetic bus. **That
  binding is screening geometry, not a service connection.**

### Coverage

* EAGLE-I: 253 distinct Texas counties across 2021+2024; 5,364,241 rows.
  2021 loaded 2,443,041 of 2,534,532 source Texas rows — the 91,491 dropped
  rows are **blank `customers_out` targets, i.e. missing observations, not
  zeros**. 2024 loaded 2,921,200 / 2,921,200.
* Storm events: 254 counties, 6,549 rows.
* EIA-930: 35,040 rows, 8,760 h each for ERCO/EPE/SWPP/MISO.
* `coverage_history.csv` loaded 5 rows and covers 2018–2022 only, so the
  coverage rule cannot fire for 2023–2025.

### Timezone

Curated timestamps are stored as UTC `TIMESTAMP` (naive-UTC convention):
EAGLE-I `2021-01-01 00:00` … `2024-12-31 23:45`; `ba_load_hourly`
`2021-01-01 06:00` … `2025-01-01 07:00` (UTC offsets of the local six-month
files); storm events `2021-01-06 17:53` … `2024-12-28 21:52` converted from
`CZ_TIMEZONE` local standard time.

### Critical records — independently reproduced

| Record | Rebuilt value | Matches |
|---|---|---|
| Uri peak customers out | **4,257,873** at `2021-02-16 19:00Z` | `VERIFICATION.md`, EAGLE-I receipt |
| Beryl peak customers out | **2,762,057** at `2024-07-08 19:45Z` | EAGLE-I receipt |
| ERCO demand at Uri 07Z | **65,255 MW** at `2021-02-15 07:00Z` | `VERIFICATION.md` correction 12 |

### Operations-metadata alignment — `unoperated_source` is clear

`operations_alignment.status: ready`, **`unoperated_source_ids: []`**. All 8
curated `source_name` values (`activsg2000`, `census_tiger_county+fema_nri`,
`eaglei`, `eia930`, `fema_nri`, `noaa_storm_events`, `ntad_military_bases`,
`pudl_eia860`) reconcile to 9 declared `datasets/operations.json` operation ids.

### Failures and unavailable results — reported, not repaired

**1. Scenario weather: UNAVAILABLE.** `--require-scenario-weather --scenario
uri_2021 --scenario beryl_2024` exits **1**. `scenarios` and `weather_hourly`
are both **0 rows**: `pipelines.build` seeds no scenarios and ingests no HRRR.
`scenario_present: false` for both. Consequently
**`texas_full_flux_ready: false`** — this artifact cannot support an outage,
cascade, or full-Flux claim.
*Next step:* seed `scenarios` and run the HRRR loader (spec 01 / spec 03), then
re-run the preflight with `--require-scenario-weather`.

**2. Dashboard eligibility: REFUSED.** `scripts/validate_data_quality.py`
returns `dashboard_eligible: false` with **11 errors and 1 warning**:

* 9 × `source_curated_mismatch` — curated rows cite `activsg2000`,
  `census-tiger-counties`, `fema-nri`, `pudl-eia860-plants`, `eia-930`,
  `eaglei-2021`, `eaglei-2024`, `noaa-storm-events`, `dod-bases-tx`, but no
  successful ingest-log record exists.
* 1 × `volume_baseline_missing` — no reviewed expected row-count baseline.
* 1 × `reconciliation_unavailable` — no append-only ingest log supplied.
* warning `reconciliation_unavailable`; `api_health: unavailable` (no URL
  supplied, correctly reported rather than assumed healthy).

*Next step:* supply `--ingest-log` and `--previous-counts` from a reviewed
release baseline. **Until then this artifact is not dashboard-eligible.** Note
this is a different gate from the preflight's `dashboard_release_ready`, which
only reflects operations-ID alignment.

**3. FEMA NRI 403 for some clients.** The declared v1.20 ZIP URL answered every
`urllib.request` call with HTTP 403 while serving the identical URL to
`requests` and to `curl`. The fetcher therefore uses `requests` (already a
project dependency). The URL is unchanged; only the client differs.

**4. Empty downstream tables (expected at P0).** `outage_predictions`,
`cascade_runs`, `site_scores`, `line_upgrade_scores`, `line_upgrade_detail`,
`corpus_chunks` are all 0 rows. P0 intake does not populate them.

**5. Python test suite could not run clean on this Windows host.**
`uv run --extra dev pytest -q` → **1,794 passed, 174 failed**. Every failure is
the pre-existing Windows environment problem tracked as **2WKG-423**: the
`Settings.duckdb_path` guard rejects a Windows absolute path as "a DuckDB
connection target … or scheme://", plus two `PermissionError` cases from
Windows exclusive file locking. This branch changes no file any failing test
imports.

## 5. Repository findings raised by this run

1. **`run-artifacts/` was not git-ignored** even though the 2WKG-412 runbook
   makes it the documented fresh-output location. An 829 MB DuckDB written
   there would have been offered to Git. Added to `.gitignore` (with
   `datasets/raw/`).
2. **`pipelines.build` ignores `--db` when choosing the Parquet destination.**
   `build()` hardcodes `live_parquet = Path("data/parquet")`, so a build
   directed at a fresh `--db` still promotes Parquet into `data/parquet` in the
   working directory. Confirmed: the export landed in `data/parquet/`, not
   beside `run-artifacts/texas-p0-2wkg-416/grid.duckdb`. It is git-ignored, so
   nothing leaked, but "build into a fresh, explicit output location" is only
   half true today. Not fixed here — it changes builder behaviour and belongs
   in its own change.
3. **`scripts/data/fetch_activsg2000.sh` hardcodes `python3`**, which on this
   Windows host is the Microsoft Store alias stub; extraction failed after a
   successful, checksum-matching download. Worked around by extracting with the
   project interpreter; the new `fetch_texas_p0_raw.py` covers the same step in
   pure Python.
4. **`scripts/validate_data_quality.py` needs `PYTHONPATH=.`** — run directly it
   raises `ModuleNotFoundError: No module named 'pipelines'`.
5. **Schema version on current `master` is `2.1.0`, not `1.0.0`.** Planning
   material still circulating quotes 1.0.0; `pipelines/db.py` defines
   `SCHEMA_VERSION = "2.1.0"` over 19 contract tables, and 2.1.0 is what was
   built and validated here.



## What this rebuild does not claim

* **No dashboard eligibility.** `pipelines.data_quality` gates dashboard
  promotion on an operations mapping for every curated `source_name` /
  `source_version`, a reviewed row-count baseline, and an append-only ingest
  log. The results below state each outcome explicitly.
* **No hackathon readiness.** The preflight receipt's
  `readiness.current_hackathon_ready` is `false` by construction for a Texas
  receipt, and `scope.status` is `blocked` pending a Minnesota source decision.
* **No real-grid claim.** ACTIVSg2000 buses, branches, and coordinates are
  synthetic. Their proximity to a real plant, county, or installation is
  screening geometry, never a service-connection or interconnection finding.
* **No outage-replay claim beyond the loaded windows.** EAGLE-I coverage varies
  by utility and year; blank `customers_out` values are missing observations,
  never zero.
