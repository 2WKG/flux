# 01 — Data ingest (Layers 1 + 2: grid twin skeleton, geography, load, weather, hazard, outages)

Status: build spec, weekend scope. Texas first (ACTIVSg2000 / ERCOT); national is a scale slide.
All access facts below were checked on 2026-09-05 with `curl -I` / WebFetch unless tagged
`[UNVERIFIED]` or `[GATED: …]`. Where this spec conflicts with the pitch doc, this spec wins
(notably: EAGLE-I is open on figshare, no Globus; ACTIVSg2000 geography is a curl-able Google
Drive zip from the TAMU page and the electrical case ships inside the `matpower` pip package —
no TAMU form needed).

## Purpose

Produce one DuckDB file, `data/duck/grid.duckdb`, that every downstream layer (twin, outage
model, siting, causal, copilot, web) reads and never writes to except through the tables named
here. Ingest is idempotent, per-source, and runs from `scripts/data/download.sh` (raw fetch)
followed by `uv run python -m pipelines.build` (load + derived joins). Priority is a P0 set that
is sufficient for the Winter Storm Uri Texas demo, P1 for the national scale slide, P2 stretch.

Shared contract (do not rename): repo layout `data/raw/<source>/` (gitignored),
`data/duck/grid.duckdb`, `data/parquet/`, `pipelines/`, `twin/`, `models/outage/`, `siting/`,
`causal/`, `copilot/`, `web/`, `docs/specs/`, `scripts/data/download.sh`. Python 3.12, uv,
`pyproject.toml` at root. All geometry EPSG:4326, stored as WKB `BLOB` columns (`geom_wkb`)
plus plain `lon`/`lat` doubles on point tables; DuckDB `spatial` extension is loaded for joins.

## Inputs

### Priority ladder

| Pri | Source | Needed for |
|---|---|---|
| P0 | ACTIVSg2000 (matpower pip) | twin skeleton, `buses/lines/gens/loads` |
| P0 | Census TIGER 2024 counties | `counties`, bus→county join |
| P0 | FEMA NRI v1.20 county table | `counties.pop`, `hazard_static.nri_score` |
| P0 | EAGLE-I 2021 + 2024 (+ MCC.csv) | `eaglei_outages`, labels for outage model |
| P0 | NOAA Storm Events 2021, 2024 | `storm_events` (features + scenario bounds) |
| P0 | HRRR via herbie/AWS for the four scenario windows | `weather_hourly` |
| P0 | EIA-930 BALANCE 2021 H1, 2024 H2 | `ba_load_hourly` (ERCO) |
| P0 | EIA-860 via PUDL parquet | `gens.eia_plant_id`, coal-site candidates |
| P0 | NTAD Military Bases (DoD) | `critical_loads(kind='dod')` |
| P0 | NWS alerts API | `forecast_72h` live layer |
| P1 | EAGLE-I 2018–2020, 2022, 2023, 2025 | full training set |
| P1 | HIFLD archived lines/substations (DataLumos) or OSM power tags | real geometry overlay |
| P1 | HIFLD hospitals archive / OSM `amenity=hospital` | `critical_loads(kind='hospital')` |
| P1 | EIA-861 Reliability (SAIDI/SAIFI) | outage-model + causal confounder |
| P1 | USFS WHP 2023, USGS NSHM 2023 | `hazard_static.wildfire_hazard/seismic_pga` |
| P1 | ACTIVSg10k/25k/70k (matpower pip) | national scale slide |
| P2 | ACTIVSg82k (TAMU form) | national twin |
| P2 | NOAA ISD station hourlies | HRRR fallback |
| P2 | Water utilities (`critical_loads.kind='water'`) via OSM `man_made=water_works` | critical-load panel completeness |

### Source-by-source

Each entry: URL · format · size · license/gating · loader · target table.

**S1. ACTIVSg2000 (Texas synthetic 2000-bus grid)** — P0
- **Geography + tables (verified, open, curl-able):** the TAMU page's "here" link is a Google
  Drive zip, `https://drive.google.com/uc?export=download&id=1tOIK_RVQaZZDo_oIi75bVdPsAlQ7J1l9`
  (2.1 MB, downloads with plain curl; unpacks to
  `data/raw/activsg2000/Texas 2000 - June 2016 Synthetic Case/Texas2000_June2016.{AUX,EPC,m,pwb,pwd,RAW,xlsx}`).
  `Texas2000_June2016.xlsx` has clean sheets (verified with pandas):
  `Substations(Substation Number, Substation Name, Area Name, Latitude, Longitude, Maximum Nominal kV)`,
  `Buses(Bus Number, Bus Name, Area Name, Substation Number, Nominal kV)`,
  `Lines(From Bus Number, To Bus Number, Circuit Number, R pu, X pu, B pu, MVA Limit)`,
  `Transformers(...)`, `Loads(Bus Number, MW, Mvar)`, `Generators`, `Shunts`, `Areas`.
  **This xlsx is the source of record for `buses/lines/gens/loads`**: `buses.lon/lat` come from
  `Buses → Substations` on `Substation Number`; `coord_source='tamu_xlsx'`.
- **Electrical model (twin only):** the pip `matpower` package (already in `pyproject.toml`) bundles
  `.venv/lib/python3.12/site-packages/matpower/data/case_ACTIVSg2000.m` (plus
  `scenarios_ACTIVSg2000.m`, `contab_ACTIVSg2000.m`); the GitHub copy
  `https://raw.githubusercontent.com/MATPOWER/matpower/master/data/case_ACTIVSg2000.m` was verified
  to carry `mpc.bus_name` (~line 7459), `mpc.gentype` (~6363), `mpc.genfuel` (~6911) but no lat/lon.
  It loads in pandapower 3.5 via `from pandapower.converter.matpower import from_mpc` (needs
  `matpowercaseframes`, in pyproject): 2,000 buses / 2,359 lines / 847 transformers / 544 gens /
  1,125 loads / 67,109 MW; `pp.rundcpp` solves in 0.84 s (verified by the coordinator).
  `gens.fuel` comes from `mpc.genfuel` (joined on `GEN_BUS` + order); the xlsx `Generators` sheet
  is the fallback if the join is ambiguous.
