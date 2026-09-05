# Dataset ingestion pipeline — source schema and curation contract

**Status:** implementation-ready design  
**Owner:** data lane  
**Companion:** [`docs/plans/data-collection-and-curation-plan.md`](../../../docs/plans/data-collection-and-curation-plan.md) is the source-by-source execution plan. This document narrows it into the exact data to retain, reject, normalize, and prove for the ingest pipeline.

## Purpose and scope

This project needs one repeatable data path from public raw material to a small set of stable DuckDB/Parquet contract tables. The input plan covers a much broader universe than the product should load indiscriminately. This document prevents that drift.

The ingest pipeline must support:

1. a **synthetic** Texas electrical twin (ACTIVSg2000),
2. county-level observed-outage labels for historical events,
3. event weather and public operations signals,
4. public siting/critical-load/hazard screening, and
5. future nationwide extension without changing the public table contract.

It does **not** construct the real ERCOT topology, make a real interconnection determination, or retain unbounded copies of every source field. Synthetic network IDs and real-world facility IDs remain distinct.

## Design rules

### 1. Four layers, never one dumping ground

| Layer | Location | Contents | Git policy |
| --- | --- | --- | --- |
| Source registry | `data/sources/*.json` | URL, license, release/version, expected artifacts, checksums, schema note | tracked |
| Raw immutable artifact | `data/raw/<source>/<release>/` | Exact zip/CSV/Parquet/GeoJSON fetched from publisher | ignored |
| Staging / source-preserving helper | DuckDB helper table and, only when useful, `data/parquet/_helper/` | Retained fields that have analytical value but are not shared contracts | ignored |
| Curated product contract | `data/duck/grid.duckdb`, `data/parquet/<table>.parquet` | Stable, small tables used by the other lanes | ignored |

> **Executable authority: `pipelines/db.py`.** That module now defines **19** contract tables at
> `SCHEMA_VERSION 1.0.0`. The 13 listed above are the ingest-owned inputs; the other six are written
> by downstream lanes — `outage_predictions` (02), `cascade_runs` (03), `site_scores` (04),
> `line_upgrade_scores` and `line_upgrade_detail` (08), `corpus_chunks` (05, at ingest time per A4).
> Where this table and `pipelines/db.py` disagree, the module wins.

No source file is copied into `data/sources/`. The directory contains only reproducibility metadata and this design document.

### 2. Preserve evidence; do not preserve clutter

- Retain a raw artifact, SHA-256, publisher release/version, retrieval time, source URL, license/terms reference, and loader version for every ingest.
- Contract tables contain only fields explicitly needed by another lane. A useful source field goes into a named helper table only if it answers a stated product question, supports a quality check, or explains a derived value.
- Keep source-native IDs alongside normalized IDs. Do not use names or a nearest spatial match as a primary key.
- Do not promote point-to-line proximity, a synthetic-to-real nearest match, or a queue record into a claim of electrical connectivity.
- Fields that are completely null in a source release, unsupported by documentation, or unused by a documented derivation are excluded from curated storage. They remain available in the immutable raw artifact.

### 3. Invariants enforced by shared helpers

| Concern | Rule |
| --- | --- |
| Geography | EPSG:4326 in curated tables; point tables also carry `lon` and `lat`. Source CRS is recorded and converted explicitly. |
| County key | `county_fips` is a 5-character string everywhere. Names are display fields only. |
| Time | Preserve raw timestamp plus source timezone in staging; write a UTC, hour/15-minute aligned, timezone-naive timestamp into contract tables. Never silently assume a local time is UTC. |
| Units | Curated names carry units: `_mw`, `_mwh`, `_ms`, `_mm`, `_km`, `_pu`, `_c`. Record source unit and conversion in the manifest. |
| Revisions | Release/vintage is data. Never overwrite a prior raw artifact; re-ingest writes a new `source_release` in the log. |
| Idempotence | Each loader deletes/replaces only records belonging to its source key and release before inserting. A second identical run must have identical row counts and checksums. |
| Missingness | Null is unknown/not reported, never zero. Every high-volume time-series loader emits coverage and null-rate diagnostics. |

