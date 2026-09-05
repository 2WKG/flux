# 01 — Data ingest (Layers 1 + 2: grid twin skeleton, geography, load, weather, hazard, outages)

Status: build spec, weekend scope. Texas first (ACTIVSg2000 / ERCOT); national is a scale slide.
All access facts below were checked on 2026-09-05 with `curl -I` / WebFetch unless tagged
`[UNVERIFIED]` or `[GATED: …]`; an independent fact-check pass (ledger:
`docs/specs/verification/01-02.md`) re-checked every load-bearing claim against primary
sources on 2026-09-05 and corrected the text in place. Where this spec conflicts with the pitch
doc, this spec wins (notably: EAGLE-I is open on figshare, no Globus; ACTIVSg2000 geography is
a curl-able Google Drive zip from the TAMU page and the electrical case ships inside the
`matpower` pip package — no TAMU form needed). **Fact-check headline:** the June-2016 xlsx is
the *previous* case version and its bus numbers do not match the pip `case_ACTIVSg2000.m`;
coordinates for the pip case come from the current-version `ACTIVSg2000.aux` (S1, corrected).

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
- **Two case versions exist and their bus numbering is different (fact-checked 2026-09-05):**
  - *Current version (2018 build)* = the pip `matpower` `case_ACTIVSg2000.m` (PowerWorld v21, build
    2018-08-30; 2,000 buses, bus ids 1001–8159). The TAMU page's main "Download Dataset" link is a
    Google Drive zip, id `1tC-ofbw1EE46hoZeSfiBAWnSAhG0SmVu` (125.3 MB; needs the large-file
    confirm: `curl -L -o ACTIVSg2000.zip 'https://drive.usercontent.google.com/download?id=1tC-ofbw1EE46hoZeSfiBAWnSAhG0SmVu&export=download&confirm=t'`
    — verified 200, 125,303,682 bytes). It contains `ACTIVSg2000.aux` (6.3 MB), `ACTIVSg2000.{m,RAW,EPC,PWB,pwd,con}`,
    `case_ACTIVSg2000.m` (byte-identical bus/branch/gen blocks to the pip file; only two comment
    lines differ), `contab_/scenarios_ACTIVSg2000.m`, dynamics files and a 236 MB `.tsb`.
    **`ACTIVSg2000.aux` is the source of record for coordinates:** its
    `DATA (Substation, [SubNum,SubName,SubID,Latitude,Longitude,…])` block (line 18; 1,250 substations)
    joined to `DATA (Bus, [BusNum,BusName,BusNomVolt,…,SubNum])` (line 1326; 2,000 buses) on `SubNum`
    gives lat/lon for **all 2,000 pip bus ids** (verified: bus-id sets identical, 0 kV mismatches,
    lon −104.62..−94.37, lat 25.91..35.83). `coord_source='tamu_aux'`.
  - *Previous version (June 2016)* = the page's "previous version … here" link,
    `https://drive.google.com/uc?export=download&id=1tOIK_RVQaZZDo_oIi75bVdPsAlQ7J1l9` (2.1 MB, plain
    curl; unpacks to `Texas 2000 - June 2016 Synthetic Case/Texas2000_June2016.{AUX,EPC,m,pwb,pwd,RAW,xlsx}`).
    `Texas2000_June2016.xlsx` sheets (verified with pandas): `Areas(8)`,
    `Substations(1500: Substation Number, Substation Name, Area Name, Latitude, Longitude, Maximum Nominal kV)`,
    `Buses(2007: Bus Number, Bus Name, Area Name, Substation Number, Nominal kV)`,
    `Lines(2481: From Bus Number, To Bus Number, Circuit Number, "R, pu", "X, pu", "B, pu", MVA Limit)`,
    `Transformers(562: From Bus Number, From Bus Nominal Kv, To Bus Number, To Bus Nominal kV, Circuit Number, "R, pu", "X, pu", "B, pu", MVA Limit)`,
    `Loads(1417: Bus Number, MW, Mvar)` (sum 49,775.5 MW), `Generators(282)`, `Shunts(41)`,
    `Benchmark Power Flow Solution`. **Its bus numbers do NOT match the pip case** (only 98 of
    2,000 pip ids appear in the xlsx, 43 of those with a different kV), so it must not be joined to
    the pip `.m`. It is only a fallback: 1,398 of the 2,000 pip `bus_name` stems (e.g. `ODESSA 2`)
    match an xlsx `Substation Name` case-insensitively, which is a usable name-join if the
    current-version AUX is ever unavailable (`coord_source='tamu_xlsx_namejoin'`).
- **Electrical model (twin):** the pip `matpower` package (already in `pyproject.toml`) bundles
  `.venv/lib/python3.12/site-packages/matpower/data/case_ACTIVSg2000.m` (plus
  `scenarios_ACTIVSg2000.m`, `contab_ACTIVSg2000.m`); the GitHub copy
  `https://raw.githubusercontent.com/MATPOWER/matpower/master/data/case_ACTIVSg2000.m` was verified
  to carry `mpc.bus_name` (line 7459), `mpc.gentype` (6363), `mpc.genfuel` (6911) but no lat/lon.
  It loads in pandapower 3.5.3 via `from pandapower.converter.matpower import from_mpc` (needs
  `matpowercaseframes`, in pyproject): 2,000 buses / 2,359 lines / 847 transformer branches (the
  branches whose endpoint kV differ; `from_mpc` places them in **`net.impedance`, not `net.trafo`**,
  verified) / 544 gens (484 `gen` + 59 `sgen` + 1 `ext_grid`) / 1,125 loads / 67,109.21 MW;
  `pp.rundcpp` converges in 0.45 s (re-verified). `gens.fuel` comes from `mpc.genfuel`
  (joined on `GEN_BUS` + order). **`buses/lines/gens/loads` are built from the pip `.m` (topology,
  ratings, loads) + the 2018 AUX (coordinates); the June-2016 xlsx is not used in P0.**
- CSV mirror (no coordinates, backup only): `https://raw.githubusercontent.com/caseformat/ACTIVSg2000/master/{bus,branch,gen,gencost,case}.csv`
  (header verified `BUS_I,BUS_TYPE,PD,QD,GS,BS,BUS_AREA,VM,VA,BASE_KV,ZONE,VMAX,VMIN,...`).