- CSV mirror (no coordinates, backup only): `https://raw.githubusercontent.com/caseformat/ACTIVSg2000/master/{bus,branch,gen,gencost,case}.csv`
  (header verified `BUS_I,BUS_TYPE,PD,QD,GS,BS,BUS_AREA,VM,VA,BASE_KV,ZONE,...`).
- Name-geocode fallback (only if the xlsx is unavailable): `Bus Name` values are Texas place
  names with a numeric suffix (e.g. `ODESSA 2 0`); strip the suffix and fuzzy-match (rapidfuzz ≥ 90)
  against the Census 2024 place gazetteer
  `https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip`
  (verified; `INTPTLAT`,`INTPTLONG`, filter `USPS='TX'`), `coord_source='gazetteer'`.
  A manual override CSV `data/raw/activsg2000/bus_coords_manual.csv` (`bus_id,lon,lat`) wins over both.
- License: TAMU states free for commercial/non-commercial use; cite Birchfield et al. 2017
  (doi 10.1109/TPWRS.2016.2616385). No CEII. The June-2016 xlsx and the pip `.m` are the same
  case family; bus numbers agree `[UNVERIFIED: spot-check 20 bus numbers/kV between xlsx and .m in AC #2]`.
- Loader: `pipelines/activsg.py::load_activsg(con, xlsx_path, case="ACTIVSg2000")` → `buses`, `lines`, `gens`, `loads`.
- Twin handoff: `pipelines/activsg.py::to_pandapower(case) -> pandapowerNet` via `from_mpc`; the net
  is pickled to `data/parquet/twin_ACTIVSg2000.p` so the cascade spec never re-parses `.m`.
  `twin/` maps pandapower bus index ↔ `buses.bus_id` through `net.bus['name']` (= MATPOWER bus number).
- Footnote: the PowerWorld `Texas2000_June2016.AUX` also carries coordinates in its
  `DATA (Bus, [...,Latitude,Longitude,...])` (~line 230) and `DATA (Substation, [SubNum,SubName,SubID,Latitude,Longitude,...])`
  (~line 7677) blocks; a parser (`pipelines/activsg_aux.py`) is not needed while the xlsx exists.

**S2. ACTIVSg10k / 25k / 70k** — P1 (national slide); **ACTIVSg82k** — P2
- 10k/25k/70k are also in the `matpower` package data dir; same loader with `case=`.
- 82k: TAMU form only (`…/activsg82k/`), PowerWorld/MATPOWER/RAW/EPC formats.
  `[GATED: TAMU form]`. Only load if the 70k national slide is not enough.

**S3. EIA-860 plants + generators (via PUDL parquet)** — P0
- `https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/core_eia860__scd_plants.parquet` (3.3 MB, HTTP 200)
- `https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/core_eia860__scd_generators.parquet` (9.3 MB, HTTP 200)
- Also `out_eia__yearly_plants.parquet` / `out_eia__yearly_generators.parquet` (denormalised, has lat/lon, fuel, capacity, retirement dates). Prefer these two if present. No credentials (`--no-sign-request`). License CC-BY-4.0 (PUDL). Pin a versioned path (`v2026.2.0/`) if nightly breaks: pattern `…/pudl.catalyst.coop/v{YYYY.MM.0}/{table}.parquet`.
- Raw fallback: `https://www.eia.gov/electricity/data/eia860/xls/eia8602024.zip` (HTTP 200 per coordinator).
- Loader: `pipelines/eia860.py::load_eia860_plants()` → `eia_plants` (helper table, not in the shared contract; columns `plant_id_eia, plant_name, lon, lat, state, county_fips, capacity_mw, primary_fuel, retirement_year, operational_status`), then `pipelines/eia860.py::attach_gens_to_eia(radius_km=25)` fills `gens.eia_plant_id` by nearest plant of matching `fuel` class; also seeds `site_candidates(kind in ('retired_coal','retiring_coal','existing_nuclear'))` for TX.

**S4. EIA-930 hourly BA demand** — P0
- Pattern `https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_{YYYY}_{Jan_Jun|Jul_Dec}.csv`. Verified `EIA930_BALANCE_2021_Jan_Jun.csv` HTTP 200, 43 MB; header verified: `"Balancing Authority","Data Date","Hour Number","Local Time at End of Hour","UTC Time at End of Hour","Demand Forecast (MW)","Demand (MW)",…,"Demand (MW) (Adjusted)",…`. Open, no login.
- P0 files: `2021_Jan_Jun` (Uri), `2024_Jul_Dec` (Beryl Jul 8, Helene Sep 26). P1: all halves 2018–2025 (~16 files × ~45 MB).
- BA reference table (BA code → region/time zone): `https://www.eia.gov/electricity/930-content/EIA930_Reference_Tables.xlsx` (44 KB, verified 200).
- Loader: `pipelines/eia930.py::load_eia930(halves: list[str])` → `ba_load_hourly(ba_code, ts, demand_mw)` using `Demand (MW) (Adjusted)` falling back to `Demand (MW)`, `ts` = UTC end-of-hour.

**S5. EAGLE-I county outages 2014–2025** — P0 (2021, 2024), P1 (rest)
- **Open on figshare, CC BY 4.0, no Globus.** Article `https://api.figshare.com/v2/articles/24237376` (version 4, "…Recorded Electricity Outages 2014-2025"). Direct file URLs (verified via API; GET follows a 302 to a 10-second presigned S3 URL, so use `curl -L -o`, not HEAD):
  - `eaglei_outages_2021.csv` 1,141 MB `https://ndownloader.figshare.com/files/42547891`
  - `eaglei_outages_2024.csv` 1,445 MB `https://ndownloader.figshare.com/files/53581661`
  - `eaglei_outages_2025.csv` 1,402 MB `https://ndownloader.figshare.com/files/62164877`
  - `eaglei_outages_2023.csv` 1,200 MB `…/files/44574907`; `2022` `…/42547897`; `2020` `…/42547894`; `2019` `…/42547885`; `2018` `…/42547879`; `2017` `…/42547828`; `2016` `…/42547825`; `2015` `…/42547822`; `2014` 78 MB `…/42547717`
  - `MCC.csv` (modeled customer count per county, 2022) 40 KB `https://ndownloader.figshare.com/files/42547708`
  - `coverage_history.csv` 12 KB `…/42547714`; `DQI.csv` `…/42547705`