## Curated contract tables

The following columns are fixed by the build specs. Do not add source-specific columns to them; use helpers below instead.

| Contract table | Grain / primary identity | Required fields |
| --- | --- | --- |
| `buses` | synthetic bus | `bus_id`, `name`, `base_kv`, `lon`, `lat`, `county_fips`, `ba_code`, `coord_source`, `zone`, `area` |
| `lines` | synthetic branch | `line_id`, `from_bus`, `to_bus`, `base_kv`, `r_pu`, `x_pu`, `rate_a_mw`, `length_km`, `geom_wkb`, `is_transformer` |
| `gens` | synthetic generator | `gen_id`, `bus_id`, `fuel`, `pmax_mw`, `eia_plant_id` |
| `loads` | synthetic load | `load_id`, `bus_id`, `p_mw_nominal` |
| `counties` | Census county FIPS | `county_fips`, `name`, `state`, `pop`, `geom_wkb` |
| `critical_loads` | public critical facility | `cl_id`, `kind`, `name`, `lon`, `lat`, `bus_id`, `county_fips` |
| `eaglei_outages` | county × 15-minute timestamp | `county_fips`, `ts`, `customers_out` |
| `weather_hourly` | county × hour | `county_fips`, `ts`, `wind_ms`, `gust_ms`, `temp_c`, `ice_mm`, `precip_mm` |
| `storm_events` | NOAA event × affected county | `event_id`, `ts_begin`, `ts_end`, `county_fips`, `type`, `magnitude` |
| `hazard_static` | county FIPS | `county_fips`, `nri_score`, `wildfire_hazard`, `seismic_pga` |
| `ba_load_hourly` | balancing authority × hour | `ba_code`, `ts`, `demand_mw` |
| `site_candidates` | candidate site | `site_id`, `name`, `kind`, `lon`, `lat`, `county_fips`, `bus_id`, `capacity_slot_mw` |
| `scenarios` | named time window | `scenario_id`, `name`, `kind`, `ts_start`, `ts_end` |

## Source-by-source field contract

### P0 — load for the Uri/Beryl Texas demo

#### ACTIVSg2000 current bundle + MATPOWER case

**Purpose:** synthetic electrical skeleton. The current TAMU `ACTIVSg2000.aux` supplies coordinates; `case_ACTIVSg2000.m` supplies the electrical model. The June 2016 XLSX is explicitly excluded because its bus IDs/topology differ.

| Source fields to read | Curated destination | Retain in helper? | Why |
| --- | --- | --- | --- |
| `mpc.bus`: `BUS_I`, `BUS_TYPE`, `PD`, `QD`, `GS`, `BS`, `BUS_AREA`, `VM`, `VA`, `BASE_KV`, `ZONE`, `VMAX`, `VMIN` | `buses.bus_id`, `base_kv`, `area`, `zone`; `loads` from `PD`/`QD` as required by the grid parser | `synthetic_bus_electrical` for P/Q/shunt/voltage bounds | Needed for power flow and later voltage/VAR work; the public `buses` contract stays lean. |
| AUX `BusNum`, `BusName`, `BusNomVolt`, `SubNum`; AUX `Substation` `SubNum`, `SubName`, `SubID`, `Latitude`, `Longitude` | `buses.name`, `lon`, `lat`, `coord_source='tamu_aux'` | `synthetic_substations` with `sub_num`, `sub_name`, `sub_id` | Provides the only authoritative coordinates for this case and useful substation grouping. |
| `mpc.branch`: `F_BUS`, `T_BUS`, `BR_R`, `BR_X`, `BR_B`, `RATE_A`, `TAP`, `SHIFT`, `BR_STATUS`, angle bounds | `lines` | `synthetic_branch_electrical` for `b_pu`, tap, shift, status, angle bounds | Required electrical branch attributes; tap/status are valuable in cascade logic but not shared UI fields. |
| `mpc.gen`: bus, `PG`, `QG`, limits, voltage setpoint, `MBASE`, status, `PMAX`, `PMIN`; `mpc.genfuel`, `mpc.gentype`, `mpc.gencost` | `gens.bus_id`, `fuel`, `pmax_mw` | `synthetic_generator_electrical` for P/Q limits, status, cost coefficients, gen type | Supports dispatch/cascade expansion without polluting `gens`. Preserve order used to map fuel/type. |
| `mpc.bus_name` | `buses.name` | no duplicate required | Display/name fallback only. |