- Name-geocode fallback (only if both TAMU zips are unavailable): `mpc.bus_name` values are Texas
  place names with numeric suffixes (e.g. `ODESSA 2 0`); strip the suffixes and fuzzy-match
  (rapidfuzz ≥ 90; rapidfuzz 3.14 is installed transitively, not pinned in `pyproject.toml`)
  against the Census 2024 place gazetteer
  `https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip`
  (verified 200, 1.2 MB; tab-delimited `2024_Gaz_place_national.txt` with columns
  `USPS,GEOID,ANSICODE,NAME,LSAD,FUNCSTAT,ALAND,AWATER,ALAND_SQMI,AWATER_SQMI,INTPTLAT,INTPTLONG`;
  1,863 rows with `USPS='TX'`), `coord_source='gazetteer'`.
  A manual override CSV `data/raw/activsg2000/bus_coords_manual.csv` (`bus_id,lon,lat`) wins over all.
- License: TAMU states the datasets are "free for commercial or non-commercial use" (verified on the
  page); cite Birchfield et al. 2017, *IEEE Trans. Power Systems*, doi 10.1109/TPWRS.2016.2616385
  (resolves). No CEII (stated on the TAMU test-case index page).
- Loader: `pipelines/activsg.py::load_activsg(con, aux_path, case="ACTIVSg2000")` → `buses`, `lines`, `gens`, `loads`.
- Twin handoff: `pipelines/activsg.py::to_pandapower(case) -> pandapowerNet` via `from_mpc`; the net
  is pickled to `data/parquet/twin_ACTIVSg2000.p` so the cascade spec never re-parses `.m`.
  `twin/` maps pandapower bus index ↔ `buses.bus_id` through `net.bus['name']` (= MATPOWER bus number).
- AUX parser: `pipelines/activsg_aux.py::read_aux_coords(aux_path) -> DataFrame[bus_id, lon, lat, sub_num, sub_name]`
  **is required** (P0). The PowerWorld AUX format is `DATA (Object, [field,…]) { rows }` with
  quoted strings; the June-2016 AUX has the same blocks (`DATA (Bus,…)` at line 224 — no lat/lon
  fields in the Bus block, `SubNum` is the join key — and `DATA (Substation,[SubNum,SubName,SubID,Latitude,Longitude,…])`
  at line 7677), so one parser serves both versions.

**S2. ACTIVSg10k / 25k / 70k** — P1 (national slide); **ACTIVSg82k** — P2
- 10k/25k/70k are also in the `matpower` package data dir; same loader with `case=`.
- 82k: TAMU form only (`…/activsg82k/`), PowerWorld/MATPOWER/RAW/EPC formats.
  `[GATED: TAMU form]`. Only load if the 70k national slide is not enough.

**S3. EIA-860 plants + generators (via PUDL parquet)** — P0
- `https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/core_eia860__scd_plants.parquet` (3.3 MB, HTTP 200) — **has no lat/lon/state/county columns** (verified schema: 41 cols, keys `plant_id_eia, report_date`, plus `balancing_authority_code_eia, nerc_region, iso_rto_code, utility_id_eia, …`).
- `https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/core_eia860__scd_generators.parquet` (9.3 MB, HTTP 200; 69 cols incl. `generator_id, capacity_mw, prime_mover_code, energy_source_code_1, fuel_type_code_pudl, operational_status, operational_status_code, planned_generator_retirement_date, generator_retirement_date`).
- **Required for location:** `out_eia__yearly_plants.parquet` (3.6 MB, HTTP 200; 54 cols incl. `plant_name_eia, city, county, latitude, longitude, state, balancing_authority_code_eia`; latest `report_date` 2026-01-01; 1,537 TX plants in the latest year) and optionally `out_eia__yearly_generators.parquet` (13.0 MB, HTTP 200). No credentials (`--no-sign-request`). License CC-BY-4.0 (PUDL README, verified). Pin a versioned path if nightly breaks: `…/pudl.catalyst.coop/v2026.2.0/core_eia860__scd_plants.parquet` verified 200 (pattern `v{YYYY.M.0}/{table}.parquet`).
- Verified in the latest year: 24 TX coal plants (28 `existing` + 19 `retired` coal generators), and `Comanche Peak` / `South Texas Project` are present as TX nuclear plants.
- Raw fallback: `https://www.eia.gov/electricity/data/eia860/xls/eia8602024.zip` (verified HTTP 200, 22.1 MB).
- Loader: `pipelines/eia860.py::load_eia860_plants()` → `eia_plants` (helper table, not in the shared contract; columns `plant_id_eia, plant_name, lon, lat, state, county_fips, capacity_mw, primary_fuel, retirement_year, operational_status`; `lon/lat/state/county` from `out_eia__yearly_plants`, `primary_fuel` = capacity-weighted mode of `fuel_type_code_pudl`, `retirement_year` = year of `generator_retirement_date` or `planned_generator_retirement_date`, `county_fips` resolved by point-in-polygon against `counties` because PUDL gives county *name*, not FIPS), then `pipelines/eia860.py::attach_gens_to_eia(radius_km=25)` fills `gens.eia_plant_id` by nearest plant of matching `fuel` class; also seeds `site_candidates(kind in ('retired_coal','retiring_coal','existing_nuclear'))` for TX.

**S4. EIA-930 hourly BA demand** — P0
- Pattern `https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_{YYYY}_{Jan_Jun|Jul_Dec}.csv`. Verified `EIA930_BALANCE_2021_Jan_Jun.csv` HTTP 200, 43.1 MB and `EIA930_BALANCE_2024_Jul_Dec.csv` 200, 47.9 MB; header verified on both: `"Balancing Authority","Data Date","Hour Number","Local Time at End of Hour","UTC Time at End of Hour","Demand Forecast (MW)","Demand (MW)","Net Generation (MW)","Total Interchange (MW)","Sum(Valid DIBAs) (MW)","Demand (MW) (Imputed)",…,"Demand (MW) (Adjusted)",…,"Region"` (the 2024 file adds finer fuel columns; the demand columns are unchanged). Values are plain integers without thousands separators (e.g. `ERCO,02/15/2021,1,…,64579,65255,…`). Open, no login.
- P0 files: `2021_Jan_Jun` (Uri), `2024_Jul_Dec` (Beryl landfall Matagorda 2024-07-08 ~09Z; Helene landfall Big Bend FL 2024-09-27 03:10Z = Sep 26 local). P1: all halves 2018–2025 (16 files, 30–48 MB each; `2018_Jan_Jun` 30.3 MB and `2025_Jul_Dec` 48.3 MB verified 200).
- Verified on the 2021 H1 file: `ERCO` has 4,343 hourly rows (2021-01-01 07Z .. 2021-07-01 05Z), zero NULLs in `Demand (MW)` and `Demand (MW) (Adjusted)`, and the two columns are identical through the Uri window (no imputation there). 64 BA codes are present incl. `ERCO, EPE, SWPP, MISO`.
- BA reference table (BA code → region/time zone): `https://www.eia.gov/electricity/930-content/EIA930_Reference_Tables.xlsx` (45 KB, verified 200; sheets `BAs, Regions, BA Subregions, BA Connections, Energy Sources, Date Energy Sources Available, Notes`; `BAs` columns `BA Code, BA Name, Time Zone, Region/Country Code, Region/Country Name, Generation Only BA, Demand by BA Subregion, U.S. BA, Active BA, Activation Date, Retirement Date`; `ERCO` = "Electric Reliability Council of Texas, Inc.", region `TEX`).
- Loader: `pipelines/eia930.py::load_eia930(halves: list[str])` → `ba_load_hourly(ba_code, ts, demand_mw)` using `Demand (MW) (Adjusted)` falling back to `Demand (MW)`, `ts` = UTC end-of-hour.

