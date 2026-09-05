# Data Collection & Curation — Execution Plan (spec 01 lane)

*Owner: data lane · Written 2026-09-05 · **Revised against `38b1714`** (the fact-check pass:
196 verified / 106 corrected / 35 unverifiable) · Source of truth: `docs/specs/01-data-ingest.md`,
`docs/specs/00-overview.md` §2, and `docs/specs/verification/01-02.md`. This plan sequences the
spec into work, adds the technical how-to the spec leaves implicit, and records the issues found
while reading every other spec for what they expect from us.*

Tags follow the project convention: `[UNVERIFIED]` = not confirmed by us; `[VERIFY-DAY0]` =
must be checked before kickoff; `[DECISION]` = needs a human call.

**Revision note.** The first version of this plan named the June-2016 xlsx as the source of
record for `buses/lines/gens/loads`. That was wrong — it is a different case version whose bus
numbers do not match the pip `.m`. §3 S1, §5, §7 and §9 are corrected below. Two acceptance
numbers the first version repeated from the spec (the ERCO load-shed hour, the xlsx↔`.m`
spot-check) were also false and are replaced.

---

## 1. What this lane delivers, to whom

**Deliverable:** one populated database plus Parquet mirrors, containing the 13 contract tables
we own, 4 contract tables we create empty for other lanes, ~14 helper tables, a fixture DB,
an idempotent `scripts/data/download.sh`, and an `ingest_log` with sha256 provenance for every
file loaded.

**Consumers** (from `00-overview.md` §4.1):

| Table we write | Read by |
|---|---|
| `buses`, `lines` | 03 cascade, 04 siting, 06 web, 08 lines |
| `gens`, `loads` | 03, 04 |
| `counties` | 02, 03, 04, 06, 07 |
| `critical_loads` | 03, 04, 06 |
| `eaglei_outages` | 02, 06, 07 |
| `weather_hourly` | 02, 03, 07, **08** (see §9, issue I-2) |
| `storm_events` | 02, 07 |
| `hazard_static` | 02, 04, 07 |
| `ba_load_hourly` | 03 |
| `site_candidates` | 04, 06 |
| `scenarios` | everyone |

**Critical path:** 01 → 03 → 04 → 06. We are the head of it. Four lanes idle if we slip, which
is why the fixture DB ships in hour one (§5, step 0).

**Time budget:** 11 h P0 (spec), 10 h in the overview's Day-1 allocation. Our own estimate in
§5 lands at 11.5 h with slack for HRRR.

---

## 2. Storage `[DECISION]` — and how we stay unblocked either way

The specs assume DuckDB (`data/duck/grid.duckdb`, one file, "No PostGIS this weekend"). The
team is considering Postgres. **Decision needed by kickoff.** Until then, this lane is designed
so the decision does not block us:

**Parquet-first architecture.** Every loader produces a pandas/GeoPandas DataFrame and writes
`data/parquet/<table>.parquet`. A single thin module, `pipelines/db.py`, is the only code that
knows which engine is behind `connect()` / `write_table()` / `ensure_schema()`. All joins (§6)
are done in Python with GeoPandas + scipy, not in engine SQL, so they are identical under
DuckDB, Postgres, or neither. The database becomes a *load target for Parquet*, not the place
where curation happens. Swapping engines is then a one-file change on our side.

What actually differs, for the record:

| Concern | DuckDB | Postgres (+PostGIS) |
|---|---|---|
| Geometry | `geom_wkb BLOB` + `lon/lat`; `spatial` ext for `ST_*` | native `geometry(…,4326)` + GiST; keep `geom_wkb` too to satisfy the contract |
| Bulk CSV (EAGLE-I 1.1 GB) | `read_csv` with `WHERE state='Texas'` pushdown, streams | `COPY … FROM STDIN` into an UNLOGGED staging table, then `INSERT … SELECT WHERE state='Texas'`; or load with DuckDB and push via DuckDB's `postgres` extension (`ATTACH 'dbname=flux' AS pg (TYPE POSTGRES)`) |
| Hand-off between lanes | copy the `.duckdb` file to the shared drive (spec's plan) | shared instance on the LAN, or `pg_dump -Fc` circulated the same way |
| Concurrency during build | one writer OR many readers; Parquet mirrors exist to dodge the lock | true multi-writer — the strongest argument for Postgres in a 5-person build |
| Copilot `sql()` tool (spec 05) | read-only connection + statement denylist | read-only role, simpler and safer |
| Dependencies | `duckdb` (installed) | `psycopg[binary]`, `sqlalchemy`, `geoalchemy2` — **none in `pyproject.toml`** |
| Blast radius of switching | — | specs 05, 08 read paths; `/health` reports `duckdb_path`; every other lane's `connect()`; `00` §2.1 amendment required |

**Recommendation (ours, not a decision):** the switch costs the *other* lanes more than us, and
it forfeits the "one file, air-gappable" line the Second Front judges are pitched on. If
Postgres is chosen, do it as a formal amendment A8 to `00-overview.md` at kickoff so every lane
changes `connect()` once, and keep the Parquet mirrors as the demo-day hand-off regardless.

---

## 3. Inputs — source by source

Priority: **P0** = required for the Uri Texas demo; **P1** = national slide / full training;
**P2** = stretch. All URLs below were verified HTTP 200 on 2026-09-05 by the spec author unless
tagged otherwise. Each entry: what · where · format/size · how to pull · target · gotchas.

### P0

**S1 — ACTIVSg2000 (Texas synthetic grid)** → `buses`, `lines`, `gens`, `loads`
- **Coordinates come from the CURRENT-version TAMU bundle, not the June-2016 one.** 125 MB zip
  (125,303,682 B, verified):
  `https://drive.usercontent.google.com/download?id=1tC-ofbw1EE46hoZeSfiBAWnSAhG0SmVu&export=download&confirm=t`
  → `data/raw/activsg2000_current/`. Members include `ACTIVSg2000.aux` and a `case_ACTIVSg2000.m`
  byte-identical to the pip copy apart from two comment lines.
- `ACTIVSg2000.aux` is the coordinate source of record (`coord_source='tamu_aux'`). Two blocks:
  `DATA (Substation,[SubNum,SubName,SubID,Latitude,Longitude,…])` at line 18 (1,250 rows) and
  `DATA (Bus,[BusNum,…,SubNum])` at line 1326 (2,000 rows); join on `SubNum`. Verified: the AUX
  bus-id set equals the pip `.m` bus set exactly, **0 kV mismatches**, all 2,000 buses get lon/lat,
  extent −104.62..−94.37 / 25.91..35.83. A parser `pipelines/activsg_aux.py` is **required**
  (the spec's earlier "not needed while the xlsx exists" footnote is withdrawn).
- **Do NOT use the June-2016 xlsx for coordinates or topology.** It is a *different case version*:
  2,007 buses, 2,481 lines, 562 transformers, 1,417 loads summing **49,776 MW** (vs 67,109), and
  only **98 of 2,000** bus numbers are shared with the pip case — 43 of those 98 disagree on kV.
  Joining it to the pip case silently produces wrong geography. Kept at `data/raw/activsg2000/`
  for reference only. (Its columns are `"R, pu"`, `"X, pu"`, `"B, pu"` — with commas — if needed.)
- Electrical case for the twin: `case_ACTIVSg2000.m` from the pip `matpower` package
  (`.venv/lib/python3.12/site-packages/matpower/data/`), copied into the raw dir so the raw dir is
  the record. `from pandapower.converter.matpower import from_mpc` (that exact path;
  `pandapower.converter.from_mpc` does not exist), `f_hz=60` (default is 50), needs
  `matpowercaseframes`. Verified on pandapower 3.5.3: **2,000 buses, 2,359 lines, `net.trafo`
  EMPTY with 847 branches landing in `net.impedance`, 484 gen + 59 sgen + 1 ext_grid = 544,
  1,125 loads, 67,109.21 MW**; `rundcpp` 0.45 s cold, 9–14 ms warm.
- Fallbacks for coordinates, in order: (a) join pip bus names to the June-2016 `Substations`
  sheet by substation name — 1,398 of 2,000 match; (b) gazetteer geocode — strip the numeric
  suffix from `Bus Name` (`ODESSA 2 0` → `ODESSA`) and fuzzy-match the Census 2024 place
  gazetteer (`INTPTLAT`/`INTPTLONG`, `USPS='TX'`, 1,863 TX rows, 12 tab-delimited columns) with
  `rapidfuzz` ≥ 90; (c) manual override CSV `bus_coords_manual.csv (bus_id, lon, lat)`, which
  beats everything.
- `gens.fuel` from `mpc.genfuel` (GitHub `.m` line 6911; `bus_name` 7459, `gentype` 6363).
- **Cache the AUX in the team's shared storage on Day 0.** Google changes its large-file confirm
  flow periodically and this is the only scriptable source — now the top risk in §10.
- License: TAMU "free for commercial or non-commercial use", explicitly no CEII; cite Birchfield
  et al. 2017 (10.1109/TPWRS.2016.2616385).

**S13 — Census TIGER 2024 counties** → `counties`
- `https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip`, 83,913,260 B,
  public domain, 3,235 features (verified).
- `geopandas.read_file("zip://…/tl_2024_us_county.zip")`; filter `STATEFP == '48'` for P0.
- Gotcha: TIGER is **EPSG:4269 (NAD83)** — confirmed by the fact-check. Reproject to 4326 explicitly (`.to_crs(4326)`) even though
  the shift is centimetres — every other layer is 4326 and a mixed-CRS sjoin fails silently
  in some GeoPandas versions. `county_fips = STATEFP + COUNTYFP` as a 5-char **string**; never let
  it become an int anywhere (leading zeros matter nationally even if not for Texas).

**S9 — FEMA National Risk Index v1.20 (county)** → `hazard_static.nri_score`, `counties.pop`, helper `nri_hazards`
- `https://www.fema.gov/about/reports-and-data/openfema/nri/v120/NRI_Table_Counties.zip`,
  24,966,535 B. Use this OpenFEMA host; `hazards.fema.gov` 301s away.
- Columns verified at header positions: `STCOFIPS` 9, `POPULATION` 10, `RISK_SCORE` 15,
  `WFIR_RISKS` 437, `ISTM_RISKS` 245, `SWND_RISKS` 341, `HRCN_RISKS` 223, `WNTW_RISKS` 463,
  `EAL_VALT` 21, plus `STATEABBRV`. 254 TX rows. Anchors: Travis 48453 pop 1,285,769;
  Harris 48201 pop 4,726,200. Spec 07 also wants `RESL_SCORE` `[UNVERIFIED present]`.
- **Gotcha: send the default curl UA.** A browser-style User-Agent gets 403 from FEMA's WAF;
  the plain `curl` default returns 200. Read `STCOFIPS` as `dtype=str`.

**S3 — EIA-860 plants/generators via PUDL** → helper `eia_plants`, `gens.eia_plant_id`, `site_candidates`
- Anonymous S3, CC-BY-4.0. **`out_eia__yearly_plants.parquet` is REQUIRED, not optional** —
  `core_eia860__scd_plants` has **no latitude/longitude/state/county** (41 cols). Use:
  `https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/out_eia__yearly_plants.parquet`
  (3,556,945 B; 54 cols incl. `latitude, longitude, state, county, plant_name_eia`) and
  `…/out_eia__yearly_generators.parquet` (12,951,577 B; `fuel_type_code_pudl,
  energy_source_code_1, capacity_mw, operational_status, generator_retirement_date,
  planned_generator_retirement_date`). The `core_eia860__scd_*` files (3,342,979 / 9,275,784 B)
  are the fallback for fields the `out_` tables lack.
- Gotcha: `nightly/` can change schema without notice. Pin `…/pudl.catalyst.coop/v2026.2.0/<table>.parquet`
  (verified 200). Read with `pyarrow`/`polars`, filter `state == 'TX'`, latest `report_date` per plant.
- Plausibility anchor (verified): latest-year TX has 24 coal plants — 28 existing + 19 retired
  coal generators — plus `Comanche Peak` and `South Texas Project`. Satisfies AC 10.
- Raw fallback: `https://www.eia.gov/electricity/data/eia860/xls/eia8602024.zip` (22,100,342 B).

**S4 — EIA-930 hourly BA demand** → `ba_load_hourly`
- Pattern `https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_{YYYY}_{Jan_Jun|Jul_Dec}.csv`.
  P0 files: `2021_Jan_Jun` (43,073,764 B, Uri) and `2024_Jul_Dec` (47,928,993 B, Beryl + Helene).
  P1 halves range 30–48 MB each, not "~45 MB". Reference table
  `https://www.eia.gov/electricity/930-content/EIA930_Reference_Tables.xlsx` (45,201 B; sheets
  `BAs, Regions, …`; ERCO/EPE/SWPP/MISO all present).
- Use `"Demand (MW) (Adjusted)"` falling back to `"Demand (MW)"`; `ts` = `"UTC Time at End of Hour"`.
  Keep `ERCO, EPE, SWPP, MISO`. **Numbers are unquoted with no thousands separators** — do *not*
  pass `thousands=','` (raw row: `ERCO,02/15/2021,1,…,64579,65255,…`).
- **Corrected:** for ERCO in 2021 H1 there are **no imputed and no NULL hours** — `Demand (MW)
  (Adjusted)` equals `Demand (MW)` throughout all 4,343 ERCO rows, and `Demand (MW) (Imputed)`
  is NaN across 02-14..02-16. Keep the NULL-flagging logic for other BAs/years only.
- **AC 6 corrected (the original number was false).** ERCO at 2021-02-15 **07Z is 65,255 MW**,
  not < 50 GW. Real shape: 09Z = 54,178; first sub-50 GW hour is **15Z** (49,849); minimum
  **43,776 at 02-16 06Z**; 02-14 18Z = 64,431. The check is now "18Z < 50 GW **and** 02-14 18Z
  > 60 GW".
- Landfall anchors (verified): Beryl 8 Jul 2024 ≈ 09Z Matagorda TX; Helene 27 Sep 2024 0310Z.

**S5 — EAGLE-I county outages** → `eaglei_outages`, helper `county_customers`
- **Open on figshare, CC BY 4.0, no Globus** (the pitch's #1 risk is void). Article 24237376.
  Direct files: 2021 `https://ndownloader.figshare.com/files/42547891` (1,141 MB),
  2024 `…/53581661` (1,445 MB), `MCC.csv` `…/42547708` (40 KB), `coverage_history.csv` `…/42547714`.
  P1 years: 2014 `42547717`, 2015 `42547822`, 2016 `42547825`, 2017 `42547828`, 2018 `42547879`,
  2019 `42547885`, 2020 `42547894`, 2022 `42547897`, 2023 `44574907`, 2025 `62164877`.
- Pull with `curl -L -C - -o` — the GET 302s to a presigned S3 URL that expires in ~10 s, so
  **no HEAD, no `wget --spider`**, and resume support matters on hackathon Wi-Fi.
  **Download these the night before** (§5, step −1). 2.6 GB for P0 alone.
- Columns: `fips_code, county, state, customers_out, run_start_time`; **only the 2024 file adds
  `total_customers`** (2014/2021/2025 all have exactly 5 columns — the spec's "2024+" was wrong).
  15-min cadence, minutes ∈ {0,15,30,45}. Texas 2021 ≈ 8.9 M rows → ~35 MB `[UNVERIFIED]`.
- **Emergency shortcut if the full download fails:** the file is time-ordered, so an HTTP `Range`
  slice pulls just the storm window. Uri 02-13..02-18 ≈ **17 MB at byte offsets ~104.7–121.5 M**
  of the 2021 file (`curl -r 104750000-121470000`). This is how the fact-check verified AC 5.
- Load: never into pandas. DuckDB: `read_csv_auto(path) WHERE state='Texas'` streams in one pass.
  Postgres: `COPY` into unlogged staging, filter on insert. Either way keep the raw CSV; never re-download.
- `MCC.csv` (40,584 B) columns are `County_FIPS,Customers` — **BOM-prefixed, FIPS unpadded**,
  254 rows in 48xxx. `coverage_history.csv` (11,965 B): `year,state,total_customers,min_covered,
  max_covered,min_pct_covered,max_pct_covered` — **years 2018–2022 only**, so spec 02's coverage
  rule cannot be applied to 2023–2025; TX 2019 `min_pct_covered` is 0.59 (max 0.93), which is why
  02 pins the rule to `max_pct_covered`.
- Gotchas: `fips_code` may parse as int — cast to 5-char string. `run_start_time` timezone
  `[VERIFY-DAY0]` (assumed UTC; if local, the Uri peak lands 6 h off and AC 5 catches it).

**S6 — NOAA Storm Events** → `storm_events`
- Directory `https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/`. Filenames carry a
  publish suffix that rotates, so `download.sh` lists the directory and greps `d{YEAR}_`.
  Verified: `…_d2021_c20260323.csv.gz` 10,563,953 B; `…_d2024_c20260728.csv.gz` 12,693,243 B.
  51 columns; `MAGNITUDE_TYPE ∈ {EG,MG,ES,MS}` (knots).
- County FIPS = `STATE_FIPS*1000 + CZ_FIPS` **only when `CZ_TYPE='C'`**. This is the load-bearing
  path: TX Feb 2021 has 760 rows of which **747 are zone-typed**, and all **446** rows of the four
  AC-8 winter types are `Z`. Nothing usable survives without zone→county expansion.
- **Both URLs in the original plan were 404.** Corrected (verified 200):
  correlation file `https://www.weather.gov/source/gis/Shapefiles/County/bp16ap26.dbx`
  (pipe-delimited: `STATE|ZONE|CWA|NAME|STATE_ZONE|COUNTY|FIPS|TIME_ZONE|FE_AREA|LAT|LON`),
  older edition `bp18mr25.dbx`; zone shapefile `…/WSOM/z_16ap26.zip` or `z_18mr25.zip`.
  `[UNVERIFIED]` whether a 2021-era zone edition matters for Feb-2021 zone definitions — if
  zones were redrawn, expansion is approximate. Fallback stays: sjoin county centroids into
  zone polygons.

**S7 — HRRR weather (county-hour)** → `weather_hourly` — *the expensive one, 2.5 h*
- AWS Open Data `s3://noaa-hrrr-bdp-pds`, anonymous. Keys `hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcf00.grib2`
  (~145 MB/hour full). Use **`herbie`** with byte-range subsetting via the `.idx` files: four fields
  ≈ 2–3 MB/hour. Example:
  ```python
  from herbie import Herbie
  H = Herbie("2021-02-15 06:00", model="hrrr", product="sfc", fxx=0)
  ds = H.xarray(":(UGRD|VGRD):10 m above ground|:GUST:surface|:TMP:2 m above ground")
  ```
  (`search=` regex in current herbie 2026.3.0; older releases call it `searchString=`.)
- **`FRZR` is confirmed present in the Feb-2021 sfc files, and both accumulations must come from
  `f01`, not `f00`.** The `f00` idx lines read `FRZR:surface:0-0 day acc fcst` and `APCP:surface:
  0-0 day acc` — i.e. zero-length accumulation windows, so a loader that reads only `f00` gets
  **all-zero `ice_mm` and `precip_mm`**. The `f01` idx gives `0-1 hour acc` for both. Verified
  file sizes: f00 140.6–144.6 MB, f01 154,024,601 B; `.idx` 9,099 B.
  The `ice_mm = precip_mm where temp_c <= 0` fallback is no longer needed but stays as a guard.
- **System dependency:** `cfgrib` needs the ecCodes C library. `[VERIFY-DAY0]` on every laptop that
  will run this: `python -c "import cfgrib"`; fix with `pip install eccodes` (binary wheels) or
  `apt install libeccodes0` / `brew install eccodes`. This is the single most likely "works on my
  machine" failure in the lane.
- County aggregation: HRRR is a 3 km Lambert-conformal grid (1799 × 1059 ≈ 1.9 M cells). Build a
  **grid-cell → county index once**: take cell centroids inside the Texas bbox (~60 k cells),
  `geopandas.sjoin` against TIGER counties, cache to `data/parquet/hrrr_county_index.parquet`.
  Then every hour is a groupby-mean over that index — no rasterio needed. Wind speed
  `= hypot(UGRD, VGRD)`; temp `K → °C`.
- Windows: `uri_2021` 2021-02-11..21 (10 d, wider than the scenario so spec 02's 48–72 h lag
  features have history), `beryl_2024` 07-07..11, `helene_2024` 09-25..30 (non-Texas; P0 may skip),
  `forecast_72h` = latest run `fxx=1..48`, hours 49–72 copy hour 48 with a `stale` flag —
  **only the 00/06/12/18Z cycles reach f48**, other cycles stop at f18, so the forecast refresh
  must pick a 6-hourly cycle. P0 volume: ~240 + 96 h ≈ 340 hours × 3 MB ≈ 1 GB, ~30–60 min wall.
  Verified anchor for AC 7: 2 m temperature in the Panhandle box on 2021-02-16 12Z bottoms at
  **−23.9 °C**.
- **Full-year weather is needed by specs 02 and 08 and is not in P0** — see §9, I-1/I-2, and the
  ISD plan under P1 below.

**S14 — DoD installation boundaries** → `critical_loads(kind='dod')`
- NTAD Military Bases, ArcGIS FeatureServer, GeoJSON, polygon/wkid 4326:
  `https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Military_Bases/FeatureServer/0/query?where=stateNameCode%3D%27tx%27&outFields=*&returnGeometry=true&outSR=4326&f=geojson`.
  Fields `siteName, siteReportingComponent, siteOperationalStatus, stateNameCode, isJointBase`.
  824 features total, **32 in TX (31 active), including `Fort Cavazos`**; `maxRecordCount` 2000,
  so TX needs no paging (CONUS would). FY2024 data, last updated 2025-11-11. Licence is
  "US Government work, unrestricted public use" — **not CC0**, as the first version said.
- **Field values are lower-case:** `stateNameCode='tx'` and `siteOperationalStatus='act'`
  (domain `act|care|clsd|excs|semi`). Filtering on `'Active'` or `'TX'` returns nothing.
- Keep `siteOperationalStatus='act'` and area > 1 km²; `lon/lat` = polygon centroid
  (`.to_crs(3083).centroid.to_crs(4326)` — compute centroids in a projected CRS, Texas Albers 3083,
  or GeoPandas warns and the result is subtly wrong). Acceptance #9 needs a row matching
  `Cavazos|Hood` with a non-NULL `bus_id`.

**S8 — NWS alerts** → helper `nws_alerts` (forecast_72h)
- `https://api.weather.gov/alerts/active?area=TX`, GeoJSON. **Requires a `User-Agent`** header
  (`(flux-grid-twin, <team email>)`) — an empty UA returns 403, verified. Undocumented rate limit,
  retry after ~5 s. Snapshot to `data/raw/nws/alerts_TX_<UTC hour>.geojson`.
- **Event-name correction:** there is no `Excessive Heat Warning` in `api.weather.gov/alerts/types`.
  The real names are `Extreme Heat Warning`, `Extreme Heat Watch`, `Heat Advisory`. Spec 02's
  flag mapping was renamed accordingly — match on those, not the old string.

**S17 — County → balancing authority** → `counties.ba_code` (via `buses.ba_code`)
- Dict in `pipelines/ba_map.py`, now sourced from **EIA-861 2021 `Service_Territory`** rather than
  hand-curation. Default `ERCO`, then: SPS (utility 17718) **45 TX counties → `SWPP`**;
  **SWEPCO (17698) 25 counties → `SWPP`** — corrected, the first version put SWEPCO in MISO, but
  AEP/SWEPCO is an SPP member; Entergy Texas (55937) **27 counties → `MISO`** (joined 2013-12-19);
  EPE (5701) **3 counties → `EPE`**. Full lists are in spec 01 S17.
- Caveat that survives: EIA-861 lists every county a utility *touches*, not shares, so the
  split-county majority rule is still `[UNVERIFIED]` and SPP/MISO co-ops are not captured. Low
  blast radius — only `ERCO` scaling touches physics; the rest is labelling.

**Scenarios seed** → `scenarios` (4 rows; see §9, I-5 for the Uri end-time conflict).

### P1 (do after Gate B, or in the background on Day 1)

**S7b — NOAA ISD station hourlies** → `weather_hourly` for **full years** (the fix for I-1/I-2)
- Station list `https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv` (2,914,601 B, verified;
  filter `STATE='TX'`, active through the year) → `[UNVERIFIED: ~200 stations]`. Files
  `https://www.ncei.noaa.gov/data/global-hourly/access/{YEAR}/{USAF}{WBAN}.csv` — pattern verified
  (`2021/72243012960.csv`, 7,531,911 B), so budget nearer 5–8 MB each and ~1–2 GB per year.
  Open, no account.
- Parse: `WND` field = `dir,q,type,speed×10,q` (speed m/s ÷ 10); `TMP` = `temp×10,q` (°C ÷ 10);
  `AA1` = precip period + depth. Wind gust is in `OC1` where present. Freezing rain only via
  present-weather codes (`AW1`/`MW1`), i.e. a flag not an accumulation — `ice_mm` degrades to a
  proxy `[UNVERIFIED how spec 02 wants this handled; propose ice_mm = precip_mm where temp ≤ 0 and
  FZRA code present]`.
- Interpolate station → county centroid with inverse-distance weighting, k=3
  (`sklearn.neighbors.BallTree(metric='haversine')` — sklearn is installed). Record
  `source='isd'` vs `'hrrr'` per row so 02 can weight them.
- Why ISD and not ERA5: ERA5 needs a CDS account and its queue can take hours; ISD is a curl.

**S16 — EIA-861 reliability + service territories** → `utility_reliability`, `utility_county`
- **URL differs by year.** 2021: `…/eia861/archive/zip/f8612021.zip` (4,427,163 B, 200).
  2024: the `archive/zip/` path 301s then 503s — use `…/eia861/zip/f8612024.zip`
  (4,568,208 B, 200). Inner members verified: `Reliability_{YYYY}.xlsx`,
  `Service_Territory_{YYYY}.xlsx`, `Sales_Ult_Cust_{YYYY}.xlsx`, `Balancing_Authority_{YYYY}.xlsx`.
  Spec 07 needs 2018–2023 for the SAIDI trend; S17 above now depends on this too.
- PUDL note: `core_eia861__yearly_balancing_authority` exists but is the **wrong table** (no
  utility link). Try `core_eia861__assn_balancing_authority` `[UNVERIFIED columns]`.

**S10 — USFS Wildfire Hazard Potential** → `hazard_static.wildfire_hazard`
- `https://www.fs.usda.gov/rds/archive/products/RDS-2015-0047-4/RDS-2015-0047-4_Data.zip`,
  368,424,961 B. **Not a GeoTIFF** — the payload is `Data/whp2023.gdb/`, an Esri FileGDB
  (WHP 270 m, 2023 4th edition, Dillon 2023, free with citation). Needs a FileGDB reader
  (`pyogrio`/GDAL) rather than plain rasterio; layer names `[UNVERIFIED]`. `rasterstats` is
  **absent from the env** (confirmed). P0 shortcut stands: leave NULL, use `nri_hazards.WFIR_RISKS`.

**S11 — USGS NSHM 2023 PGA** → `hazard_static.seismic_pga`
- ScienceBase `US_PGA_2Pct_5Pct_10Pct_50Yrs_BC.zip`, 59,162,562 B. **Not grids** — the contents
  are contour **shapefiles** `US_PGA_{2,5,10}Pct50Yrs_BC_{arc,poly}.*` plus `.lyrx`. So the
  loader is a polygon overlay (sjoin county centroid / area-weighted mean over `poly`), not a
  zonal raster mean. Sibling `US_2023_HazardMaps.zip` (117 MB) `[UNVERIFIED]` may hold rasters.
  Feeds `hazard_static.seismic_pga` and spec 04's S3 per-site criterion.

**S12 — Real transmission geometry overlay** → helpers `real_lines`, `real_substations`
- HIFLD archived lines: DataLumos 240591 — **gated** (Cloudflare + free ICPSR account, browser only).
  Drop into `data/raw/hifld/`. Spec 08 wants this for owner attribution (≥ 50 % match on ≥ 230 kV).
- Scriptable fallback: Geofabrik `texas-latest.osm.pbf` → 302 to the dated
  `texas-260904.osm.pbf`, **718,093,892 B** (not 684 MB) →
  `osmium tags-filter … nwr/power=line,minor_line,cable,substation nwr/amenity=hospital nwr/man_made=water_works`
  → `pyosmium` or `osmnx` to read. **`which osmium` returns nothing** — the CLI is genuinely
  absent, `apt install osmium-tool` first. Overlay only; **never joined into `lines`/`buses`**.
- DataLumos 240591's "76.8 MB" is `[UNVERIFIED]` — the site 403s behind Cloudflare, so neither
  the size nor the project ids 239072/239091/239599/241367 could be confirmed.

**S15 — Hospitals** → `critical_loads(kind='hospital')`: HIFLD 239108 (gated) or OSM `amenity=hospital` from the same PBF.

**S2 — ACTIVSg10k/25k/70k** for the national slide: same `matpower` package, same loader, `case=`.

### P2
ACTIVSg82k (TAMU form, gated); water utilities via OSM `man_made=water_works`.

### Layers other lanes need that are *not* in spec 01 (coordinate, do not silently own)
Spec 04's safety screen needs Census **tract** population + geometry, FEMA NFHL floodplains,
NHDPlus flowlines/waterbodies, PAD-US, USGS 3DEP slope, NWI wetlands — Texas clips. Spec 04's
time-box owns the downloads (2 h). We should agree on Day 0 who pulls them and where they land
(`data/raw/census/`, `data/raw/fema_nfhl/`, `data/raw/nhd/`, …) so two people don't do it twice.

---

## 4. Pipeline architecture

```
scripts/data/download.sh          idempotent raw fetch → data/raw/<source>/ ; TIER=p0|p1|p2
pipelines/
  db.py            connect() / ensure_schema() / write_table() / export_parquet()   ← the ONLY engine-aware file
  build.py         build(tier, states) — runs loaders in dependency order, writes ingest_log
  activsg.py       pip .m → buses, lines, gens, loads; to_pandapower() pickle for spec 03
  activsg_aux.py   REQUIRED: parse ACTIVSg2000.aux Substation+Bus blocks → buses.lon/lat
  counties.py      TIGER → counties
  nri.py           NRI → hazard_static, counties.pop, nri_hazards
  eia860.py        PUDL → eia_plants; attach_gens_to_eia(); seed_site_candidates()
  eia930.py        → ba_load_hourly
  eaglei.py        → eaglei_outages, county_customers
  storm_events.py  → storm_events (with zone→county)
  hrrr.py          build_county_index(); load_hrrr_window(); load_hrrr_forecast()
  isd.py           load_isd_window() — P1 full-year weather
  nws.py           snapshot_alerts(); alerts_to_features()
  dod.py           → critical_loads(dod)
  hospitals.py     → critical_loads(hospital)
  osm_power.py     → real_lines, real_substations
  wildfire.py / seismic.py / eia861.py   P1 hazard + reliability
  ba_map.py        TX_NON_ERCOT_COUNTIES; assign_ba()
  joins.py         join_bus_county(); join_critical_loads_to_bus()   — GeoPandas/scipy, engine-agnostic
  fixtures/make_fixture_db.py
```

Conventions:
- Every loader: `def load_x(con, path, …) -> int` (rows written). Delete-by-source-key, then insert.
  Second run changes no counts.
- Every raw file: sha256 recorded in `ingest_log(source, file, sha256, rows, loaded_at)` before load.
- Geometry: EPSG:4326 everywhere; `geom_wkb` as `shapely.to_wkb()` bytes; `lon`/`lat` doubles on
  point tables. Timestamps: UTC, tz-naive after conversion (document it in one place).
- FIPS: 5-char string, always. A helper `fips5()` used by every loader.
- `export_parquet()` after every build. Parquet is the hand-off artifact whatever the engine.

---

## 5. Step-by-step execution

### Step −1 — Day 0 (the night before). ~1.5 h, mostly waiting on downloads
1. Run `download.sh` with `TIER=p0` on the fastest connection available. EAGLE-I 2021 + 2024
   (2.6 GB) is the reason — hackathon Wi-Fi will not do it in a reasonable time.
2. `[VERIFY-DAY0]` checklist (shortened — the fact-check already closed FRZR, the zone-file URLs,
   and `rapidfuzz`):
   - `uv run python -c "import duckdb, pandapower, lightgbm, geopandas, herbie, cfgrib"` on every data-lane laptop.
   - **Download the 125 MB current-version zip and copy `ACTIVSg2000.aux` to shared storage** —
     the single highest-value 10 minutes of Day 0 (§10 risk 1).
   - **Assert AUX bus-id set == pip `.m` bus-id set, 2,000/2,000, 0 kV mismatches.** This replaces
     the old xlsx spot-check, which was checking the wrong file.
   - `rasterstats` and `osmium` are confirmed absent; `rapidfuzz` is present but only transitively.
     Decide whether to add them to `pyproject.toml` (P1 only — ask first, A2 says one root env).
   - EAGLE-I `run_start_time` timezone — the one genuinely open item. Range-read the 2021 file at
     offsets ~104.7–121.5 M and check the statewide peak lands at **2021-02-16 19:00** (4,257,873).
   - `herbie` can fetch one Uri hour, **and confirm `f01` returns non-zero `FRZR`/`APCP`**.
3. Storage `[DECISION]` closed, `db.py` targets it.

### Step 0 — 08:30–09:30 · Fixture DB + schema · **Gate: fixture exists**
- `db.py::ensure_schema()` creates all 17 contract tables (DDL in spec 01 §Outputs) plus
  `corpus_chunks` and `line_upgrade_detail` (amendment A4 says we create these).
- `make_fixture_db.py`: ~20 buses, 30 lines, 5 counties (real TIGER polygons for e.g. Travis,
  Harris, Bell, Bexar, Dallas), 1 synthetic scenario `fixture_01`, 48 hours of made-up
  `weather_hourly` + `ba_load_hourly`, 3 `critical_loads`, 3 `site_candidates`. Deterministic
  (seeded). This is what unblocks 02–08 at Gate A.
- Hand the fixture off *before* starting real ingest.

### Step 1 — 09:30–12:00 · Twin skeleton + geography · **Gate: 2000 / 3206 / 254 rows**
1. `counties` from TIGER (TX only). `hazard_static` + `counties.pop` from NRI. `[0.5 h]`
2. `buses/lines/gens/loads` from the **pip `.m`**, coordinates from **`ACTIVSg2000.aux`**
   (`coord_source='tamu_aux'`). Line `length_km` = haversine × 1.15 when the case has none;
   `geom_wkb` = straight `LINESTRING`. Transformer branches arrive in `net.impedance` (847), not
   `net.trafo` — keep them in `lines` with `is_transformer=TRUE`, `length_km=0`. `[1.0 h]`
3. **J1 bus→county** (§6). `[0.3 h]`
4. **J2 county→BA**, `buses.ba_code` inherits. `[0.2 h]`
5. `to_pandapower()` → `data/parquet/twin_ACTIVSg2000.p`; assert `rundcpp` converges, total load =
   `SUM(loads.p_mw_nominal)` ± 0.1 %. `[0.3 h]`
6. `scenarios` seed. `export_parquet()`. `[0.2 h]`

### Gate A — 12:00 — every lane runs on the fixture DB.

### Step 2 — 13:00–15:00 · Load, weather, events, critical loads · **Gate: `weather_hourly` covers Uri for 254 counties**
1. `ba_load_hourly` from EIA-930 2021 H1 + 2024 H2. Check **18Z** on 02-15 (< 50 GW) and 18Z on
   02-14 (> 60 GW) — not 07Z, which is 65 GW. `[0.4 h]`
2. `eaglei_outages` 2021 + 2024 TX, `county_customers` from MCC + 2024 `total_customers` (2021 has
   no such column). Print the Uri peak; expect **4,257,873 at 2021-02-16 19:00 across 249
   counties**. `[0.6 h]`
3. `storm_events` 2021 + 2024 with zone→county expansion. Count Feb-2021 winter rows ≥ 150. `[0.7 h]`
4. `weather_hourly` for `uri_2021` (start the herbie pull in the background at 13:00; it runs while
   2–3 happen), then `beryl_2024`. `[2.0 h wall, ~0.8 h attention]`
5. `critical_loads` from DoD; **J3 critical load→bus** (§6). Confirm Fort Cavazos has a `bus_id`. `[0.4 h]`
6. `eia_plants`, `gens.eia_plant_id`, `site_candidates` (≥ 15 coal, 2 nuclear, each `bus_id` at the
   agreed kV — see I-6). `[0.6 h]`
7. `export_parquet()`; run all 14 acceptance checks as a script, print a table. `[0.3 h]`

### Gate B — 19:00 — real DB replaces fixture; beats 1–3 work on real data.

### Step 3 — Day 1 evening / background · P1 that other lanes are waiting on
1. ISD full-year 2021 + 2024 → `weather_hourly` outside the HRRR windows (I-1, I-2). Start the
   ~1 GB/yr download early; the parse + IDW is ~1 h. `[1.5 h]`
2. `forecast_72h`: `load_hrrr_forecast()` + `snapshot_alerts()`; `scenarios.ts_start` refreshed. `[0.7 h]`
3. EIA-861 2018–2023 for spec 07's confounder. `[0.6 h]`
4. OSM Texas PBF → `real_lines`, `real_substations`, hospitals — the map overlay for beat 1 and
   spec 08's owner attribution. `[1.0 h]`

### Step 4 — Day 2 morning · scale slide + polish `[1 h]`
ACTIVSg70k load for the national H3 hex layer (`/layers/national_hex`); any AC still red.

**Estimated total: P0 ≈ 6.5 h attention (≈ 8 h wall with HRRR) + fixture 1 h + Day 0 1.5 h;
P1 ≈ 4 h. Fits the 11 h spec budget with ~1 h slack, all of which HRRR can eat.**

---

## 6. The joins — technical detail

All in Python, engine-agnostic, in `pipelines/joins.py`.

**J1 bus → county.**
```python
pts = gpd.GeoDataFrame(buses, geometry=gpd.points_from_xy(buses.lon, buses.lat), crs=4326)
hit = gpd.sjoin(pts, counties[["county_fips","geometry"]], how="left", predicate="within")
```
Unmatched (coastal jitter, buses just offshore): nearest county **centroid** within 30 km using
`BallTree(metric="haversine")` on centroids computed in EPSG:3083; else NULL + a row in
`ingest_warnings`. Acceptance: ≥ 99 % matched, remainder listed. Print the count assigned by fallback.

**J2 county → BA.** Dict lookup, default `ERCO`. `buses.ba_code = counties.ba_code[buses.county_fips]`.

**J3 critical load → bus.** For each critical load, nearest bus among `base_kv >= 115`
(BallTree haversine), ties → higher kV. Store the distance in `critical_load_bus_dist`. Spec 03
additionally says "within the same county" — `[UNVERIFIED which wins]`; propose: same-county
first, fall back to nearest-anywhere, record which.

**Gen → EIA plant.** Nearest `eia_plants` row with the same fuel class (coal, gas, nuclear, hydro,
wind, solar, other) within 25 km. Synthetic gens do not correspond 1:1 to real plants; expect a
modest match rate and print it. Used only for `site_candidates` seeding and the `retiring` flag on
the map.

**Site → bus.** Nearest bus at ≥ 230 kV (spec 01) *or* ≥ 138 kV within 40 km (spec 04) — I-6.

**Load scaling (hand-off to spec 03, not a join we run).** `k = ba_load_hourly.demand_mw(ERCO, ts) / SUM(p_mw_nominal WHERE ba_code='ERCO')`.
Our obligation: `ba_load_hourly` has every hour with ≤ 0.5 % NULL, and `buses.ba_code` is right
for the buses that carry the load — a wrong BA label on a big-load bus changes the denominator.

---

## 7. Data quality checks (run as one script, `pipelines/checks.py`)

The 14 acceptance criteria from spec 01, plus a few that catch classic bugs:

| # | Check | Catches |
|---|---|---|
| A2 | 2000 buses, 3206 branches (2359 line + 847 impedance), 544 gen-equivalents (484+59+1), 1125 loads, 67,109.21 MW ± 1 % | wrong case version, dropped impedance branches |
| A2 | every bus inside TX bbox (−106.7..−93.5, 25.8..36.6); AUX extent is −104.62..−94.37 / 25.91..35.83 | lat/lon swapped |
| A2 | **AUX bus-id set == pip `.m` bus-id set, 2,000/2,000, 0 kV mismatches** | wrong case version (the June-2016 xlsx shares only 98 ids) |
| A3 | 100 % `lon/lat` non-NULL with `coord_source='tamu_aux'`, ≥ 99 % `county_fips` | broken join |
| A5 | Uri 15-min statewide `SUM(customers_out)` max = 4,257,873 at 2021-02-16 19:00, ≥ 249 counties | timezone, state filter, dupes |
| A6 | ERCO 2021-02-15 **18Z < 50 GW** and 02-14 18Z > 60 GW; **0** NULL ERCO rows in H1-2021 | wrong demand column, local-time parse |
| + | `weather_hourly.ice_mm` and `precip_mm` are not identically zero over Uri | loader read `f00` instead of `f01` |
| A7 | `weather_hourly` uri: 254 × 240 ± 2 %; Panhandle min temp < −15 °C on 02-16 | K→°C missed, county index off |
| A8 | ≥ 150 TX winter-type storm rows Feb 2021 | zone expansion failed |
| A9 | ≥ 12 `dod` rows; one matches `Cavazos|Hood` with `bus_id` | DoD filter/centroid |
| A10 | ≥ 15 coal + 2 nuclear sites, each with `bus_id` | PUDL schema drift |
| A1 | second `build()` run: identical row counts | non-idempotent loader |
| + | no `county_fips` shorter than 5 chars anywhere | int coercion |
| + | `weather_hourly.ts` and `ba_load_hourly.ts` on exact hour boundaries, UTC | end-of-hour vs start-of-hour |
| + | `SUM(customers_out)` never exceeds `SUM(total_customers)` per county | MCC join wrong |
| + | every `ingest_log` row has a sha256 matching the file on disk | stale raw file |

---

## 8. Tooling

| Need | Tool | Status |
|---|---|---|
| Downloads | `curl -L -C -` in `download.sh`; `herbie` for HRRR; `requests` for ArcGIS/NWS | ok |
| Tabular | `pandas`, `polars`, `pyarrow` | installed |
| AUX parse | plain Python (the two `DATA (…)` blocks) | no dep |
| Excel (fallback path only) | `openpyxl` | `[VERIFY-DAY0]` |
| Spatial | `geopandas`, `shapely`, `pyproj`, `pyogrio`; `scipy.spatial.cKDTree` / `sklearn.neighbors.BallTree` | installed |
| GRIB | `herbie-data` 2026.3.0, `xarray`, `cfgrib` + **ecCodes system lib** | `[VERIFY-DAY0]` |
| FileGDB / shapefile hazards (P1) | `pyogrio`/GDAL — **not** `rasterio`; WHP is a FileGDB, NSHM is contour shapefiles | `rasterstats` **absent** |
| Fuzzy match (fallback) | `rapidfuzz` 3.14.6 | present, but **not declared in `pyproject.toml`** |
| OSM (P1) | `osmium-tool` CLI + `pyosmium` | **absent** (`which osmium` → nothing) |
| Grid case | `matpower`, `matpowercaseframes`, `pandapower` | installed |
| DB | `duckdb` (installed) / `psycopg[binary]` + `geoalchemy2` (not installed) | `[DECISION]` |
| Checks | plain `pytest` over `checks.py` | `dev` extra |

---

## 9. Issues found and open questions

**I-1 · Spec 02 needs full-year weather; P0 only delivers scenario windows.** 02 trains on
Texas 2021 + 2024 (~740 k county-windows) with weather features, but P0 `weather_hourly` covers
~340 hours — and those hours are the held-out storms. Trained that way the model learns
"weather NULL ⇒ no outage". Fix: ISD full-year hourlies (P1 S7b, ~1 GB/yr, no account) for the
bulk, HRRR for the scenario windows where precision matters; `source` column on every row.
**Raise with 02's owner at kickoff; this changes their Day-1 afternoon.**

**I-2 · Spec 08 needs a full year of 2024 hourly weather** for DLR climatology
(`data/parquet/weather_hourly_2024/`). Same fix as I-1; HRRR for 8,760 hours would be ~25 GB
of subset pulls and most of a day — not happening. ISD or a seasonal sample.

**I-3 · `site_candidates.kind` enum.** Spec 01 S3 text says `('retired_coal','retiring_coal','existing_nuclear')`;
amendment A3 fixes it as `coal_retired | coal_retiring | nuclear_existing`. **We follow A3.**

**I-4 · Bus coordinates source. RESOLVED — and spec 03 was right.** Coordinates come from the
AUX, but from the **current-version** `ACTIVSg2000.aux`, not the June-2016 one (whose `Bus` block
has no lat/lon at all — the join key there is `SubNum`, and its Substation block sits at line
7677). The first version of this plan named the xlsx and was wrong. See §3 S1.

**I-5 · Uri window end. RESOLVED as deliberate.** `00` §2.3 says `ts_end` 2021-02-20T23:00Z;
the `scenarios` seed and spec 03's "168 h" imply 02-20T00:00Z; spec 02's 28 six-hour windows
match the 7-day reading. The fact-check confirms the **HRRR window (02-11..02-21, 240 h) is
intentionally wider** than the scenario so lag features have history — the two numbers were never
in conflict. Still worth pinning 00:00Z in `00` so AC 7's "254 × 240" is unambiguous.

**I-6 · Site `bus_id` kV threshold.** Spec 01: nearest bus ≥ 230 kV. Spec 04: ≥ 138 kV within
40 km, else `unconnected`. Different thresholds produce different candidate sets. **Propose 04's
rule** (it owns the semantics) and record the distance so 04 can re-filter.

**I-7 · Critical load → bus: same-county constraint?** Spec 03 says "≥ 115 kV within the same
county"; spec 01 says nearest ≥ 115 kV, no county constraint. Propose same-county first, fallback
nearest, `critical_load_bus_dist` records which.

**I-8 · Layers spec 04 needs that nobody downloads in 01** (tracts, NFHL, NHDPlus, PAD-US, 3DEP,
NWI). Agree owner and paths on Day 0.

**I-9 · Missing deps — CONFIRMED by the fact-check.** `rasterstats` and the `osmium` CLI are
genuinely absent; `rapidfuzz` (3.14.6) imports but is not declared in `pyproject.toml`, so it is
one `uv sync` away from vanishing. Plus ecCodes (system) and a Postgres driver if that decision
lands. All P1 except `rapidfuzz`. A2 says one root env — add via PR, not ad hoc installs.

**I-10 · HRRR `FRZR`. RESOLVED — present, but in `f01`.** Verified in the Feb-2021 sfc idx files.
The trap is that `f00` carries `0-0 day acc` windows for both `FRZR` and `APCP`, so an `f00`-only
loader yields all-zero ice and precip and nobody notices until the outage model has no ice
signal. Read `f01`. Added as a check in §7.

**I-13 · `lightsim2grid` cannot load this case — cross-lane, tell spec 03's owner.** The 847
transformer branches import into `net.impedance`, and lightsim2grid rejects the net with
"Unsupported element (Impedance)". Spec 03 makes lightsim its **default** solver and budgets
120 s per scenario on a claimed ≥20× speedup; that path is now stretch-only and the cascade
falls back to pandapower at 6-hour stride. Not our deliverable, but it sits on the critical path
directly downstream of us.

**I-14 · P1 hazard layers need different loaders than specified.** WHP is an Esri FileGDB, not a
GeoTIFF; NSHM ships contour shapefiles, not grids. Both need `pyogrio`/GDAL vector reads rather
than `rasterio` + `rasterstats` zonal means. Re-estimate that work before promising it to 04.

**I-11 · Disk.** P0 raw ≈ 2.6 GB EAGLE-I + 1 GB HRRR subsets + 0.3 GB misc; P1 adds ~2 GB ISD,
0.7 GB OSM, 0.4 GB WHP, and 10 GB more EAGLE-I if all years. Budget 20 GB free per data laptop.

**I-12 · Timezones.** Three different conventions in the inputs: EIA-930 has both local and UTC
columns; EAGLE-I `run_start_time` `[VERIFY-DAY0]`; Storm Events `BEGIN_DATE_TIME` is local with a
`CZ_TIMEZONE` column (`CST-6`). Convert everything to UTC at load and assert hour alignment.

---

## 10. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| EAGLE-I download too slow on venue Wi-Fi | High | Blocks 02 | Download Day 0; bring on a USB stick as well |
| ecCodes/cfgrib not importable on someone's laptop | High | HRRR blocked on that machine | Day-0 check; designate one HRRR machine |
| **Google Drive `confirm=t` flow changes** — the only scriptable source for the current-version AUX | Medium | No coordinates → no map | **Cache the AUX in shared storage on Day 0.** Then: substation-name join (1,398/2,000), gazetteer, manual CSV — each degrades quality |
| Storm Events zone→county: 2021-era zone definitions may differ from the 2026 file | Medium | A8 approximate; 02 loses feature fidelity | `bp16ap26.dbx` verified 200; zone-polygon sjoin fallback; state the approximation |
| Someone rebuilds geography from the June-2016 xlsx | Medium | Silent wrong coordinates | The `coord_source='tamu_aux'` assert in §7 fails loudly if they do |
| PUDL nightly schema drift | Medium | S3 loader breaks | Pin versioned path |
| Storage decision late | Medium | `db.py` rewrite mid-day | Parquet-first; decide at kickoff |
| Full-year weather (I-1/I-2) surprises 02/08 | High if unraised | Model trains on holdouts only | Raise at kickoff; ISD plan |
| HRRR pull eats the 13:00–15:00 slot | Medium | Gate B slips | Start it at 13:00 in background; Beryl can slip to evening |

---

## 11. Definition of done for this lane

- [ ] `download.sh` re-runnable, skips existing, exits non-zero naming each missing gated file.
- [ ] `build --tier p0` < 25 min after downloads; second run changes no counts.
- [ ] All 14 spec-01 acceptance criteria green in `checks.py`, printed as a table.
- [ ] Fixture DB shipped and used by ≥ 1 other lane before Gate A.
- [ ] `ingest_log` complete with sha256 for every raw file.
- [ ] Parquet mirror for every contract table.
- [ ] Open issues raised with their owners and resolutions recorded in `00-overview.md`
      amendments: I-1, I-2, I-3, I-6, I-7, I-8, I-9, I-12, I-14 — and **I-13 to spec 03's owner
      before they plan around lightsim2grid**. (I-4, I-5, I-10 are closed by the fact-check.)
- [ ] `weather_hourly` full-year coverage for 2021 + 2024 (ISD) delivered to 02 and 08 by Day 1 evening.
- [ ] No table anywhere carries `coord_source='tamu_xlsx'`.