**Hard checks:** exactly 2,000 buses; AUX and case bus-ID sets match; all coordinates present; `coord_source` is never `tamu_xlsx`; 2,359 line branches + 847 impedance/transformer branches are represented; all map geometry is derived, not claimed real.

#### Census TIGER/Line counties

**Purpose:** canonical county polygons and all county-based joins.

| Read | Curated destination | Helper retention |
| --- | --- | --- |
| `STATEFP`, `COUNTYFP`, `GEOID`, `NAME`, `NAMELSAD`, `STUSPS`, `ALAND`, `AWATER`, geometry | `counties.county_fips=GEOID`, `name`, `state`, `geom_wkb` | `county_geo_meta` with land/water area and TIGER vintage |

Filter Texas with `STATEFP='48'`, convert source EPSG:4269 to EPSG:4326, and preserve the TIGER vintage. `ALAND`/`AWATER` are beneficial for density and water-context features, but not needed in the shared table.

#### FEMA National Risk Index (NRI)

**Purpose:** county static hazard context, resilience, and explainability.

| Read | Curated destination | High-value helper fields to retain |
| --- | --- | --- |
| `STCOFIPS`, `POPULATION`, `RISK_SCORE` | `counties.pop`, `hazard_static.nri_score` | `source_release`, `risk_rating`, `EAL_VALT`, `EAL_RATNG`, `SOVI_SCORE`, `SOVI_RATNG`, `RESL_SCORE`, `RESL_RATNG` |
| Individual-hazard risk / expected annual loss columns | none directly | `nri_hazards`: `county_fips`, hazard code, risk score/rating, EAL value/rating, annualized frequency, exposure where present |

At minimum retain the high-value energy/outage hazards: winter weather (`WNTW_*`), hurricane (`HRCN_*`), strong wind (`SWND_*`), ice storm (`ISTM_*`), wildfire (`WFIR_*`), flood/flash flood, heat wave, tornado, and lightning. Store them in long form rather than hundreds of wide columns. Read FIPS as text; a browser-like User-Agent can be rejected by FEMA.

#### PUDL EIA-860 plant and generator outputs

**Purpose:** public real-generator context and retiring-coal/nuclear candidate seeding. Use a **versioned PUDL release**, not `nightly`, for a reproducible build. The loader may optionally compare the latest nightly schema before a planned release bump, but must never ingest it silently.

| Read | Curated destination | High-value helper fields to retain |
| --- | --- | --- |
| `out_eia__yearly_plants`: `report_date`, `plant_id_eia`, `plant_name_eia`, `state`, `county`, `latitude`, `longitude`, BA/ISO/NERC, utility IDs/name where available | `eia_plants` helper; spatial county FIPS; candidate `name`, coordinates | `eia_plant_attributes`: report date, city, BA/ISO/NERC, utility, sector, NAICS, source provenance |
| `out_eia__yearly_generators`: `plant_id_eia`, `generator_id`, `report_date`, `capacity_mw`, `prime_mover_code`, energy source/fuel, status/code, retirement and planned-retirement dates | `eia_plants.capacity_mw`, primary fuel, retirement year/status; `site_candidates` | `eia_generator_inventory` at plant/unit/year grain with all listed fields plus summer/winter capacity, planned operating date, ownership if available |

