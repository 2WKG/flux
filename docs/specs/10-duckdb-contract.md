# 10 — DuckDB fixture contract

**Contract version:** `1.0.0`  
**Status:** canonical concrete DDL for the next-wave fixture database  
**Implementation:** `pipelines/db.py`  
**Database:** `data/duck/grid.duckdb`

This document makes the shared table summary in [00-overview.md](00-overview.md)
implementable. It keeps that overview's table names, UTC `TIMESTAMP` choice,
and EPSG:4326 geometry rule. `pipelines.db.SCHEMA_STATEMENTS` is the normative
DDL; this document defines its meanings. Any change to a table, key, type,
unit, or semantic requires a new contract version and explicit migration.

## Global rules

- `TIMESTAMP` values are UTC, timezone-naive DuckDB values with microsecond
  precision. Ingest converts source times to UTC; APIs emit a trailing `Z`.
  `ts` is an observation instant; `ts_begin`/`ts_end` bound an event.
- `geom_wkb` is OGC WKB in WGS 84 / EPSG:4326 using `(longitude, latitude)`.
  Point tables use decimal-degree `lon`/`lat`; Web Mercator and screen `x`/`y`
  values never enter DuckDB.
- Every fixture row includes `source_name`, `source_ref`, `source_version`,
  `source_retrieved_at`, and `fixture_batch_id`. `source_ref` is a stable URL,
  path, or record ID; derived rows name their Flux module and input artifact/run.
- `NULL` is the only unavailable-value marker. It means that the source, join,
  or successful calculation did not supply a value; it never means zero, empty
  string, `NaN`, `-1`, or an invented default. A missing derived row means its
  computation was not run or failed, never zero impact. Consumers surface it as
  unavailable. Numeric zero always means an observed/calculated zero.
- Numeric values are finite. Percent fields are `0..100`; `p_out` is `0..1`.

## Identity and relationships

`bus_id`, `line_id`, `gen_id`, and `load_id` are deterministic source-case
identifiers. `line_id` identifies one MATPOWER branch row and
`(from_bus,to_bus,circuit)` is also unique. `site_id`/`cl_id` are deterministic
fixture IDs; immutable upstream IDs live in `source_site_id`/`source_ref`.
`county_fips` is a zero-padded five-character Census FIPS. `scenario_id` is a
stable slug. `run_id` identifies an execution; `(run_id,hour)` identifies its
saved hour. `chunk_id` identifies a retrieval chunk, while
`(doc,page,chunk_ordinal)` protects deterministic re-chunking.

All documented foreign keys are enforced in the DDL except
`site_scores.scenario_id`: the aggregate value `all` is deliberately valid
there alongside a real scenario. An unconnected site has `bus_id = NULL`; its
grid-value fields are `NULL`, while its safety screen remains valid.

## Units and encoded structures

| Field suffix | Unit / encoding |
| --- | --- |
| `_mw`, `_mwh`, `_kv`, `_km` | megawatts, megawatt-hours, nominal line-to-line kilovolts, kilometres |
| `_pu`, `_ms`, `_c`, `_mm` | source-case per unit, metres/second, degrees Celsius, millimetres |
| `_usd`, `_usd_yr`, `_musd`, `_yr` | source-year USD, USD/year, MW per USD million, years; provenance identifies the source/year |
| `_pct`, `p_out`, `pop`, `customers_*` | percent (0–100), probability (0–1), people, customer accounts |
| `seismic_pga`, `conductor_kcmil` | peak ground acceleration in `g`, thousands of circular mils |
| `*_json` | valid JSON, not stringified Python; cascade and safety object shapes remain owned by specs 03 and 04 |

## Table catalogue

All tables include the five provenance fields. `?` marks a nullable field;
the canonical DDL adds the exact checks and foreign keys.