- Columns: `fips_code, county, state, customers_out, run_start_time` (2024+ adds `total_customers`). 15-minute cadence.
- Loader: `pipelines/eaglei.py::load_eaglei(years, states=("Texas",))` streams each CSV through DuckDB `read_csv` with a state filter and writes `eaglei_outages(county_fips, ts, customers_out)` plus helper `county_customers(county_fips, total_customers)` from `MCC.csv` (overridden by 2024 `total_customers` where present). For P0 the Texas filter cuts 2021 to ~35 MB in DuckDB.
- Alternate: ORNL OpenEnergyHub `https://openenergyhub.ornl.gov/explore/dataset/eaglei_outages_2014/` (no login, Opendatasoft export) `[UNVERIFIED: export size limit]`. OSTI records (e.g. 2025: `https://www.osti.gov/biblio/3012826`) point to Globus — not needed.

**S6. NOAA Storm Events** — P0
- Directory `https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/` (open). Files: `StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz` (10.6 MB, HTTP 200), `StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz`. The `c########` suffix changes when NCEI republishes — `download.sh` resolves it by listing the directory and grepping `d{YEAR}_`.
- Loader: `pipelines/storm_events.py::load_storm_events(years)` → `storm_events(event_id, ts_begin, ts_end, county_fips, type, magnitude)`. County FIPS = `STATE_FIPS*1000 + CZ_FIPS` only when `CZ_TYPE='C'`; zone-typed rows (`CZ_TYPE='Z'`, common for winter storms) are mapped to counties via the NWS zone→county correlation file `https://www.weather.gov/source/gis/Shapefiles/WSOM/bp05mr24.dbx` `[UNVERIFIED: current filename; pattern bpDDmmYY.dbx]` — if that fails, fall back to assigning the zone row to every county whose centroid is within the zone polygon from `https://www.weather.gov/source/gis/Shapefiles/WSOM/z_05mr24.zip` `[UNVERIFIED filename]`.

**S7. HRRR (weather per county-hour)** — P0 for the four scenario windows; fallback S7b
- AWS Open Data bucket `noaa-hrrr-bdp-pds`, no credentials. Verified keys exist for Uri:
  `hrrr.20210213/conus/hrrr.t12z.wrfsfcf00.grib2`, `hrrr.20210215/conus/hrrr.t00z.wrfsfcf00.grib2` (145 MB each; `f01` 154 MB). Use **analysis files `f00`** every hour (24 files/day × ~145 MB = 3.5 GB/day) but fetch only the needed GRIB messages via `herbie` byte-range subsetting (the `.idx` files exist) — 4 fields ≈ 2–3 MB/hour.
- Fields: `UGRD/VGRD:10 m` (→ `wind_ms`), `GUST:surface` (→ `gust_ms`), `TMP:2 m` (→ `temp_c`), `APCP:surface` 1-h from `f01` (→ `precip_mm`), `FRZR:surface` (freezing rain accumulation; `ice_mm` = hourly diff, 0 if absent) `[UNVERIFIED: FRZR present in 2021 sfc files; else derive ice_mm = precip_mm where temp_c ≤ 0]`.
- Aggregation: county mean via `xarray` + precomputed HRRR-grid→county index (`pipelines/hrrr.py::build_county_index()` rasterises TIGER counties on the HRRR Lambert grid once, cached in `data/parquet/hrrr_county_index.parquet`).
- Windows (P0): `uri_2021` 2021-02-11T00Z..2021-02-21T00Z (10 d); `beryl_2024` 2024-07-07..2024-07-11; `helene_2024` 2024-09-25..2024-09-30 (Helene is FL/GA/NC — used for the held-out non-Texas test, Texas-only P0 may skip it); `forecast_72h` = latest HRRR `f00..f48` + NWS alerts (HRRR only forecasts 48 h; hours 49–72 reuse the 48 h field, flagged).
- Loader: `pipelines/hrrr.py::load_hrrr_window(scenario_id, states)` → `weather_hourly(county_fips, ts, wind_ms, gust_ms, temp_c, ice_mm, precip_mm)`.
- **S7b fallback (P2, cheap):** NOAA ISD hourlies via `https://www.ncei.noaa.gov/data/global-hourly/access/{YEAR}/{USAF}{WBAN}.csv` (open; ~200 TX stations). `pipelines/isd.py::load_isd_window(scenario_id)` interpolates station values to county centroids (IDW, k=3). Same target table, `source='isd'` recorded in `scenarios`.

**S8. NWS alerts API** — P0 (`forecast_72h` live layer)
- `https://api.weather.gov/alerts/active?area=TX` (verified 200, GeoJSON). Requires a `User-Agent` header (`"(flux-grid-twin, <team email>)"`), undocumented rate limit (retry after 5 s).
- Loader: `pipelines/nws.py::snapshot_alerts(area="TX")` → helper table `nws_alerts(alert_id, event, severity, onset, ends, geom_wkb, county_fips_list)`; `pipelines/nws.py::alerts_to_features(ts)` maps `event` to the outage model's hazard flags (Winter Storm Warning → ice, High Wind Warning → wind, Red Flag → wildfire, Excessive Heat → heat).