Only use the latest `report_date` per plant/unit for the demo view, but retain the reporting history in the helper table. `plant_id_eia + generator_id + report_date` is the unit grain. `county` is a name, not a join key: derive county FIPS by point-in-polygon. Matching real EIA plants to synthetic generation is a labeled proximity/fuel-class helper, never an assertion of physical correspondence.

#### EIA-930 balancing authority operations

**Purpose:** demand scaling and observed operations context.

| Read | Contract destination | High-value helper fields to retain |
| --- | --- | --- |
| `Balancing Authority`, `UTC Time at End of Hour`, `Demand (MW) (Adjusted)`, `Demand (MW)` | `ba_load_hourly.ba_code`, `ts`, `demand_mw` | raw and adjusted demand; `Demand (MW) (Imputed)`; local end time; data date/hour number |
| `Demand Forecast (MW)`, `Net Generation (MW)`, `Total Interchange (MW)`, `Sum(Valid DIBAs) (MW)` | none | `ba_operations_hourly` with forecast, net generation, interchange, valid DIBAs and derived forecast error |
| Available fuel-generation columns | none | `ba_fuel_generation_hourly` in long form: BA, timestamp, fuel, MW, source column/version |

Use the adjusted-demand value when present, otherwise actual demand. Keep `ERCO`, `EPE`, `SWPP`, and `MISO` for Texas-boundary context. The end-of-hour UTC timestamp is the canonical time. Forecast error and interchange are highly useful to explain stressed periods, but do not belong in `ba_load_hourly` because its interface is intentionally narrow.

#### EAGLE-I outages + county customer counts

**Purpose:** validation labels; the core observed-outage data.

| Read | Contract destination | High-value helper fields to retain |
| --- | --- | --- |
| Yearly CSV: `fips_code`, `county`, `state`, `customers_out`, `run_start_time` | `eaglei_outages.county_fips`, `ts`, `customers_out` | `eaglei_outage_observations`: source year/file/release, raw time string, county/state display text, coverage and quality flags |
| 2024-only `total_customers` | no direct contract field | `county_customers` at county × source-year; `outage_fraction` is derived, never treated as source truth |
| `MCC.csv`: `County_FIPS`, `Customers` | no direct contract field | `county_customers` with denominator source=`mcc_2022` |
| `coverage_history.csv` and `DQI.csv` | none | `eaglei_coverage` and `eaglei_quality` long tables |

Load Texas rows with a streaming DuckDB scan, never pandas. Pad all FIPS to five characters. `run_start_time` arrives timezone-naive: hold the raw string and block promotion to `ts` until the source-timezone decision is recorded and the Uri peak acceptance check passes. Store the 2024 `total_customers` separately from MCC because the two denominators may not represent identical vintages. Do not replace missing outage values with zero.

#### NOAA Storm Events + NWS zone/county crosswalk

**Purpose:** event-level labels and interpretable county features.

| Read | Contract destination | High-value helper fields to retain |
| --- | --- | --- |
| `EVENT_ID`, `EPISODE_ID`, begin/end date-time, `CZ_TIMEZONE`, `EVENT_TYPE`, `MAGNITUDE`, `MAGNITUDE_TYPE`, `CZ_TYPE`, `CZ_FIPS`, `STATE_FIPS`, state, source location fields | `storm_events.event_id`, UTC begin/end, `county_fips`, type, magnitude | `storm_event_attributes` with episode ID, location type/id/name, magnitude type, injuries/deaths, damage fields, data source, raw timestamps/timezone, assignment method |
| NWS correlation: state, zone, county FIPS, timezone; zone geometry when used | none | `storm_zone_county_crosswalk` with source edition and mapping method |
| Event narratives | none | leave in compressed raw by default; extract only on demand for a cited explanation |

County-zone expansion is mandatory for February 2021 Texas winter events. Mark every output row with `assignment_method = direct_county | nws_crosswalk | zone_centroid_fallback`; downstream modeling can then test sensitivity instead of treating all mappings as equally certain. Normalize magnitude only when source units are known; retain `magnitude_type` in the helper to disambiguate knots and other measures.