| Table | Primary key / uniqueness | Columns | Nullable fields |
| --- | --- | --- | --- |
| `counties` | `county_fips` | `county_fips TEXT`, `name TEXT`, `state TEXT`, `pop BIGINT`, `geom_wkb BLOB` | — |
| `buses` | `bus_id` | `bus_id BIGINT`, `name TEXT`, `base_kv DOUBLE`, `lon DOUBLE`, `lat DOUBLE`, `county_fips TEXT`, `ba_code TEXT`, `coord_source TEXT`, `zone INTEGER`, `area INTEGER` | county/BA/zone/area |
| `lines` | `line_id`; endpoints/circuit | `line_id BIGINT`, `from_bus BIGINT`, `to_bus BIGINT`, `circuit TEXT`, `base_kv DOUBLE`, `r_pu DOUBLE`, `x_pu DOUBLE`, `rate_a_mw DOUBLE`, `length_km DOUBLE`, `geom_wkb BLOB`, `is_transformer BOOLEAN` | rating, geometry |
| `gens` | `gen_id`; bus/unit | `gen_id BIGINT`, `bus_id BIGINT`, `fuel TEXT`, `pmax_mw DOUBLE`, `eia_plant_id BIGINT`, `source_unit_id TEXT` | EIA match |
| `loads` | `load_id`; one per bus | `load_id BIGINT`, `bus_id BIGINT`, `p_mw_nominal DOUBLE` | — |
| `critical_loads` | `cl_id` | `cl_id BIGINT`, `kind TEXT`, `name TEXT`, `lon DOUBLE`, `lat DOUBLE`, `bus_id BIGINT`, `county_fips TEXT` | electrical bus |
| `eaglei_outages` | county/time | `county_fips TEXT`, `ts TIMESTAMP`, `customers_out BIGINT` | — |
| `weather_hourly` | county/time | `county_fips TEXT`, `ts TIMESTAMP`, `wind_ms DOUBLE`, `gust_ms DOUBLE`, `temp_c DOUBLE`, `ice_mm DOUBLE`, `precip_mm DOUBLE` | each weather measurement |
| `storm_events` | event/county | `event_id BIGINT`, `county_fips TEXT`, `ts_begin TIMESTAMP`, `ts_end TIMESTAMP`, `type TEXT`, `magnitude DOUBLE` | magnitude |
| `hazard_static` | `county_fips` | `county_fips TEXT`, `nri_score DOUBLE`, `wildfire_hazard DOUBLE`, `seismic_pga DOUBLE` | each hazard |
| `ba_load_hourly` | BA/time | `ba_code TEXT`, `ts TIMESTAMP`, `demand_mw DOUBLE` | — |
| `site_candidates` | `site_id`; source/site | `site_id BIGINT`, `name TEXT`, `kind TEXT`, `lon DOUBLE`, `lat DOUBLE`, `county_fips TEXT`, `bus_id BIGINT`, `capacity_slot_mw DOUBLE`, `source_site_id TEXT` | electrical bus |
| `scenarios` | `scenario_id` | `scenario_id TEXT`, `name TEXT`, `kind TEXT`, `ts_start TIMESTAMP`, `ts_end TIMESTAMP` | — |
| `outage_predictions` | scenario/county/time | `scenario_id TEXT`, `county_fips TEXT`, `ts TIMESTAMP`, `p_out DOUBLE`, `customers_at_risk BIGINT`, `driver TEXT` | — |
| `cascade_runs` | run/hour | `run_id TEXT`, `scenario_id TEXT`, `hour INTEGER`, `tripped_element_ids_json JSON`, `lost_load_mw DOUBLE`, `counties_dark_json JSON`, `critical_loads_lost_json JSON`, `counterfactual_site_id BIGINT` | counterfactual site on baseline |
| `site_scores` | site/scenario/unit | `site_id BIGINT`, `scenario_id TEXT`, `unit_mw DOUBLE`, `safety_score DOUBLE`, `safety_flags_json JSON`, `grid_value_score DOUBLE`, `lol_reduction_mwh DOUBLE`, `congestion_relief_pct DOUBLE`, `blackstart_reach_mw DOUBLE` | four grid-value fields |
| `line_upgrade_scores` | `line_id` | `line_id BIGINT`, `congestion_usd_yr DOUBLE`, `dlr_uplift_mw DOUBLE`, `reconductor_uplift_mw DOUBLE`, `dlr_cost_usd DOUBLE`, `reconductor_cost_usd DOUBLE`, `mw_per_musd DOUBLE`, `ferc_screen_pass BOOLEAN`, `spark_eligible BOOLEAN` | source-dependent scores/flags |
| `line_upgrade_detail` | `line_id` | `line_id BIGINT`, `owner TEXT`, `conductor_material TEXT`, `conductor_kcmil DOUBLE`, `static_rating_mw DOUBLE`, `aar_rating_mw DOUBLE`, `dlr_p50_mw DOUBLE`, `dlr_hours_above_static INTEGER`, `best_tech TEXT`, `payback_yr DOUBLE`, `congestion_method TEXT`, `region TEXT` | owner/conductor/detail, best tech/payback |
| `corpus_chunks` | `chunk_id`; doc/page/ordinal | `chunk_id TEXT`, `doc TEXT`, `title TEXT`, `page INTEGER`, `chunk_ordinal INTEGER`, `text TEXT`, `embedding FLOAT[1024]` | embedding only |

## Semantics that are easy to get wrong

- `lines` includes both AC lines and impedance-transformer branches. A
  transformer has `is_transformer=TRUE`, `length_km=0`, and the higher endpoint
  nominal voltage in `base_kv`; `rate_a_mw` is the source-case thermal rating.
- `weather_hourly.ts` is the beginning of the UTC hour. EAGLE-I stays at its
  source 15-minute cadence. `outage_predictions.ts` starts a six-hour UTC
  prediction window. One NOAA zone event may expand to many counties, hence the
  composite `storm_events` key.
- `site_candidates.kind` is exactly `coal_retired`, `coal_retiring`,
  `nuclear_existing`, `doe_federal`, or `dod`; no `federal`/`defense` aliases.
- Baseline run IDs are `<scenario_id>-s<seed>-<sha8(forced_out)>`; persisted
  site counterfactuals are `<scenario_id>-s<seed>-cf-<site_id>-<unit_mw>`.
  `hour` is an integer offset from scenario start. `site_scores.scenario_id`
  equal to `all` is an explicit aggregate, never a missing scenario.
- `line_upgrade_detail.congestion_method='twin_proxy'` must not be presented as
  an RTO shadow-price result. `embedding=NULL` means BM25-only retrieval, never
  a zero vector.

## Verification

Run `uv run --extra dev pytest tests/test_schema_contract.py`. The focused test
creates the schema twice in memory, verifies the contract version and required
tables, and asserts the optional `FLOAT[1024]` embedding declaration.