**S9. FEMA National Risk Index (county)** — P0
- `https://www.fema.gov/about/reports-and-data/openfema/nri/v120/NRI_Table_Counties.zip` — **verified HTTP 200, 25.0 MB** via curl (v1.20, Dec 2025). (The `hazards.fema.gov/nri/data-resources` page 301s to fema.gov; use the OpenFEMA URL above, not the hazards host.) Shapefile companion: `…/nri/v120/NRI_Shapefile_Counties.zip`. Public domain.
- Columns used: `STCOFIPS, POPULATION, RISK_SCORE, WFIR_RISKS (wildfire), ISTM_RISKS (ice storm), SWND_RISKS (strong wind), HRCN_RISKS, WNTW_RISKS, EAL_VALT`.
- Loader: `pipelines/nri.py::load_nri()` → `hazard_static.nri_score` (= `RISK_SCORE`) and `counties.pop` (= `POPULATION`); the per-hazard columns go to helper `nri_hazards(county_fips, hazard, risk_score, eal)`.

**S10. USFS Wildfire Hazard Potential 2023** — P1
- `https://www.fs.usda.gov/rds/archive/products/RDS-2015-0047-4/RDS-2015-0047-4_Data.zip` (verified 200, 368 MB; 270 m GeoTIFF, CONUS continuous + 5-class). Free, attribution required.
- Loader: `pipelines/wildfire.py::load_whp()` → `hazard_static.wildfire_hazard` = county mean of the continuous index (rasterstats zonal mean). P0 shortcut: use `nri_hazards.WFIR_RISKS` and leave `wildfire_hazard` NULL until this runs.

**S11. USGS NSHM 2023 seismic** — P1
- ScienceBase item 04 "Uniform-hazard ground motion maps": `US_PGA_2Pct_5Pct_10Pct_50Yrs_BC.zip` 59 MB, `https://www.sciencebase.gov/catalog/file/get/64ff886dd34ed30c2057b4d9?f=__disk__76%2Ff4%2Fb4%2F76f4b416aadf6f70680106a36acc31714473b4ff` (verified via the ScienceBase JSON API; open). Contents are gridded 0.2°/0.05° PGA points (CSV/GeoTIFF) `[UNVERIFIED: inner file format]`.
- Loader: `pipelines/seismic.py::load_nshm()` → `hazard_static.seismic_pga` (county mean of PGA 2%-in-50 yr, site class BC, in g). Also used per-site by `siting/`.

**S12. Transmission-line / substation geometry (real overlay)** — P1
- HIFLD archived lines: DataLumos/ICPSR project 240591 `https://www.datalumos.org/datalumos/project/240591/version/V1/view` (DOI 10.3886/E240591V1, shapefile, 76.8 MB) `[GATED: Cloudflare challenge + free ICPSR account; download in a browser, drop into data/raw/hifld/]`. Substations: not located on DataLumos by search; consult the HIFLD OPEN GIS index/crosswalk project 241367 `[UNVERIFIED]`. Data Rescue Project portal `https://portal.datarescueproject.org/datasets/hifld-open-transmission-lines/` links back to DataLumos. HIFLD Hub page `https://hifld-geoplatform.hub.arcgis.com/datasets/geoplatform::transmission-lines` returns 200 but the portal was decommissioned 2025-08-26 — treat as `[UNVERIFIED: may be a stub]`. source.coop `seerai/hifld` geoparquet mirror `[GATED: source.coop login]`.
- **OSM fallback (P1, scriptable):** Geofabrik `https://download.geofabrik.de/north-america/us/texas-latest.osm.pbf` (302 → mirror, 684 MB). Extract `power=line|minor_line|cable` and `power=substation` with `osmium tags-filter` → `pipelines/osm_power.py::load_osm_power(pbf)` → helper tables `real_lines(osm_id, voltage_kv, geom_wkb)`, `real_substations(osm_id, name, voltage_kv, lon, lat)`. These are a **map overlay only**; they are never joined into `lines`/`buses` (synthetic topology stays synthetic; say so in the demo).

**S13. Census TIGER counties** — P0
- `https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip` (verified 200, 83.9 MB). Public domain.
- Loader: `pipelines/counties.py::load_counties()` → `counties(county_fips, name, state, pop, geom_wkb)` (`pop` filled from NRI; `state` = USPS from `STATEFP`).

**S14. DoD installation boundaries** — P0
- NTAD "Military Bases" (BTS/USDOT, FY2024, CC0, updated 2025-11-11). ArcGIS FeatureServer **verified**: `https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Military_Bases/FeatureServer/0/query?where=stateNameCode%3D%27TX%27&outFields=*&returnGeometry=true&outSR=4326&f=geojson` (polygon, WGS84, fields `siteName, siteReportingComponent, siteOperationalStatus, stateNameCode, isJointBase`; max 2,000 records/page — CONUS needs `resultOffset` paging). data.gov landing: `https://catalog.data.gov/dataset/military-bases-24048` (DOI 10.21949/1522149). DataLumos MIRTA archive project 239599 is the gated backup.
- Loader: `pipelines/dod.py::load_dod(states)` → `critical_loads(kind='dod')` using the polygon centroid as `lon/lat`, `bus_id` = nearest bus with `base_kv ≥ 115` (see join J3), `name = siteName`. Keep only `siteOperationalStatus='Active'` and area > 1 km² for the panel (Fort Cavazos/Hood, Fort Bliss, JBSA, Dyess, Sheppard, Goodfellow, Laughlin, NAS Corpus Christi, Red River, Camp Mabry…).

**S15. Hospitals** — P1
- HIFLD OPEN Hospitals archive: DataLumos project 239108 (DOI 10.3886/E239108V1) `[GATED: Cloudflare + ICPSR login]`; Data Rescue Project page `https://portal.datarescueproject.org/datasets/hifld-open-hospitals/`. Fallback: OSM `amenity=hospital` from the same Texas PBF (S12). Loader: `pipelines/hospitals.py::load_hospitals(source="osm"|"hifld")` → `critical_loads(kind='hospital')`, filtered to ≥100 beds when `beds` is present, else all.