#### NOAA HRRR weather

**Purpose:** county-hour hazard covariates for the selected scenario windows.

| GRIB field / processing | Contract destination | High-value helper fields to retain |
| --- | --- | --- |
| `UGRD`, `VGRD` at 10 m; `hypot(u,v)` | `weather_hourly.wind_ms` | source run/init, forecast lead, grid-cell count/weight, mean U/V for direction if required later |
| `GUST` surface | `weather_hourly.gust_ms` | grid aggregation diagnostics |
| `TMP` at 2 m, Kelvin to Celsius | `weather_hourly.temp_c` | min/max/standard deviation within county, not only mean |
| `APCP` f01 0–1 h accumulation | `weather_hourly.precip_mm` | source field, lead window, aggregation count |
| `FRZR` f01 0–1 h accumulation | `weather_hourly.ice_mm` | `ice_is_proxy` flag if fallback calculation is used |

Use HRRR analysis `f00` for wind/temperature and **f01** for one-hour accumulated precipitation/freezing rain. Reading `f00` accumulations produces zeros and is a hard failure. Persist a `weather_source_runs` helper with source model, grid/version, init time, lead, fields, retrieval location, and county-grid-index version. Do not retain full statewide GRIB in DuckDB; raw GRIB stays immutable and the county index is cached as Parquet.

#### NTAD DoD installations

**Purpose:** public critical-load screening only.

| Read | Contract destination | High-value helper fields to retain |
| --- | --- | --- |
| `siteName`, `siteReportingComponent`, `siteOperationalStatus`, `stateNameCode`, `isJointBase`, polygon geometry | `critical_loads` for active Texas bases, with centroid point, county/bus match | `critical_load_geometry`: source ID, component, status, joint-base flag, polygon WKB, projected area, centroid method, distance/match method |

Filter `stateNameCode='tx'`, `siteOperationalStatus='act'`, and the documented area threshold. Compute area/centroid in a projected CRS (Texas Albers), then transform the centroid to WGS84. The bus association is a synthetic-nearest proxy, not a claim of service connection.

#### NWS active alerts

**Purpose:** optional live forecast-layer features, distinct from historical evidence.

| Read | Contract destination | High-value helper fields to retain |
| --- | --- | --- |
| Alert `id`, `sent`, `effective`, `onset`, `expires`, `ends`, `event`, severity, certainty, urgency, status, message type, area description, geometry, response | none | `nws_alerts_snapshot` keyed by alert ID + snapshot time; `nws_alert_county_features` keyed county × hour |

Store immutable GeoJSON snapshots under `data/raw/nws/` with the required descriptive User-Agent. The contract has no live-alert table; derive only documented county flags such as wind/ice/fire/heat from active alerts. An alert is a warning, not measured weather damage or outage evidence.

### P1 — add only after P0 quality gates pass

| Source | Required fields and target | Valuable extra fields / rules |
| --- | --- | --- |
| EIA-861 reliability + service territory | Reliability fields needed for `utility_reliability`: utility ID/name, report year, SAIDI/SAIFI and customer denominator where documented. Service territory: utility ID, county/state, legal/territory flags; feeds `utility_county` and BA map. | Retain reporting status, major-event-exclusion flags, service-territory provenance, BA code, retail sales/customer classes. Do not convert utility territory to a county total without an allocation method. |
| NOAA ISD station hourlies | Station ID, timestamp, station lon/lat/elevation, `WND`, `TMP`, `AA1`, `OC1`, `AW1`/`MW1`; aggregate to the same `weather_hourly` fields. | `isd_station_observations` retains source/quality flags and station values; `weather_interpolation_diagnostics` retains k-nearest stations, distance/weights and source=`isd`. ISD freezing-rain value is a proxy, so mark it. |
| OSM / HIFLD lines, substations, hospitals | Real public geometry becomes helper `real_lines`, `real_substations`, or `critical_loads(kind='hospital')`. | Keep source element/feature ID, version/date, voltage/owner only when published, geometry, attribution, and completeness warning. Never merge real lines into synthetic `lines`/`buses`. |
| USFS Wildfire Hazard Potential | Sample latest WHP raster/FileGDB at county or candidate-site geometry into `hazard_static.wildfire_hazard`. | Keep edition, method (centroid/area mean), CRS/raster resolution and sampled distribution in `hazard_sampling`. |
| USGS NSHM 2023 PGA | Join/summarize correct PGA contour product into `hazard_static.seismic_pga`. | Keep exceedance probability/time horizon, source contour value, and spatial method. It is a contour polygon dataset, not a raster by default. |
| EIA-923 / EPA CEMS | Optional plant historical operations: `plant_id_eia`, unit/facility ID, report period, generation, fuel and emissions/load fields. | Build standalone `plant_operations_monthly` and `cems_unit_hourly`, preserving source coverage. Do not use a missing CEMS unit as a non-operating unit. |
| EIA-930 national history / ACTIVSg10k/25k/70k | Same schemas with a case/version dimension. | Do not conflate Texas-tuned assumptions with national-scale scenario parameters. |

