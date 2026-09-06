# Minnesota bounded public-source receipts

This receipt set records the public source families retrieved and validated for
Minnesota on 2026-09-06, loaded through the same loaders that produce the Texas
slice and into the same `data/duck/grid.duckdb` store. It is county-grain public
context. It does **not** create a Minnesota electrical topology, does not change
the Minnesota demo authority recorded in
[`physical-grid-source-authority-ledger.md`](../research/minnesota/physical-grid-source-authority-ledger.md),
and does not make an untracked database artifact available in a fresh clone.

The Texas counterpart is
[`texas-p0-curated-source-receipts.md`](./texas-p0-curated-source-receipts.md).
Six of the seven families below are the **same national artifacts** Texas uses;
only the state scope differs, and `ingest_log` keeps each state's acquisition
evidence separately as `<release>;scope=mn` next to `<release>;scope=tx`.

| Source | Evidence | Validation |
| --- | --- | --- |
| Census TIGER/Line 2024 counties | [`minnesota-tiger-2024.json`](../../data/sources/minnesota-tiger-2024.json) | `load_counties` loaded 87 Minnesota counties, transformed to EPSG:4326, with no missing population. |
| FEMA NRI v1.20 counties | [`minnesota-nri-v1.20.json`](../../data/sources/minnesota-nri-v1.20.json) | `load_nri` loaded 87 county rows and 870 hazard rows across the same 10 hazards Texas carries, with no missing population or NRI score. |
| PUDL EIA-860 v2026.2.0 | [`minnesota-pudl-eia860-v2026.2.0.json`](../../data/sources/minnesota-pudl-eia860-v2026.2.0.json) | `load_eia860_plants` loaded 909 Minnesota plants totalling 26,142 MW. No site candidates are seeded. |
| EIA-930 hourly balancing-authority | [`texas-eia930-2021-2024.json`](../../data/sources/texas-eia930-2021-2024.json) | Already covers Minnesota: `load_eia930` declares MISO alongside ERCO/EPE/SWPP and loaded 8,760 MISO hours. No separate Minnesota acquisition was needed. |
| NOAA Storm Events 2021 and 2024 | [`minnesota-noaa-storm-events-2021-2024.json`](../../data/sources/minnesota-noaa-storm-events-2021-2024.json) | `load_storm_events` loaded 1,752 Minnesota rows (848 in 2021, 904 in 2024) over 1,743 events and 9 event types. |
| EAGLE-I 2021 and 2024 annual outages | [`minnesota-eaglei-2021-2024.json`](../../data/sources/minnesota-eaglei-2021-2024.json) | UTC streaming intake loaded 331,681 (2021) and 417,845 (2024) Minnesota observations, plus the MCC-2022 denominator for all 87 counties and five years of coverage history. |
| NTAD military bases FY2024 | [`minnesota-ntad-military-bases-fy2024.json`](../../data/sources/minnesota-ntad-military-bases-fy2024.json) | Acquired and digest-recorded (10 installations); **not loaded**, because `load_dod` associates each facility with a nearest synthetic bus and the bus model is Texas-only. |

## Where each source comes from

`datasets/catalog.json` is the machine-readable registry; `datasets/download.py
--group demo-mn` fetches the Minnesota-specific files. The two routes that
differ from Texas are worth naming here.

- **FEMA NRI.** The bulk archive
  `https://www.fema.gov/about/reports-and-data/openfema/nri/v120/NRI_Table_Counties.zip`
  returns **HTTP 403** to scripted clients (verified 2026-09-06 from two hosts
  and with a desktop user agent; the Akamai edge refuses it, and
  `hazards.fema.gov` refuses the same file). The working route is the ArcGIS
  FeatureServer query, which returns the identical 467-attribute county records
  that back the checked-in `NRI_Counties_TX.json`.
- **NWS zone-to-county crosswalks.** `bp10nv20.dbx` and `bp05mr24.dbx` were
  retrieved **live from weather.gov** and both match the SHA-256 values pinned
  in `datasets/catalog.json`. The Texas receipt reaches them through
  `web.archive.org`; that mirror is no longer required.

## Reproduce the Minnesota intake