**S16. EIA-861 reliability (SAIDI/SAIFI) + service territories** — P1
- `https://www.eia.gov/electricity/data/eia861/archive/zip/f861{YYYY}.zip` (2021 verified 200, 4.4 MB; 2024 at `…/zip/f8612024.zip`). Inside: `Reliability_{YYYY}.xlsx`, `Service_Territory_{YYYY}.xlsx` (utility → county list), `Sales_Ult_Cust_{YYYY}.xlsx` `[UNVERIFIED: exact inner sheet names]`.
- Loader: `pipelines/eia861.py::load_eia861(years)` → helper `utility_reliability(utility_id, year, saidi_w_med, saifi_w_med, saidi_wo_med)` and `utility_county(utility_id, county_fips, year)`; county-level `saidi_trend` = customer-weighted slope over 2018–2023, consumed by the causal spec as the confounder.

**S17. Balancing-authority ↔ county mapping** — P0 (Texas), P1 (national)
- Texas P0: hand-curated in `pipelines/ba_map.py::TX_NON_ERCOT_COUNTIES` — every Texas county is `ERCO` except: El Paso, Hudspeth, Culberson (→ `EPE`); the Panhandle counties served by SPS (→ `SWPP`; ~33 counties: Dallam, Sherman, Hansford, Ochiltree, Lipscomb, Hartley, Moore, Hutchinson, Roberts, Hemphill, Oldham, Potter, Carson, Gray, Wheeler, Deaf Smith, Randall, Armstrong, Donley, Collingsworth, Parmer, Castro, Swisher, Briscoe, Hall, Childress, Bailey, Lamb, Hale, Floyd, Motley, Cottle, Hardeman, Cochran, Hockley, Lubbock, Crosby, Dickens, King, Yoakum, Terry, Lynn, Garza, Kent, Stonewall, Gaines, Dawson, Borden, Scurry, Fisher, Andrews, Martin, Howard, Mitchell — `[UNVERIFIED: exact SPS/ERCOT boundary; several of these are split counties, assign by majority]`); East Texas counties served by SWEPCO/Entergy Texas (→ `MISO`; Bowie, Cass, Marion, Harrison, Panola, Shelby, San Augustine, Sabine, Newton, Jasper, Tyler, Hardin, Jefferson, Orange, Liberty, Polk, San Jacinto, Montgomery(part), Walker(part), Trinity, Houston, Angelina, Nacogdoches `[UNVERIFIED: split counties]`).
- National P1: HIFLD OPEN Control Areas (DataLumos 239072) or Electric Retail Service Territories (239091) `[GATED: DataLumos]`; else EIA-861 `Service_Territory` → utility → BA via `EIA930_Reference_Tables.xlsx` and PUDL `core_eia861__yearly_balancing_authority` `[UNVERIFIED: table name]`.
- Function: `pipelines/ba_map.py::assign_ba(counties) -> DataFrame[county_fips, ba_code]`; `buses.ba_code` is inherited from the bus's county.

## Outputs

DuckDB `data/duck/grid.duckdb` with exactly the shared-contract tables (types below) plus the helper tables named above (prefixed as listed; helpers may change freely, contract tables may not).

```sql
CREATE TABLE buses(bus_id INTEGER PRIMARY KEY, name TEXT, base_kv DOUBLE, lon DOUBLE, lat DOUBLE,
                   county_fips TEXT, ba_code TEXT, coord_source TEXT, zone INTEGER, area INTEGER);
CREATE TABLE lines(line_id INTEGER PRIMARY KEY, from_bus INTEGER, to_bus INTEGER, base_kv DOUBLE,
                   r_pu DOUBLE, x_pu DOUBLE, rate_a_mw DOUBLE, length_km DOUBLE, geom_wkb BLOB,
                   is_transformer BOOLEAN);
CREATE TABLE gens(gen_id INTEGER PRIMARY KEY, bus_id INTEGER, fuel TEXT, pmax_mw DOUBLE, eia_plant_id INTEGER);
CREATE TABLE loads(load_id INTEGER PRIMARY KEY, bus_id INTEGER, p_mw_nominal DOUBLE);
CREATE TABLE counties(county_fips TEXT PRIMARY KEY, name TEXT, state TEXT, pop INTEGER, geom_wkb BLOB);
CREATE TABLE critical_loads(cl_id INTEGER PRIMARY KEY, kind TEXT CHECK(kind IN ('dod','hospital','water')),
                   name TEXT, lon DOUBLE, lat DOUBLE, bus_id INTEGER, county_fips TEXT);
CREATE TABLE eaglei_outages(county_fips TEXT, ts TIMESTAMP, customers_out INTEGER);
CREATE TABLE weather_hourly(county_fips TEXT, ts TIMESTAMP, wind_ms DOUBLE, gust_ms DOUBLE,
                   temp_c DOUBLE, ice_mm DOUBLE, precip_mm DOUBLE);
CREATE TABLE storm_events(event_id BIGINT, ts_begin TIMESTAMP, ts_end TIMESTAMP, county_fips TEXT,
                   type TEXT, magnitude DOUBLE);
CREATE TABLE hazard_static(county_fips TEXT PRIMARY KEY, nri_score DOUBLE, wildfire_hazard DOUBLE, seismic_pga DOUBLE);
CREATE TABLE ba_load_hourly(ba_code TEXT, ts TIMESTAMP, demand_mw DOUBLE);
CREATE TABLE site_candidates(site_id INTEGER PRIMARY KEY, name TEXT, kind TEXT, lon DOUBLE, lat DOUBLE,
                   county_fips TEXT, bus_id INTEGER, capacity_slot_mw DOUBLE);
CREATE TABLE scenarios(scenario_id TEXT PRIMARY KEY, name TEXT, kind TEXT CHECK(kind IN ('historical','forecast','synthetic')),
                   ts_start TIMESTAMP, ts_end TIMESTAMP);
-- outage_predictions, cascade_runs, site_scores, line_upgrade_scores are created empty here
-- (DDL owned by specs 02/03/04/05) so downstream code can always SELECT.
```

Parquet mirrors in `data/parquet/<table>.parquet` are written after every build (`pipelines/build.py::export_parquet()`) so `web/` and notebooks can read without a DuckDB lock.

Seeded rows in `scenarios`:

| scenario_id | name | kind | ts_start | ts_end |
|---|---|---|---|---|
| `uri_2021` | Winter Storm Uri | historical | 2021-02-13 00:00 | 2021-02-20 00:00 |
| `beryl_2024` | Hurricane Beryl | historical | 2024-07-07 00:00 | 2024-07-11 00:00 |
| `helene_2024` | Hurricane Helene | historical | 2024-09-25 00:00 | 2024-09-30 00:00 |
| `forecast_72h` | Next 72 h | forecast | now (UTC, floored to hour) | now + 72 h |

## Algorithm or Design

Build order (`uv run python -m pipelines.build --tier p0|p1|p2`):

1. `counties` (S13) → `hazard_static` + `counties.pop` (S9, S10, S11).
2. `buses/lines/gens/loads` (S1). Line `length_km` = haversine between endpoint buses × 1.15 (routing factor) when the case gives none; `geom_wkb` = straight `LINESTRING(from, to)`. Transformers (branches whose endpoint `base_kv` differ or `TAP≠0`) are kept in `lines` with `is_transformer=TRUE` and `length_km=0`.
3. **J1 bus→county:** `ST_Within(ST_Point(lon,lat), county.geom)` via DuckDB spatial; buses that fall outside any county (coastal jitter) take the nearest county centroid within 30 km, else NULL and a warning row in helper `ingest_warnings`.
4. **J2 county→BA:** `assign_ba` (S17); `buses.ba_code` inherits.
5. **J3 critical load→bus:** nearest bus by haversine among `base_kv ≥ 115`, ties → higher kV; store distance in helper `critical_load_bus_dist`.
6. `eia_plants` (S3) → `gens.eia_plant_id` (nearest same-fuel-class plant ≤25 km, fuel classes: coal, gas, nuclear, hydro, wind, solar, other) → `site_candidates` (TX coal plants with `retirement_year IS NOT NULL OR primary_fuel='coal'`, existing nuclear = Comanche Peak, South Texas Project; federal sites are out of Texas so P1). `capacity_slot_mw` = 300 for SMR-class candidates, 1000 for large; `bus_id` = nearest bus ≥ 230 kV.
7. `ba_load_hourly` (S4) for scenario halves.
8. `eaglei_outages` (S5), Texas filter.
9. `storm_events` (S6).
10. `weather_hourly` (S7) per scenario window.
11. `critical_loads` dod (S14), hospitals (S15).
12. `scenarios` seed; `export_parquet()`.

Load scaling handoff to `twin/`: `loads.p_mw_nominal` sums to the ACTIVSg2000 base case (~67 GW); the twin scales every load by `ba_load_hourly.demand_mw(ERCO, ts) / SUM(p_mw_nominal WHERE ba_code='ERCO')` — this is the only place EIA-930 touches physics.

Every loader is idempotent: `DELETE FROM <table> WHERE <source-key>` then insert; `pipelines/build.py` records `(source, file, sha256, rows, loaded_at)` in helper `ingest_log`.

## Interfaces (exact function signatures)

```python
# pipelines/db.py
def connect(path: str = "data/duck/grid.duckdb", read_only: bool = False) -> duckdb.DuckDBPyConnection: ...
def ensure_schema(con: duckdb.DuckDBPyConnection) -> None: ...   # creates all contract tables if missing

# pipelines/activsg.py
def load_activsg(con, xlsx_path: str = "data/raw/activsg2000/Texas 2000 - June 2016 Synthetic Case/Texas2000_June2016.xlsx",
                 case: str = "ACTIVSg2000", manual_coords: str | None = None) -> dict[str, int]: ...  # rows per table
def to_pandapower(case: str = "ACTIVSg2000") -> "pandapower.auxiliary.pandapowerNet": ...   # from_mpc on the pip matpower .m
def geocode_bus_names(names: list[str], gazetteer_zip: str) -> pd.DataFrame: ...  # fallback only: name, lon, lat, score

# pipelines/counties.py
def load_counties(con, tiger_zip: str = "data/raw/tiger/tl_2024_us_county.zip", states: tuple[str, ...] | None = None) -> int: ...

# pipelines/nri.py
def load_nri(con, zip_path: str = "data/raw/nri/NRI_Table_Counties.zip") -> int: ...

# pipelines/eia860.py
def load_eia860_plants(con, plants_parquet: str, generators_parquet: str) -> int: ...
def attach_gens_to_eia(con, radius_km: float = 25.0) -> int: ...
def seed_site_candidates(con, states: tuple[str, ...] = ("TX",)) -> int: ...

# pipelines/eia930.py
def load_eia930(con, csv_paths: list[str], ba_codes: tuple[str, ...] | None = ("ERCO","EPE","SWPP","MISO")) -> int: ...

# pipelines/eaglei.py
def load_eaglei(con, years: list[int], states: tuple[str, ...] = ("Texas",), raw_dir: str = "data/raw/eaglei") -> int: ...
def load_county_customers(con, mcc_csv: str = "data/raw/eaglei/MCC.csv") -> int: ...

# pipelines/storm_events.py
def load_storm_events(con, years: list[int], raw_dir: str = "data/raw/storm_events") -> int: ...

# pipelines/hrrr.py
def build_county_index(con, cache: str = "data/parquet/hrrr_county_index.parquet") -> pd.DataFrame: ...
def load_hrrr_window(con, scenario_id: str, states: tuple[str, ...] = ("TX",), fxx: int = 0) -> int: ...
def load_hrrr_forecast(con, run: datetime | None = None, horizon_h: int = 48) -> int: ...  # forecast_72h

# pipelines/isd.py
def load_isd_window(con, scenario_id: str, states: tuple[str, ...] = ("TX",)) -> int: ...

# pipelines/nws.py
def snapshot_alerts(con, area: str = "TX", user_agent: str = ...) -> int: ...
def alerts_to_features(con, ts: datetime) -> pd.DataFrame: ...  # county_fips, ice_flag, wind_flag, fire_flag, heat_flag

# pipelines/dod.py
def load_dod(con, states: tuple[str, ...] = ("TX",)) -> int: ...
# pipelines/hospitals.py
def load_hospitals(con, source: Literal["osm","hifld"] = "osm", pbf: str | None = None) -> int: ...
# pipelines/osm_power.py
def load_osm_power(con, pbf: str = "data/raw/osm/texas-latest.osm.pbf") -> dict[str, int]: ...
# pipelines/wildfire.py / seismic.py / eia861.py
def load_whp(con, data_zip: str) -> int: ...
def load_nshm(con, pga_zip: str) -> int: ...
def load_eia861(con, years: list[int]) -> int: ...
# pipelines/ba_map.py
def assign_ba(counties: pd.DataFrame) -> pd.DataFrame: ...   # county_fips, ba_code
# pipelines/joins.py
def join_bus_county(con) -> int: ...
def join_critical_loads_to_bus(con, min_kv: float = 115.0) -> int: ...
# pipelines/build.py
def build(tier: Literal["p0","p1","p2"] = "p0", states: tuple[str, ...] = ("TX",)) -> None: ...
def export_parquet(con, out_dir: str = "data/parquet") -> list[str]: ...
```