### P2 / explicitly scoped additions

| Source | Keep if the feature is activated | Exclude until then |
| --- | --- | --- |
| HIFLD/OSM water utilities | source ID, name/type, geometry, county, source vintage for `critical_loads(kind='water')` | speculative demand or customer counts |
| FEMA NFHL, NHDPlus, PAD-US, 3DEP, NWI | source geometry/rasters and candidate-buffer overlap statistics for the siting lane | raw spatial attributes irrelevant to the stated exclusion or buffer rule |
| ERCOT public reports/queue | report ID, publication/delivery time, product fields required by a named scenario; queue project ID, status, technology, MW, zone, milestone dates | credentials, unbounded report archives, or a claim that queued MW is operational capacity |
| DOE-417 / FEMA declarations / NHC tracks | event ID, date/time, counties/geometry and selected event attributes for an event registry | treating a declaration/report as equipment-level causality |

## Helper-table dictionary

These helpers deliberately isolate source detail from the product contract. Every helper includes `source`, `source_release`, `source_file`, `loaded_at`, and a deterministic source record key.

| Helper | Grain | Purpose |
| --- | --- | --- |
| `ingest_log` | raw artifact × ingest run | checksum, URL, bytes, rows, schema fingerprint, loader version, status/error |
| `ingest_warnings` | source record × issue | unmapped geometry, missing FIPS/timezone, schema drift, unit concern |
| `county_geo_meta` | county × TIGER vintage | land/water area and geometry provenance |
| `synthetic_bus_electrical`, `synthetic_branch_electrical`, `synthetic_generator_electrical`, `synthetic_substations` | source asset | electrical detail omitted from UI-facing tables |
| `eia_plants`, `eia_plant_attributes`, `eia_generator_inventory` | EIA plant/unit × report date | inventory history, candidate seed traceability |
| `eaglei_outage_observations`, `county_customers`, `eaglei_coverage`, `eaglei_quality` | county × interval/year | denominators, coverage, DQI, and outage-label provenance |
| `ba_operations_hourly`, `ba_fuel_generation_hourly` | BA × hour | operational context beyond demand |
| `storm_event_attributes`, `storm_zone_county_crosswalk` | source event / zone mapping | event mapping uncertainty and units |
| `weather_source_runs`, `weather_interpolation_diagnostics` | model run / county-hour | reproducible county weather aggregation |
| `nri_hazards`, `hazard_sampling` | county × hazard / sampled target | transparent hazard components and spatial method |
| `critical_load_geometry`, `critical_load_bus_dist` | facility / facility-to-synthetic-bus match | geometry, matching method, and distance without overclaiming connectivity |
| `real_lines`, `real_substations` | public geospatial feature | overlay-only public infrastructure |
| `utility_reliability`, `utility_county` | utility × year / utility × county | EIA-861 reliability and territory crosswalk |

## Per-source manifest contract