**S5. EAGLE-I county outages 2014–2025** — P0 (2021, 2024), P1 (rest)
- **Open on figshare, CC BY 4.0, no Globus.** Article `https://api.figshare.com/v2/articles/24237376` (version 4, "…Recorded Electricity Outages 2014-2025"). Direct file URLs (verified via API; GET follows a 302 to a 10-second presigned S3 URL, so use `curl -L -o`, not HEAD):
  - `eaglei_outages_2021.csv` 1,141 MB `https://ndownloader.figshare.com/files/42547891`
  - `eaglei_outages_2024.csv` 1,445 MB `https://ndownloader.figshare.com/files/53581661`
  - `eaglei_outages_2025.csv` 1,402 MB `https://ndownloader.figshare.com/files/62164877`
  - `eaglei_outages_2023.csv` 1,200 MB `…/files/44574907`; `2022` `…/42547897`; `2020` `…/42547894`; `2019` `…/42547885`; `2018` `…/42547879`; `2017` `…/42547828`; `2016` `…/42547825`; `2015` `…/42547822`; `2014` 78 MB `…/42547717`
  - `MCC.csv` (modeled customer count per county, 2022) 40 KB `https://ndownloader.figshare.com/files/42547708`
  - `coverage_history.csv` 12 KB `…/42547714`; `DQI.csv` `…/42547705`
- Columns (verified from the file heads): `fips_code, county, state, customers_out, run_start_time` — `fips_code` is zero-padded text (`01003`), `state` is the full name (`Texas`), `run_start_time` is `YYYY-MM-DD HH:MM:SS` with no time zone. **Only the 2024 file adds `total_customers`**; 2025 has the 5-column layout again. 15-minute cadence (minutes `00/15/30/45`, verified on 2021 and 2024).
- `MCC.csv` columns: `County_FIPS,Customers` (first header carries a UTF-8 BOM; FIPS is an unpadded integer, e.g. `1001`; 254 rows with `48000 ≤ FIPS < 49000`). `coverage_history.csv` columns: `year,state,total_customers,min_covered,max_covered,min_pct_covered,max_pct_covered` with `state` = USPS code and `year` like `1/1/21`; **it covers 2018–2022 only** (TX: 2018 0.81–0.90, 2019 0.59–0.93, 2020 0.61–0.63, 2021 0.82–0.94, 2022 0.85–0.93). `DQI.csv` columns: `fema,year,success_rate,percent_enabled,spatial_precision,cust_coverage,max_covered,total_customers,DQI` (by FEMA region, 2018–2022).
- Verified Uri anchor (range-downloaded 2021-02-13 17:00 .. 02-18 11:00 from the 2021 file): Texas statewide `SUM(customers_out)` peaks at **4,257,873 at `run_start_time = 2021-02-16 19:00:00`**; 249 Texas counties report in that window.
- Loader: `pipelines/eaglei.py::load_eaglei(years, states=("Texas",))` streams each CSV through DuckDB `read_csv` with a state filter and writes `eaglei_outages(county_fips, ts, customers_out)` plus helper `county_customers(county_fips, total_customers)` from `MCC.csv` (overridden by 2024 `total_customers` where present). For P0 the Texas filter cuts 2021 to ~35 MB in DuckDB `[UNVERIFIED: DuckDB size after filter]`.
- Alternate: ORNL OpenEnergyHub `https://openenergyhub.ornl.gov/explore/dataset/eaglei_outages_2014/` (page title "EAGLE-I historic outages 2014-2025", HTTP 200) — but the Opendatasoft catalog API only lists `eaglei_outages_2014` with 0 records and `eaglei_outages_2021` returns `NotFoundResource`, so treat it as **not usable via API**; figshare is the only scriptable source. OSTI records (e.g. 2025: `https://www.osti.gov/biblio/3012826`, title "EAGLE-I Power Outage Data 2025", verified) point to Globus — not needed.

**S6. NOAA Storm Events** — P0
- Directory `https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/` (open). Files: `StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz` (10.6 MB, HTTP 200), `StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz` (12.7 MB, HTTP 200) — both re-verified in the directory listing 2026-09-05. The `c########` suffix changes when NCEI republishes — `download.sh` resolves it by listing the directory and grepping `d{YEAR}_`.
- Columns (verified): `BEGIN_YEARMONTH, BEGIN_DAY, BEGIN_TIME, END_YEARMONTH, END_DAY, END_TIME, EPISODE_ID, EVENT_ID, STATE, STATE_FIPS, YEAR, MONTH_NAME, EVENT_TYPE, CZ_TYPE, CZ_FIPS, CZ_NAME, WFO, BEGIN_DATE_TIME, CZ_TIMEZONE, END_DATE_TIME, …, MAGNITUDE, MAGNITUDE_TYPE (EG/MG/ES/MS), …, BEGIN_LAT, BEGIN_LON, END_LAT, END_LON, EPISODE_NARRATIVE, EVENT_NARRATIVE, DATA_SOURCE`. `STATE` is upper-case (`TEXAS`); `BEGIN_DATE_TIME` is local (`CZ_TIMEZONE`). Event-type strings that matter: `Winter Storm, Winter Weather, Ice Storm, Extreme Cold/Wind Chill, Cold/Wind Chill, Heavy Snow, High Wind, Strong Wind, Thunderstorm Wind, Tornado, Hurricane (Typhoon), Tropical Storm, Flash Flood, Flood, Wildfire, Excessive Heat, Heat`.
- Verified Texas Feb-2021 content: 760 rows; `Winter Storm` 201, `Extreme Cold/Wind Chill` 127, `Cold/Wind Chill` 96, `Heavy Snow` 65, `Ice Storm` 59, `Winter Weather` 59; the 446 rows of the four AC-8 types are **all `CZ_TYPE='Z'`** (747 of 760 rows are zone-typed), so the zone→county expansion is mandatory, not optional.
- Loader: `pipelines/storm_events.py::load_storm_events(years)` → `storm_events(event_id, ts_begin, ts_end, county_fips, type, magnitude)`. County FIPS = `STATE_FIPS*1000 + CZ_FIPS` only when `CZ_TYPE='C'`; zone-typed rows (`CZ_TYPE='Z'`) are mapped to counties via the NWS zone→county correlation file, currently `https://www.weather.gov/source/gis/Shapefiles/County/bp16ap26.dbx` (verified 200; pipe-delimited, no header: `STATE|ZONE|CWA|NAME|STATE_ZONE|COUNTY|FIPS|TIME_ZONE|FE_AREA|LAT|LON`, e.g. `NM|201|ABQ|Northwest Plateau|NM201|McKinley|35031|M|nw|36.4270|-108.4064`; previous edition `bp18mr25.dbx`; both listed on `https://www.weather.gov/gis/ZoneCounty`; the `WSOM/` path in the earlier draft 404s). Join key: `STATE_FIPS` + `CZ_FIPS` ↔ `STATE` + `ZONE`. If that fails, fall back to assigning the zone row to every county whose centroid is within the zone polygon from `https://www.weather.gov/source/gis/Shapefiles/WSOM/z_16ap26.zip` (listed on `https://www.weather.gov/gis/PublicZones`; prior edition `z_18mr25.zip`). Zone boundaries in force in Feb 2021 may differ slightly from the 2026 edition `[UNVERIFIED: no archived 2021 zone file checked]`.