The national artifacts (TIGER, EAGLE-I, Storm Events, PUDL, NWS crosswalks) are
the ones the Texas reproduce block already fetches. Only these two are
Minnesota-specific:

```sh
mkdir -p data/raw/nri/v1.20 data/raw/ntad_military_bases/fy2024
curl --fail --location --output data/raw/nri/v1.20/NRI_Counties_MN.json \
  'https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Counties/FeatureServer/0/query?where=STATEABBRV%3D%27MN%27&outFields=*&returnGeometry=false&f=json'
curl --fail --location --output data/raw/ntad_military_bases/fy2024/minnesota.geojson \
  'https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Military_Bases/FeatureServer/0/query?where=stateNameCode%3D%27MN%27&outFields=*&returnGeometry=true&outSR=4326&f=geojson'
```

Then load, in this order (counties must exist before the county-keyed sources):

```sh
uv run python -m pipelines.build_state_context --state MN \
  --tiger data/raw/tiger/2024/tl_2024_us_county.zip \
  --nri data/raw/nri/v1.20/NRI_Counties_MN.json \
  --eaglei 2021=data/raw/eaglei/2021/eaglei_outages_2021.csv \
  --eaglei 2024=data/raw/eaglei/2024/eaglei_outages_2024.csv \
  --eaglei-source-tz UTC

uv run python -m pipelines.build_state_context --state MN --raw-dir data/raw \
  --storm-events 2021=data/raw/storm_events/2021/StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz \
  --storm-events 2024=data/raw/storm_events/2024/StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz \
  --mcc data/raw/eaglei/support/MCC.csv \
  --coverage data/raw/eaglei/support/coverage_history.csv \
  --pudl-plants data/raw/pudl/v2026.2.0/out_eia__yearly_plants.parquet \
  --pudl-generators data/raw/pudl/v2026.2.0/out_eia__yearly_generators.parquet
```

`--eaglei-source-tz UTC` is not a default. EAGLE-I timestamps arrive without a
zone, and the loader refuses to run until the caller states the decision.

## What Minnesota has, next to Texas

Counts from one store holding both states after the loads above:

| Relation | MN | TX |
| --- | ---: | ---: |
| `counties` | 87 | 254 |
| `county_geo_meta` | 87 | 254 |
| `nri_hazards` | 870 | 2,540 |
| `hazard_static` | 87 | 254 |
| `eia_plants` | 909 | 1,584 |
| `storm_events` | 1,752 | 6,549 |
| `eaglei_outage_observations` | 749,526 | 5,364,241 |
| `county_customers` (`mcc_2022`) | 87 | 254 |
| `eaglei_coverage` | 5 | 5 |
| `ba_operations_hourly` | MISO 8,760 | ERCO 8,760 |

Every one of these relations is the *same table with the same columns* for both
states; the state is a `county_fips` prefix, not a separate schema.

## Boundaries this evidence does not cross

- **No Minnesota topology.** `buses`, `lines`, `gens`, `loads`,
  `synthetic_*` and `site_candidates` stay Texas-only. They come from the
  synthetic ACTIVSg2000 case, which is a Texas-shaped test system and not the
  actual ERCOT network — and nothing here supplies a Minnesota equivalent.
- **EAGLE-I coverage is thinner in Minnesota.** Maximum utility coverage runs
  71-80 percent of customers over 2018-2022, against a 63-94 percent Texas
  range, and 2021 reports only 79 of 87 counties. Validate overlap before
  comparing outage rates between the two states.
- **Storm Events zone expansion is bounded by the pinned crosswalks.** The two
  pinned NWS editions were selected for the Texas Uri and Beryl windows.
  Minnesota zone-type events outside those effective intervals are left
  unexpanded and recorded in `ingest_warnings` (194 interval warnings on this
  load) rather than mapped by a later edition.
- **`eia_generator_inventory` is national, not state-scoped.** Any state's
  EIA-860 load replaces the whole relation.
- **The published store manifest under-reports its scope.**
  `schema_meta.manifest` records `"state_scope":"tx"` because
  `pipelines.build_state_context` does not rewrite the manifest that
  `pipelines.build` wrote. The data is correct; the manifest's scope field is
  not, and a reader should use `ingest_log` scope keys instead.