Every tracked registry record in `data/sources/` should conform to this shape; it is intentionally metadata-only:

```json
{
  "source_id": "eaglei",
  "publisher": "Oak Ridge National Laboratory",
  "license": "CC-BY-4.0",
  "access": "public",
  "release": "article-version-or-date",
  "artifacts": [
    {
      "logical_name": "eaglei_outages_2021.csv",
      "url": "https://…",
      "expected_format": "csv",
      "expected_schema": ["fips_code", "county", "state", "customers_out", "run_start_time"],
      "required": true,
      "sha256": null
    }
  ],
  "loader": "pipelines.eaglei:load_eaglei",
  "destinations": ["eaglei_outages", "county_customers"],
  "notes": ["timestamps require source-timezone verification"]
}
```

On fetch, `record_source.py` must fill `retrieved_at`, exact bytes, SHA-256, content type, and a schema fingerprint. On ingest, `ingest_log` records the matching registry artifact and loader Git revision. A schema mismatch is a stop condition, not an invitation to automatically drop/rename columns.

## Implementation order and gates

1. **Registry and schema:** add one metadata manifest per P0 source; create contract and helper DDL; implement shared FIPS/time/geometry/provenance functions.
2. **Static foundations:** TIGER → counties; NRI → population/hazard helpers; ACTIVSg2000 case+AUX → synthetic assets; run coordinate and case-version assertions.
3. **Time-series truth:** EIA-930; EAGLE-I + denominators/coverage; Storm Events + zone crosswalk; HRRR county aggregation. Block model work if timezones, expected cadence, or event anchors fail.
4. **Context layers:** version-pinned PUDL EIA-860; DoD; NWS snapshots; construct candidate/proximity helpers with explicit synthetic-match labels.
5. **Export and test:** export each contract table to Parquet; record all raw artifacts; rerun ingest to prove idempotence; only then add P1 sources.

### Minimum quality gates

| Gate | Assertion |
| --- | --- |
| Case integrity | 2,000 current-case buses; all have AUX coordinates; no June-2016 coordinate source; expected branch/generator/load counts. |
| Geographic integrity | 254 Texas counties; all FIPS length five; >=99% bus-to-county match with fallback count logged. |
| EAGLE-I integrity | 15-minute cadence; no negative outage values; Uri statewide peak equals the documented acceptance anchor after timezone normalization; coverage gaps visible. |
| Weather integrity | exact hourly UTC cadence; no all-zero Uri `precip_mm`/`ice_mm`; Panhandle cold anchor passes; source run/lead recorded. |
| Event integrity | direct and zone-expanded events are distinguishable; magnitude type retained; no silent county assignment. |
| Operations integrity | no duplicate BA/hour; ERCO demand uses adjusted-or-raw fallback; null/imputation flags retained in helper. |
| Candidate integrity | real source IDs and PUDL vintage present; nearest synthetic-bus distance/method recorded; no real-grid connection claim. |
| Provenance integrity | every curated source has a registry entry, raw checksum, schema fingerprint, and `ingest_log` row. |

## Deliberate exclusions

- No CEII, utility feeder maps, confidential interconnection studies, account credentials, or live user tokens.
- No attempt to map a synthetic branch to a public HIFLD/OSM line or a synthetic generator to a real EIA unit as fact.
- No wholesale retention of NRI’s hundreds of wide hazard fields; only its long-form hazard helper and stated composite/community fields.
- No long narrative text, duplicate geometries, raw GRIB grid cells, or full source exports inside the product database when a raw artifact plus documented aggregate is sufficient.
- No nationwide pulls before P0 passes: the Texas event path is the proof point, and P1/P2 are gated expansions rather than a data-hoarding exercise.

## Result

This pipeline produces a compact, auditable data product: stable contract tables for the app and models; carefully named helpers for genuinely valuable source detail; and raw, versioned evidence outside the repository. It protects the demo from two common failures at once—untraceable data sprawl and falsely precise claims about a real electric grid.