### `scripts/data/download.sh`

`set -euo pipefail`; `RAW=data/raw`; each block is `mkdir -p` + skip-if-exists; accepts `TIER=p0|p1|p2` (default p0).

1. `curl -L -o $RAW/tiger/tl_2024_us_county.zip https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip`
2. `curl -L -o $RAW/nri/NRI_Table_Counties.zip https://www.fema.gov/about/reports-and-data/openfema/nri/v120/NRI_Table_Counties.zip`
3. `curl -L -o $RAW/activsg2000/Texas2000_June2016.zip 'https://drive.google.com/uc?export=download&id=1tOIK_RVQaZZDo_oIi75bVdPsAlQ7J1l9' && unzip -n -d $RAW/activsg2000 $RAW/activsg2000/Texas2000_June2016.zip`
3b. `curl -L -o $RAW/gazetteer/2024_Gaz_place_national.zip https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip` (fallback geocoder only)
4. `curl -L -o $RAW/pudl/core_eia860__scd_plants.parquet https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/core_eia860__scd_plants.parquet`
5. `curl -L -o $RAW/pudl/core_eia860__scd_generators.parquet https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/core_eia860__scd_generators.parquet`
6. `curl -L -o $RAW/pudl/out_eia__yearly_plants.parquet https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/out_eia__yearly_plants.parquet` (`|| true`, optional)
7. `curl -L -o $RAW/eia930/EIA930_BALANCE_2021_Jan_Jun.csv https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2021_Jan_Jun.csv`
8. `curl -L -o $RAW/eia930/EIA930_BALANCE_2024_Jul_Dec.csv https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2024_Jul_Dec.csv`
9. `curl -L -o $RAW/eia930/EIA930_Reference_Tables.xlsx https://www.eia.gov/electricity/930-content/EIA930_Reference_Tables.xlsx`
10. `curl -L -o $RAW/eaglei/eaglei_outages_2021.csv https://ndownloader.figshare.com/files/42547891` (1.1 GB; `-C -` resume)
11. `curl -L -o $RAW/eaglei/eaglei_outages_2024.csv https://ndownloader.figshare.com/files/53581661` (1.4 GB)
12. `curl -L -o $RAW/eaglei/MCC.csv https://ndownloader.figshare.com/files/42547708`
13. `curl -L -o $RAW/eaglei/coverage_history.csv https://ndownloader.figshare.com/files/42547714`
14. `for Y in 2021 2024; do F=$(curl -s https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/ | grep -o "StormEvents_details-ftp_v1.0_d${Y}_c[0-9]*.csv.gz" | head -1); curl -L -o $RAW/storm_events/$F https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/$F; done`
15. `curl -s -H 'User-Agent: (flux-grid-twin, team@example.com)' -o $RAW/nws/alerts_TX_$(date -u +%Y%m%dT%H).geojson 'https://api.weather.gov/alerts/active?area=TX'`
16. `curl -L -o $RAW/dod/military_bases_TX.geojson 'https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Military_Bases/FeatureServer/0/query?where=stateNameCode%3D%27TX%27&outFields=*&returnGeometry=true&outSR=4326&f=geojson'`
17. HRRR is **not** curl'd here: `uv run python -m pipelines.hrrr --scenario uri_2021 --states TX` uses herbie byte-range subsetting against `s3://noaa-hrrr-bdp-pds` (anonymous). Equivalent manual line for one hour: `aws s3 cp --no-sign-request s3://noaa-hrrr-bdp-pds/hrrr.20210215/conus/hrrr.t00z.wrfsfcf00.grib2 $RAW/hrrr/`.
18. `[TIER≥p1]` `for Y in 2018 2019 2020 2022 2023 2025; do …figshare ids: 42547879 42547885 42547894 42547897 44574907 62164877; done`
19. `[TIER≥p1]` `for Y in 2021 2022 2023 2024; do curl -L -o $RAW/eia861/f861$Y.zip https://www.eia.gov/electricity/data/eia861/archive/zip/f861$Y.zip; done`
20. `[TIER≥p1]` `curl -L -o $RAW/whp/RDS-2015-0047-4_Data.zip https://www.fs.usda.gov/rds/archive/products/RDS-2015-0047-4/RDS-2015-0047-4_Data.zip` (368 MB)
21. `[TIER≥p1]` `curl -L -o $RAW/nshm/US_PGA_2Pct_5Pct_10Pct_50Yrs_BC.zip 'https://www.sciencebase.gov/catalog/file/get/64ff886dd34ed30c2057b4d9?f=__disk__76%2Ff4%2Fb4%2F76f4b416aadf6f70680106a36acc31714473b4ff'`
22. `[TIER≥p1]` `curl -L -o $RAW/osm/texas-latest.osm.pbf https://download.geofabrik.de/north-america/us/texas-latest.osm.pbf` (684 MB) then `osmium tags-filter $RAW/osm/texas-latest.osm.pbf nwr/power=line,minor_line,cable,substation nwr/amenity=hospital nwr/man_made=water_works -o $RAW/osm/texas-power.osm.pbf`
23. `[TIER≥p1]` EIA-930 all halves 2018–2025 loop over `{Jan_Jun,Jul_Dec}`.
24. `[TIER≥p1, GATED]` echo instructions: download HIFLD lines (DataLumos 240591) and HIFLD hospitals (239108) in a browser into `$RAW/hifld/`; script checks for their presence and prints what is missing.
25. `[TIER≥p2]` ISD station files for TX (`https://www.ncei.noaa.gov/data/global-hourly/access/2021/{USAF}{WBAN}.csv` from `isd-history.csv` filtered to TX).