**S7. HRRR (weather per county-hour)** — P0 for the four scenario windows; fallback S7b
- AWS Open Data bucket `noaa-hrrr-bdp-pds`, no credentials. Verified keys exist for Uri:
  `hrrr.20210213/conus/hrrr.t12z.wrfsfcf00.grib2` (140.6 MB), `hrrr.20210215/conus/hrrr.t00z.wrfsfcf00.grib2` (144.6 MB; `f01` 154.0 MB; `.grib2.idx` 9 KB). Use **analysis files `f00`** every hour (24 files/day × ~145 MB = 3.5 GB/day) but fetch only the needed GRIB messages via `herbie` byte-range subsetting (the `.idx` files exist) — 4 fields ≈ 2–3 MB/hour (upper bound; a verified `herbie` 2026.3.0 subset of `TMP:2 m above ground` + `FRZR:surface` moved well under 1 MB).
- Fields (all verified present in the 2021-02-15 00Z `.idx`): `UGRD/VGRD:10 m above ground` (→ `wind_ms`), `GUST:surface` (→ `gust_ms`), `TMP:2 m above ground` (→ `temp_c`; `DPT`/`RH:2 m` also available for heat index), `APCP:surface` and `FRZR:surface`. **`f00` carries `APCP`/`FRZR` as `0-0 day acc` (all zero); the hourly accumulations are in `f01` as `0-1 hour acc fcst`** — so `precip_mm` and `ice_mm` both come from the `f01` file of each cycle, used directly (no differencing needed). Derived fallback if a cycle's `f01` is missing: `ice_mm = precip_mm where temp_c ≤ 0`.
- `herbie` call shape (verified): `Herbie("2021-02-16 12:00", model="hrrr", product="sfc", fxx=0).xarray("TMP:2 m above ground")` → `xarray.Dataset` with `t2m (y, x)` on the 1059×1799 Lambert grid, `longitude` in 0–360.
- Aggregation: county mean via `xarray` + precomputed HRRR-grid→county index (`pipelines/hrrr.py::build_county_index()` rasterises TIGER counties on the HRRR Lambert grid once, cached in `data/parquet/hrrr_county_index.parquet`).
- Windows (P0): `uri_2021` 2021-02-11T00Z..2021-02-21T00Z (10 d — wider than the `scenarios` row 02-13..02-20 so the model's 48 h look-back features are populated); `beryl_2024` 2024-07-07..2024-07-11 (landfall Matagorda 2024-07-08 ~09Z, NHC TCR AL022024); `helene_2024` 2024-09-25..2024-09-30 (landfall Big Bend FL 2024-09-27 03:10Z, NHC; Helene is FL/GA/NC/SC/TN/VA — used for the held-out non-Texas test, Texas-only P0 may skip it); `forecast_72h` = latest HRRR `f00..f48` + NWS alerts. **HRRR runs to `f48` only on the 00/06/12/18Z cycles (verified on 2021-02-15 and 2026-09-01); other cycles stop at `f18`** — `load_hrrr_forecast` must pick the latest synoptic cycle. Hours 49–72 reuse the 48 h field, flagged.
- Loader: `pipelines/hrrr.py::load_hrrr_window(scenario_id, states)` → `weather_hourly(county_fips, ts, wind_ms, gust_ms, temp_c, ice_mm, precip_mm)`.
- **S7b fallback (P2, cheap):** NOAA ISD hourlies via `https://www.ncei.noaa.gov/data/global-hourly/access/{YEAR}/{USAF}{WBAN}.csv` (verified: `2021/72243012960.csv` = Houston IAH, 200, 7.5 MB; columns `STATION, DATE, SOURCE, LATITUDE, LONGITUDE, ELEVATION, NAME, REPORT_TYPE, CALL_SIGN, QUALITY_CONTROL, WND, CIG, VIS, TMP, DEW, SLP, AA1…` — `WND`/`TMP` are packed strings that need parsing; station list `https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv` verified 200, 2.9 MB; ~200 TX stations `[UNVERIFIED: count]`). `pipelines/isd.py::load_isd_window(scenario_id)` interpolates station values to county centroids (IDW, k=3). Same target table, `source='isd'` recorded in `scenarios`.

**S8. NWS alerts API** — P0 (`forecast_72h` live layer)
- `https://api.weather.gov/alerts/active?area=TX` (verified 200, `application/geo+json`). Requires a `User-Agent` header (`"(flux-grid-twin, <team email>)"`; verified: the same request with an empty UA returns 403). Rate limit is not public; the API docs say an exceeded limit "may be retried after the limit clears (typically within 5 seconds)".
- Event names must match `https://api.weather.gov/alerts/types` (verified): `Winter Storm Warning`, `Ice Storm Warning`, `High Wind Warning`, `Hurricane Warning`, `Tropical Storm Warning`, `Red Flag Warning`, **`Extreme Heat Warning`** (NWS renamed "Excessive Heat Warning"; the old name is no longer in the types list) plus `Heat Advisory`.
- Loader: `pipelines/nws.py::snapshot_alerts(area="TX")` → helper table `nws_alerts(alert_id, event, severity, onset, ends, geom_wkb, county_fips_list)`; `pipelines/nws.py::alerts_to_features(ts)` maps `event` to the outage model's hazard flags (Winter Storm/Ice Storm Warning → ice, High Wind/Hurricane/Tropical Storm Warning → wind, Red Flag Warning → wildfire, Extreme Heat Warning → heat).

**S9. FEMA National Risk Index (county)** — P0
- Bulk source: `https://www.fema.gov/about/reports-and-data/openfema/nri/v120/NRI_Table_Counties.zip`. It may be WAF-blocked in automated environments. The implemented fallback is FEMA's official v1.20 ArcGIS county query, state-filtered before download: `https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Counties/FeatureServer/0/query?where=STATEABBRV%3D%27TX%27&outFields=*&returnGeometry=false&f=json`. It returned 254 TX records with `NRI_VER=December 2025` during implementation. The loader accepts either artifact. Public domain (US Government work).
- Columns used (all verified present in the CSV header): `STCOFIPS` (col 9), `POPULATION` (10), `RISK_SCORE` (15), `EAL_VALT` (21), `HRCN_RISKS` (223), `ISTM_RISKS` (245), `SWND_RISKS` (341), `WFIR_RISKS` (437), `WNTW_RISKS` (463), `NRI_VER` (465); `STATE`/`COUNTY` are names, `STATEABBRV` = `TX`. 254 rows have `STATEABBRV='TX'`; Travis = `48453`, Harris = `48201`.
- Loader: `pipelines/nri.py::load_nri()` → `hazard_static.nri_score` (= `RISK_SCORE`) and `counties.pop` (= `POPULATION`); the per-hazard columns go to helper `nri_hazards(county_fips, hazard, risk_score, eal)`.

**S10. USFS Wildfire Hazard Potential 2023** — P1
- `https://www.fs.usda.gov/rds/archive/products/RDS-2015-0047-4/RDS-2015-0047-4_Data.zip` (verified 200, 368.4 MB). Catalog: "Wildfire Hazard Potential for the United States (270-m), version 2023 (4th Edition)", Dillon 2023, doi 10.2737/RDS-2015-0047-4, "can be used without additional permissions or fees" + citation requested. **The zip's payload is an Esri File Geodatabase `Data/whp2023.gdb/` (verified by reading the remote zip central directory), not a GeoTIFF** — reading the raster needs GDAL's `OpenFileGDB` raster driver (GDAL ≥ 3.7) or a one-time `gdal_translate` to GeoTIFF; continuous vs 5-class layer names `[UNVERIFIED: not opened]`.
- Loader: `pipelines/wildfire.py::load_whp()` → `hazard_static.wildfire_hazard` = county mean of the continuous index (zonal mean; `rasterstats` is **not installed** in the repo env — add it or do the zonal mean with `rasterio`+`numpy`). P0 shortcut: use `nri_hazards.WFIR_RISKS` and leave `wildfire_hazard` NULL until this runs.

**S11. USGS NSHM 2023 seismic** — P1
- ScienceBase item `64ff886dd34ed30c2057b4d9` "04. Uniform-hazard ground motion maps for the conterminous U.S., Alaska, and Hawaii": `US_PGA_2Pct_5Pct_10Pct_50Yrs_BC.zip` 59,162,562 bytes, `https://www.sciencebase.gov/catalog/file/get/64ff886dd34ed30c2057b4d9?f=__disk__76%2Ff4%2Fb4%2F76f4b416aadf6f70680106a36acc31714473b4ff` (re-verified via the ScienceBase JSON API and a full download; open). **Contents are shapefiles of hazard-map contours, not gridded points**: `US_PGA_{2Pct,5Pct,10Pct}50Yrs_BC_{arc,poly}.{shp,shx,dbf,prj}` plus ArcGIS `.lyrx` layer files. The gridded values live in the sibling `US_2023_HazardMaps.zip` (117 MB) on the same item `[UNVERIFIED: inner format of that zip]`.
- Loader: `pipelines/seismic.py::load_nshm()` → `hazard_static.seismic_pga` (county value = area-weighted mean of the `US_PGA_2Pct50Yrs_BC_poly` contour-band values intersecting the county; site class BC, in g). Also used per-site by `siting/` (point-in-polygon on the same layer).

**S12. Transmission-line / substation geometry (real overlay)** — P1
- HIFLD archived lines: DataLumos/ICPSR project 240591 `https://www.datalumos.org/datalumos/project/240591/version/V1/view` (DOI 10.3886/E240591V1 resolves there; curl gets a Cloudflare 403; shapefile, 76.8 MB `[UNVERIFIED: size, behind the challenge]`) `[GATED: Cloudflare challenge + free ICPSR account; download in a browser, drop into data/raw/hifld/]`. Substations: not located on DataLumos by search; consult the HIFLD OPEN GIS index/crosswalk project 241367 `[UNVERIFIED]`. Data Rescue Project portal `https://portal.datarescueproject.org/datasets/hifld-open-transmission-lines/` (200) links back to DataLumos. HIFLD Hub page `https://hifld-geoplatform.hub.arcgis.com/datasets/geoplatform::transmission-lines` returns 200 but only the ArcGIS Hub SPA shell to curl; the portal was decommissioned 2025-08-26 — treat as `[UNVERIFIED: may be a stub]`. source.coop `seerai/hifld` geoparquet mirror `[GATED: source.coop login]`.
- **OSM fallback (P1, scriptable):** Geofabrik `https://download.geofabrik.de/north-america/us/texas-latest.osm.pbf` (302 → dated file, e.g. `texas-260904.osm.pbf`, 718 MB on 2026-09-05; size grows weekly). Extract `power=line|minor_line|cable` and `power=substation` with `osmium tags-filter` (**the `osmium` CLI is not installed on the dev laptop; `brew install osmium-tool`**, or use `pyosmium`/`pyrosm`) → `pipelines/osm_power.py::load_osm_power(pbf)` → helper tables `real_lines(osm_id, voltage_kv, geom_wkb)`, `real_substations(osm_id, name, voltage_kv, lon, lat)`. These are a **map overlay only**; they are never joined into `lines`/`buses` (synthetic topology stays synthetic; say so in the demo).

**S13. Census TIGER counties** — P0
- `https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip` (verified 200, 83,913,260 bytes = 83.9 MB). Public domain. Verified with `pyogrio` over `/vsizip//vsicurl/`: 3,235 features, fields `STATEFP, COUNTYFP, COUNTYNS, GEOID, GEOIDFQ, NAME, NAMELSAD, LSAD, CLASSFP, MTFCC, CSAFP, CBSAFP, METDIVFP, FUNCSTAT, ALAND, AWATER, INTPTLAT, INTPTLON`; **CRS is EPSG:4269 (NAD83), not 4326** — reproject (`to_crs(4326)`; sub-metre shift) before writing `geom_wkb`.
- Loader: `pipelines/counties.py::load_counties()` → `counties(county_fips, name, state, pop, geom_wkb)` (`county_fips` = `GEOID`; `pop` filled from NRI; `state` = USPS from `STATEFP`).

**S14. DoD installation boundaries** — P0
- NTAD "Military Bases" (BTS/USDOT; layer description: "last updated on November 11, 2025 and are defined by Fiscal Year 2024 data"; `copyrightText`: a US Government work "not protected by any U.S. copyrights … available for unrestricted public use" — the service metadata does not say "CC0"). ArcGIS FeatureServer **verified**: `https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Military_Bases/FeatureServer/0/query?where=stateNameCode%3D%27TX%27&outFields=*&returnGeometry=true&outSR=4326&f=geojson` (`esriGeometryPolygon`, wkid 4326, `maxRecordCount` 2000; **824 features world-wide**, so one page covers everything). Fields (verified): `OBJECTID, countryName, featureDescription, featureName, isCui, isFirrmaSite, isJointBase, mediaId, mirtaLocationsIdpk, sdsId, siteName, siteOperationalStatus, siteReportingComponent, stateNameCode, Shape__Area, Shape__Length`. **Attribute values are lower-case codes**: `stateNameCode='tx'` (the `where` above still matches case-insensitively), `siteOperationalStatus ∈ {act, care, clsd, excs, semi}`, `siteReportingComponent='usa'` etc.; `Shape__Area` is in square degrees, not km². data.gov landing: `https://catalog.data.gov/dataset/military-bases-24048` (200); DOI 10.21949/1522149 resolves to `geodata.bts.gov/datasets/usdot::military-bases`; data dictionary DOI 10.21949/1529039. DataLumos MIRTA archive project 239599 is the gated backup.
- Verified TX content: 32 features, 31 with `siteOperationalStatus='act'` (Longhorn AAP is `excs`), incl. `Fort Cavazos`, `Fort Bliss`, `Joint Base San Antonio`, `Dyess Air Force Base`, `Sheppard AFB`, `Goodfellow Air Force Base`, `Laughlin AFB`, `Naval Air Station Corpus Christi`, `Red River Army Depot`, `NG Camp Mabry`, `NAS Fort Worth JRB TX`, `NAS Kingsville TX`, `Ellington Field Joint Reserve Base`.
- Loader: `pipelines/dod.py::load_dod(states)` → `critical_loads(kind='dod')` using the polygon centroid as `lon/lat`, `bus_id` = nearest bus with `base_kv ≥ 115` (see join J3), `name = siteName`. Keep only `siteOperationalStatus='act'` and area > 1 km² (computed in an equal-area CRS, e.g. EPSG:5070, not from `Shape__Area`) for the panel.

**S15. Hospitals** — P1
- HIFLD OPEN Hospitals archive: DataLumos project 239108 (DOI 10.3886/E239108V1 resolves to the DataLumos page) `[GATED: Cloudflare + ICPSR login]`; Data Rescue Project page `https://portal.datarescueproject.org/datasets/hifld-open-hospitals/` (200). Fallback: OSM `amenity=hospital` from the same Texas PBF (S12). Loader: `pipelines/hospitals.py::load_hospitals(source="osm"|"hifld")` → `critical_loads(kind='hospital')`, filtered to ≥100 beds when `beds` is present, else all.

**S16. EIA-861 reliability (SAIDI/SAIFI) + service territories** — P1
- Archive years: `https://www.eia.gov/electricity/data/eia861/archive/zip/f861{YYYY}.zip` (2021 verified 200, 4.4 MB). **The latest year is not in `archive/`:** `…/archive/zip/f8612024.zip` 301s to a 503 page; use `https://www.eia.gov/electricity/data/eia861/zip/f8612024.zip` (verified 200, 4.6 MB). Inside (verified for 2021 and 2024): `Reliability_{YYYY}.xlsx`, `Service_Territory_{YYYY}.xlsx`, `Sales_Ult_Cust_{YYYY}.xlsx`, `Balancing_Authority_{YYYY}.xlsx`, `Utility_Data_{YYYY}.xlsx`, `Operational_Data_{YYYY}.xlsx`, … `Service_Territory` columns: `Data Year, Utility Number, Utility Name, Short Form, State, County` (county *name*, not FIPS). `Sales_Ult_Cust` has a 3-row header and carries a `BA Code` column per utility/state/part (utility → BA link). `Reliability` has a 2-row header (`Utility Characteristics` | `IEEE Standard: All Events (With Major Event Days)` / `Without Major Event Days` / `Loss of Supply Removed` | `Other Standard`), each group holding SAIDI/SAIFI/CAIDI.
- Loader: `pipelines/eia861.py::load_eia861(years)` → helper `utility_reliability(utility_id, year, saidi_w_med, saifi_w_med, saidi_wo_med)` and `utility_county(utility_id, county_fips, year)`; county-level `saidi_trend` = customer-weighted slope over 2018–2023, consumed by the causal spec as the confounder.

**S17. Balancing-authority ↔ county mapping** — P0 (Texas), P1 (national)
- Texas P0: seeded from **EIA-861 2021 `Service_Territory_2021.xlsx`** (primary source, verified) into `pipelines/ba_map.py::TX_NON_ERCOT_COUNTIES` — every Texas county is `ERCO` except:
  - → `EPE` (El Paso Electric, utility 5701): Culberson, El Paso, Hudspeth.
  - → `SWPP` via Southwestern Public Service (17718; SPP member): Andrews, Armstrong, Bailey, Borden, Briscoe, Carson, Castro, Cochran, Cottle, Crosby, Dallam, Dawson, Deaf Smith, Donley, Ector, Floyd, Foard, Gaines, Garza, Gray, Hale, Hansford, Hartley, Hemphill, Hockley, Hutchinson, Lamb, Lipscomb, Lubbock, Lynn, Midland, Moore, Motley, Ochiltree, Oldham, Parmer, Potter, Randall, Roberts, Sherman, Swisher, Terry, Wheeler, Wilbarger, Yoakum (45 counties).
  - → `SWPP` via **Southwestern Electric Power Co. (17698) — SWEPCO is an SPP member, not MISO** (corrected): Bowie, Camp, Cass, Childress, Collingsworth, Donley, Franklin, Gray, Gregg, Hall, Harrison, Hopkins, Marion, Morris, Panola, Rains, Red River, Rusk, Shelby, Smith, Titus, Upshur, Van Zandt, Wheeler, Wood.
  - → `MISO` via Entergy Texas (55937; MISO member since 2013-12-19): Brazos, Burleson, Chambers, Falls, Galveston, Grimes, Hardin, Harris, Houston, Jasper, Jefferson, Leon, Liberty, Limestone, Madison, Milam, Montgomery, Newton, Orange, Polk, Robertson, San Jacinto, Trinity, Tyler, Walker, Waller, Washington.
  - Many of these are **split counties** (Harris, Galveston, Montgomery, Lubbock, Midland, Ector, Smith, Gregg … are majority-ERCOT). Rule: a county is non-ERCOT only if the non-ERCOT utility is its majority retail supplier `[UNVERIFIED: majority assignment; the EIA-861 file lists every county a utility touches, not shares — cross-check with `Sales_Ult_Cust` customer counts per utility/state or a service-territory map]`. Co-ops in the SPP/MISO footprints (e.g. Deep East Texas EC, Golden Spread members) are not captured by the three IOUs above `[UNVERIFIED]`.
- National P1: HIFLD OPEN Control Areas (DataLumos 239072) or Electric Retail Service Territories (239091) `[GATED: DataLumos]`; else EIA-861 `Service_Territory` → utility → BA via the `BA Code` column of `Sales_Ult_Cust_{YYYY}.xlsx` and `EIA930_Reference_Tables.xlsx`. PUDL: `core_eia861__yearly_balancing_authority.parquet` exists (verified 200) but only holds `report_date, balancing_authority_id_eia, balancing_authority_code_eia, balancing_authority_name_eia` (no utility link); the utility↔BA association is `core_eia861__assn_balancing_authority.parquet` (verified 200) `[UNVERIFIED: columns]`, and `core_eia861__yearly_service_territory.parquet` (verified 200) mirrors the county lists.
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
def load_activsg(con, aux_path: str = "data/raw/activsg2000/ACTIVSg2000.aux",
                 case: str = "ACTIVSg2000", manual_coords: str | None = None) -> dict[str, int]: ...  # rows per table
def to_pandapower(case: str = "ACTIVSg2000") -> "pandapower.auxiliary.pandapowerNet": ...   # from_mpc on the pip matpower .m
def geocode_bus_names(names: list[str], gazetteer_zip: str) -> pd.DataFrame: ...  # fallback only: name, lon, lat, score
# pipelines/activsg_aux.py
def read_aux_coords(aux_path: str) -> pd.DataFrame: ...  # bus_id, lon, lat, sub_num, sub_name (PowerWorld AUX DATA blocks)

# pipelines/counties.py
def load_counties(con, tiger_zip: str = "data/raw/tiger/tl_2024_us_county.zip", states: tuple[str, ...] | None = None) -> int: ...

# pipelines/nri.py
def load_nri(con, source_path: str) -> int: ...  # FEMA bulk ZIP or official ArcGIS JSON

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
2. Fetch the version-pinned, state-filtered FEMA v1.20 ArcGIS response into `$RAW/nri/v1.20/NRI_Counties_TX.json`; keep the bulk ZIP only as an alternate immutable artifact.
3. `curl -L -o $RAW/activsg2000/ACTIVSg2000.zip 'https://drive.usercontent.google.com/download?id=1tC-ofbw1EE46hoZeSfiBAWnSAhG0SmVu&export=download&confirm=t' && unzip -n -d $RAW/activsg2000 $RAW/activsg2000/ACTIVSg2000.zip ACTIVSg2000.aux case_ACTIVSg2000.m` (current version, 125 MB; verified one-line curl; extract only the two needed members — the zip also holds a 236 MB `.tsb`)
3a. (fallback, previous version) `curl -L -o $RAW/activsg2000/Texas2000_June2016.zip 'https://drive.google.com/uc?export=download&id=1tOIK_RVQaZZDo_oIi75bVdPsAlQ7J1l9' && unzip -n -d $RAW/activsg2000 $RAW/activsg2000/Texas2000_June2016.zip`
3b. `curl -L -o $RAW/gazetteer/2024_Gaz_place_national.zip https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip` (fallback geocoder only)
4. `curl -L -o $RAW/pudl/core_eia860__scd_plants.parquet https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/core_eia860__scd_plants.parquet`
5. `curl -L -o $RAW/pudl/core_eia860__scd_generators.parquet https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/core_eia860__scd_generators.parquet`
6. `curl -L -o $RAW/pudl/out_eia__yearly_plants.parquet https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/out_eia__yearly_plants.parquet` (**required** — the only PUDL table with plant lat/lon/state; 3.6 MB, verified 200)
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
19. `[TIER≥p1]` `for Y in 2021 2022 2023; do curl -L -o $RAW/eia861/f861$Y.zip https://www.eia.gov/electricity/data/eia861/archive/zip/f861$Y.zip; done; curl -L -o $RAW/eia861/f8612024.zip https://www.eia.gov/electricity/data/eia861/zip/f8612024.zip` (latest year lives outside `archive/`; verified)
20. `[TIER≥p1]` `curl -L -o $RAW/whp/RDS-2015-0047-4_Data.zip https://www.fs.usda.gov/rds/archive/products/RDS-2015-0047-4/RDS-2015-0047-4_Data.zip` (368 MB)
21. `[TIER≥p1]` `curl -L -o $RAW/nshm/US_PGA_2Pct_5Pct_10Pct_50Yrs_BC.zip 'https://www.sciencebase.gov/catalog/file/get/64ff886dd34ed30c2057b4d9?f=__disk__76%2Ff4%2Fb4%2F76f4b416aadf6f70680106a36acc31714473b4ff'`
22. `[TIER≥p1]` `curl -L -o $RAW/osm/texas-latest.osm.pbf https://download.geofabrik.de/north-america/us/texas-latest.osm.pbf` (718 MB on 2026-09-05) then `osmium tags-filter $RAW/osm/texas-latest.osm.pbf nwr/power=line,minor_line,cable,substation nwr/amenity=hospital nwr/man_made=water_works -o $RAW/osm/texas-power.osm.pbf`
23. `[TIER≥p1]` EIA-930 all halves 2018–2025 loop over `{Jan_Jun,Jul_Dec}`.
24. `[TIER≥p1, GATED]` echo instructions: download HIFLD lines (DataLumos 240591) and HIFLD hospitals (239108) in a browser into `$RAW/hifld/`; script checks for their presence and prints what is missing.
25. `[TIER≥p2]` ISD station files for TX (`https://www.ncei.noaa.gov/data/global-hourly/access/2021/{USAF}{WBAN}.csv` from `isd-history.csv` filtered to TX).

## Acceptance criteria

1. `uv run python -m pipelines.build --tier p0` completes on a laptop in < 25 min after downloads, producing `data/duck/grid.duckdb` with every contract table present (`ensure_schema` idempotent; second run changes no row counts).
2. `buses` has 2,000 rows; `lines` 3,206 (2,359 with `is_transformer=FALSE` + 847 transformers); `gens` 544; `loads` 1,125 summing to 67,109 MW ± 1% (all four counts verified against the pip `.m` on 2026-09-05); every `buses.lon/lat` is within the Texas bbox (−106.7..−93.5, 25.8..36.6) (AUX extent verified: −104.62..−94.37, 25.91..35.83); all 2,000 bus numbers agree on `base_kv` between the 2018 AUX and the pandapower net (verified: 0 mismatches — assert it, do not sample).
3. 100% of buses have non-NULL `lon/lat` with `coord_source='tamu_aux'` and ≥ 99% have non-NULL `county_fips`; any remainder is listed in `ingest_warnings`.
4. `counties` has 254 Texas rows (P0) with non-NULL `pop`, and `hazard_static.nri_score` non-NULL for all 254.
5. `eaglei_outages` for TX 2021-02-13..20 has ≥ 200 counties and the statewide 15-min max of `SUM(customers_out)` falls within 4.0–4.8 M (verified from the raw file: 4,257,873 at `2021-02-16 19:00:00`, 249 counties) — a sanity anchor, printed by the build.
6. `ba_load_hourly` for `ERCO` covers every hour 2021-01-01..2021-06-30 with ≤ 0.5% NULL demand (verified: 0 NULLs); **2021-02-15 18:00 UTC demand is < 50 GW and 2021-02-14 18:00 UTC is > 60 GW** (verified from the raw file: 65,255 MW at 02-15 07Z when shedding began, 54,178 MW at 09Z, first < 50 GW at 15Z = 49,849, min 43,776 at 02-16 06Z, 64,431 at 02-14 18Z; the earlier "07:00 UTC < 50 GW" was wrong). `Demand (MW) (Adjusted)` equals `Demand (MW)` for ERCO throughout the window, so this checks the column choice only weakly.
7. `weather_hourly` for `uri_2021` has 254 counties × 240 hours ± 2% (the HRRR window 02-11..02-21, wider than the `scenarios` row), `temp_c` min < −15 somewhere in the Panhandle on 2021-02-16 (verified with a herbie subset: 2 m T min −23.9 °C in the Panhandle box at 2021-02-16 12Z).
8. `storm_events` has ≥ 150 Texas rows with `type IN ('Winter Storm','Winter Weather','Ice Storm','Extreme Cold/Wind Chill')` in Feb 2021 after zone→county expansion (raw file has 446 such rows, all zone-typed, so expansion should produce well over 150).
9. `critical_loads` contains ≥ 12 `dod` rows for TX (raw: 31 active TX sites) including a row whose `name ILIKE '%Cavazos%' OR name ILIKE '%Hood%'` (raw `siteName` = `Fort Cavazos`) with a non-NULL `bus_id`.
10. `site_candidates` has ≥ 15 Texas coal rows and 2 nuclear rows, each with `bus_id` at ≥ 230 kV.
11. `to_pandapower("ACTIVSg2000")` returns a net where `pp.rundcpp` converges and total load equals `SUM(loads.p_mw_nominal)` ± 0.1%.
12. `scenarios` has the four seeded IDs with the timestamps above; `forecast_72h` is refreshed by `load_hrrr_forecast` + `snapshot_alerts` and its `ts_start` is ≤ 2 h old.
13. `export_parquet` writes one parquet per contract table; `web/` can read `data/parquet/buses.parquet` without DuckDB.
14. `download.sh` is re-runnable: it skips existing files, never deletes, and exits non-zero naming each missing gated file.

## Demo hook

Slide/interaction 1 of the demo: "This is the grid as public data lets us see it." The map shows `lines` (synthetic, colored by kV) over `real_lines` (OSM/HIFLD, grey) and `counties` shaded by `hazard_static.nri_score`, with `critical_loads(kind='dod')` pins. The copilot's `sql(...)` tool reads this DuckDB read-only; the build log (`ingest_log`) is what the copilot cites when asked "where does this data come from".

## Risks / unknowns

- **Bus coordinates** are solved by the current-version `ACTIVSg2000.aux` (verified: exact bus-id match with the pip `.m`, 2,000/2,000 coordinates). The June-2016 xlsx is a *different* case version (2,007 buses, disjoint numbering) and must not be joined to the pip case. Residual risk: Google Drive changing its large-file confirm flow (`download.sh` line 3); mitigations in order — the xlsx substation-name join (1,398/2,000 pip names match), the gazetteer fallback, and the manual CSV `data/raw/activsg2000/bus_coords_manual.csv` (`bus_id,lon,lat`).
- **EAGLE-I file size** (1.1–1.4 GB per year) on hackathon Wi-Fi; DuckDB reads the CSV once with a `state='Texas'` pushdown — do not load into pandas. Keep the raw CSV, do not re-download. The file is time-ordered, so an HTTP `Range` slice around a storm window is a valid emergency shortcut (Uri 02-13..02-18 ≈ 17 MB at byte offsets ~104.7–121.5 M of the 2021 file).
- **HRRR `FRZR`** is present in the Feb-2021 sfc files (verified); the accumulation lives in `f01`, not `f00` — a loader that reads `f00` only will get all-zero `ice_mm` and `precip_mm`.
- **Two library gaps in the repo env** (verified): `rasterstats` and the `osmium` CLI are absent (P1 only); `rapidfuzz` is present only transitively.
- **NCEI Storm Events file suffix** rotates; the directory-grep in `download.sh` handles it.
- **HIFLD archives are behind Cloudflare/ICPSR**; OSM is the scriptable overlay and is good enough for a map. Nothing in P0 depends on HIFLD.
- **BA/county boundary** for the non-ERCOT Texas counties is hand-curated `[UNVERIFIED]`; the twin only uses `ERCO` scaling so errors affect labeling, not physics.
- EIA-930 `Demand (MW) (Adjusted)` can contain imputed values (`Demand (MW) (Imputed)` column); for ERCO in 2021 H1 no hour is imputed or NULL (verified), but keep the adjusted column and flag rows where `Demand (MW)` is NULL for other BAs/years.
- Synthetic topology ≠ real topology — state it in the demo; `real_lines` is an overlay, never joined.

## Weekend time-box (hours)

| Task | Hours |
|---|---|
| `download.sh` P0 + `db.py`/`ensure_schema` | 1.0 |
| ACTIVSg2000 `.m` + AUX coordinate parser + pandapower pickle + bus-id assert | 1.5 |
| TIGER + NRI + bus→county + BA map | 1.0 |
| EAGLE-I 2021/2024 TX + MCC | 1.0 |
| Storm Events + zone→county | 1.0 |
| HRRR window via herbie + county index | 2.5 |
| EIA-930 + EIA-860/PUDL + site candidates | 1.5 |
| DoD + NWS + scenarios + export_parquet + AC checks | 1.5 |
| **P0 total** | **11** |
| P1 (EAGLE-I all years, EIA-861, WHP, NSHM, OSM overlay, hospitals, 70k case) | +6 |
| P2 (ISD fallback, 82k) | +3 |