## Acceptance criteria

1. `uv run python -m pipelines.build --tier p0` completes on a laptop in < 25 min after downloads, producing `data/duck/grid.duckdb` with every contract table present (`ensure_schema` idempotent; second run changes no row counts).
2. `buses` has 2,000 rows; `lines` 3,206 (2,359 with `is_transformer=FALSE` + 847 transformers); `gens` 544; `loads` 1,125 summing to 67,109 MW ± 1%; every `buses.lon/lat` is within the Texas bbox (−106.7..−93.5, 25.8..36.6); 20 randomly sampled bus numbers agree on `base_kv` between the xlsx and the pandapower net.
3. 100% of buses have non-NULL `lon/lat` with `coord_source='tamu_xlsx'` and ≥ 99% have non-NULL `county_fips`; any remainder is listed in `ingest_warnings`.
4. `counties` has 254 Texas rows (P0) with non-NULL `pop`, and `hazard_static.nri_score` non-NULL for all 254.
5. `eaglei_outages` for TX 2021-02-13..20 has ≥ 200 counties and the statewide 15-min max of `SUM(customers_out)` falls within 4.0–4.8 M (EAGLE-I's Uri peak) — a sanity anchor, printed by the build.
6. `ba_load_hourly` for `ERCO` covers every hour 2021-01-01..2021-06-30 with ≤ 0.5% NULL demand; 2021-02-15 07:00 UTC demand is < 50 GW (the load-shed hour), confirming the adjusted column was used correctly.
7. `weather_hourly` for `uri_2021` has 254 counties × 240 hours ± 2%, `temp_c` min < −15 somewhere in the Panhandle on 2021-02-16.
8. `storm_events` has ≥ 150 Texas rows with `type IN ('Winter Storm','Winter Weather','Ice Storm','Extreme Cold/Wind Chill')` in Feb 2021 after zone→county expansion.
9. `critical_loads` contains ≥ 12 `dod` rows for TX including a row whose `name ILIKE '%Cavazos%' OR name ILIKE '%Hood%'` with a non-NULL `bus_id`.
10. `site_candidates` has ≥ 15 Texas coal rows and 2 nuclear rows, each with `bus_id` at ≥ 230 kV.
11. `to_pandapower("ACTIVSg2000")` returns a net where `pp.rundcpp` converges and total load equals `SUM(loads.p_mw_nominal)` ± 0.1%.
12. `scenarios` has the four seeded IDs with the timestamps above; `forecast_72h` is refreshed by `load_hrrr_forecast` + `snapshot_alerts` and its `ts_start` is ≤ 2 h old.
13. `export_parquet` writes one parquet per contract table; `web/` can read `data/parquet/buses.parquet` without DuckDB.
14. `download.sh` is re-runnable: it skips existing files, never deletes, and exits non-zero naming each missing gated file.

## Demo hook

Slide/interaction 1 of the demo: "This is the grid as public data lets us see it." The map shows `lines` (synthetic, colored by kV) over `real_lines` (OSM/HIFLD, grey) and `counties` shaded by `hazard_static.nri_score`, with `critical_loads(kind='dod')` pins. The copilot's `sql(...)` tool reads this DuckDB read-only; the build log (`ingest_log`) is what the copilot cites when asked "where does this data come from".

## Risks / unknowns

- **Bus coordinates** are solved (xlsx Substations sheet); the residual risk is a bus-number mismatch between the June-2016 xlsx and the pip `.m` case. Mitigation: AC #2 spot-check; if it fails, the gazetteer fallback and the manual CSV `data/raw/activsg2000/bus_coords_manual.csv` (`bus_id,lon,lat`) still work, and the AUX file is a third source.
- **EAGLE-I file size** (1.1–1.4 GB per year) on hackathon Wi-Fi; DuckDB reads the CSV once with a `state='Texas'` pushdown — do not load into pandas. Keep the raw CSV, do not re-download.
- **HRRR `FRZR`** field availability in Feb 2021 sfc files `[UNVERIFIED]`; the derived-ice fallback is defined above.
- **NCEI Storm Events file suffix** rotates; the directory-grep in `download.sh` handles it.
- **HIFLD archives are behind Cloudflare/ICPSR**; OSM is the scriptable overlay and is good enough for a map. Nothing in P0 depends on HIFLD.
- **BA/county boundary** for the non-ERCOT Texas counties is hand-curated `[UNVERIFIED]`; the twin only uses `ERCO` scaling so errors affect labeling, not physics.
- EIA-930 `Demand (MW) (Adjusted)` during Uri contains imputed values for some hours; we keep the adjusted column and flag rows where `Demand (MW)` is NULL.
- Synthetic topology ≠ real topology — state it in the demo; `real_lines` is an overlay, never joined.

## Weekend time-box (hours)

| Task | Hours |
|---|---|
| `download.sh` P0 + `db.py`/`ensure_schema` | 1.0 |
| ACTIVSg2000 xlsx load + pandapower pickle + bus-number spot-check | 1.5 |
| TIGER + NRI + bus→county + BA map | 1.0 |
| EAGLE-I 2021/2024 TX + MCC | 1.0 |
| Storm Events + zone→county | 1.0 |
| HRRR window via herbie + county index | 2.5 |
| EIA-930 + EIA-860/PUDL + site candidates | 1.5 |
| DoD + NWS + scenarios + export_parquet + AC checks | 1.5 |
| **P0 total** | **11** |
| P1 (EAGLE-I all years, EIA-861, WHP, NSHM, OSM overlay, hospitals, 70k case) | +6 |
| P2 (ISD fallback, 82k) | +3 |
