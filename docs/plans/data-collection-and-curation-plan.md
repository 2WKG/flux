# Data Collection & Curation — Execution Plan (spec 01 lane)

*Owner: data lane · Written 2026-09-05 · Source of truth: `docs/specs/01-data-ingest.md` and
`docs/specs/00-overview.md` §2 (on `main`). This plan sequences that spec into work, adds the
technical how-to the spec leaves implicit, and records the issues found while reading every
other spec for what they expect from us.*

Tags follow the project convention: `[UNVERIFIED]` = not confirmed by us; `[VERIFY-DAY0]` =
must be checked before kickoff; `[DECISION]` = needs a human call.

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
- Geography + tables: Google Drive zip, 2.1 MB,
  `https://drive.google.com/uc?export=download&id=1tOIK_RVQaZZDo_oIi75bVdPsAlQ7J1l9` → `data/raw/activsg2000/`.
  Small enough that Drive serves it without the virus-scan interstitial; plain `curl -L`.
  Unpacks to `Texas 2000 - June 2016 Synthetic Case/Texas2000_June2016.{xlsx,AUX,m,RAW,EPC,pwb,pwd}`.
- **The xlsx is the source of record.** Sheets: `Substations` (Substation Number, Name, Area,
  Latitude, Longitude, Max kV), `Buses` (Bus Number, Bus Name, Area, Substation Number, Nominal kV),
  `Lines` (From/To Bus, Circuit, R pu, X pu, B pu, MVA Limit), `Transformers`, `Loads` (Bus, MW, Mvar),
  `Generators`, `Shunts`, `Areas`. `buses.lon/lat` = `Buses ⋈ Substations` on `Substation Number`.
  Tool: `pandas.read_excel(sheet_name=None)` (needs `openpyxl` — `[VERIFY-DAY0]` it is in the
  resolved lockfile; pandas does not pull it transitively).
- Electrical case for the twin: `case_ACTIVSg2000.m` bundled in the `matpower` pip package
  (`.venv/lib/python3.12/site-packages/matpower/data/`). Copy to `data/raw/activsg2000/` so the
  raw dir is the record. Load with `from pandapower.converter.matpower import from_mpc`
  (that exact import path; `pandapower.converter.from_mpc` does not exist), `f_hz=60`
  (default is 50). Requires `matpowercaseframes` (installed). Expected counts: 2000 / 2359 / 847
  transformers (import as lines) / 544 / 1125 / 67,109 MW.
- Gotchas: (a) `[UNVERIFIED]` that bus numbers agree between the June-2016 xlsx and the pip `.m`
  — acceptance #2 spot-checks 20 buses on `base_kv`; do this *first*, it is a 5-minute test that
  decides whether the whole geography path works. (b) `gens.fuel` from `mpc.genfuel` joined by
  `GEN_BUS` + row order; the xlsx `Generators` sheet is the fallback. (c) The `.AUX` also has
  coordinates (spec 03 assumes we read them from there — see §9, I-4). (d) Fallback geocoder:
  strip the numeric suffix from `Bus Name` (`ODESSA 2 0` → `ODESSA`) and fuzzy-match against the
  Census 2024 place gazetteer (`INTPTLAT`, `INTPTLONG`, `USPS='TX'`) with `rapidfuzz` ≥ 90 —
  **`rapidfuzz` is not in `pyproject.toml`** `[VERIFY-DAY0]`. A manual override CSV
  `bus_coords_manual.csv (bus_id, lon, lat)` beats both.
- License: TAMU, free use, cite Birchfield et al. 2017 (10.1109/TPWRS.2016.2616385). Not CEII.

**S13 — Census TIGER 2024 counties** → `counties`
- `https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip`, 83.9 MB, public domain.
- `geopandas.read_file("zip://…/tl_2024_us_county.zip")`; filter `STATEFP == '48'` for P0.
- Gotcha: TIGER is **EPSG:4269 (NAD83)**. Reproject to 4326 explicitly (`.to_crs(4326)`) even though
  the shift is centimetres — every other layer is 4326 and a mixed-CRS sjoin fails silently
  in some GeoPandas versions. `county_fips = STATEFP + COUNTYFP` as a 5-char **string**; never let
  it become an int anywhere (leading zeros matter nationally even if not for Texas).

**S9 — FEMA National Risk Index v1.20 (county)** → `hazard_static.nri_score`, `counties.pop`, helper `nri_hazards`
- `https://www.fema.gov/about/reports-and-data/openfema/nri/v120/NRI_Table_Counties.zip`, 25 MB.
  Use this OpenFEMA host; `hazards.fema.gov` 403s.
- Columns: `STCOFIPS, POPULATION, RISK_SCORE, WFIR_RISKS, ISTM_RISKS, SWND_RISKS, HRCN_RISKS, WNTW_RISKS, EAL_VALT`.
  Spec 07 also wants `RESL_SCORE` `[UNVERIFIED present]` — grab it if it exists, it costs nothing.
- Gotcha: read `STCOFIPS` as `dtype=str`.

**S3 — EIA-860 plants/generators via PUDL** → helper `eia_plants`, `gens.eia_plant_id`, `site_candidates`
- Anonymous S3, CC-BY-4.0:
  `https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/core_eia860__scd_plants.parquet` (3.3 MB),
  `…/core_eia860__scd_generators.parquet` (9.3 MB); prefer `…/out_eia__yearly_plants.parquet` and
  `…/out_eia__yearly_generators.parquet` (denormalised, have lat/lon, fuel, capacity, retirement dates).
- Gotcha: `nightly/` can change schema without notice. If a column is missing, pin
  `…/pudl.catalyst.coop/v2026.2.0/<table>.parquet` `[UNVERIFIED exact version string]`. Read with
  `pyarrow`/`polars`, filter `state == 'TX'`, latest `report_date` per plant.
- Raw fallback: `https://www.eia.gov/electricity/data/eia860/xls/eia8602024.zip`.

**S4 — EIA-930 hourly BA demand** → `ba_load_hourly`
- Pattern `https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_{YYYY}_{Jan_Jun|Jul_Dec}.csv`, ~43 MB each.
  P0 files: `2021_Jan_Jun` (Uri), `2024_Jul_Dec` (Beryl, Helene). Reference table
  `https://www.eia.gov/electricity/930-content/EIA930_Reference_Tables.xlsx`.
- Use `"Demand (MW) (Adjusted)"` falling back to `"Demand (MW)"`; `ts` = `"UTC Time at End of Hour"`.
  Keep `ERCO, EPE, SWPP, MISO`. Numbers have thousands separators — `thousands=','` in `read_csv`.
- Gotcha: adjusted demand during Uri contains imputed hours; keep them, but flag rows where raw
  `Demand (MW)` is NULL in a helper column. Acceptance #6 checks 2021-02-15 07:00 UTC < 50 GW.

**S5 — EAGLE-I county outages** → `eaglei_outages`, helper `county_customers`
- **Open on figshare, CC BY 4.0, no Globus** (the pitch's #1 risk is void). Article 24237376.
  Direct files: 2021 `https://ndownloader.figshare.com/files/42547891` (1,141 MB),
  2024 `…/53581661` (1,445 MB), `MCC.csv` `…/42547708` (40 KB), `coverage_history.csv` `…/42547714`.
  P1 years: 2014 `42547717`, 2015 `42547822`, 2016 `42547825`, 2017 `42547828`, 2018 `42547879`,
  2019 `42547885`, 2020 `42547894`, 2022 `42547897`, 2023 `44574907`, 2025 `62164877`.
- Pull with `curl -L -C - -o` — the GET 302s to a presigned S3 URL that expires in ~10 s, so
  **no HEAD, no `wget --spider`**, and resume support matters on hackathon Wi-Fi.
  **Download these the night before** (§5, step −1). 2.6 GB for P0 alone.
- Columns: `fips_code, county, state, customers_out, run_start_time`; 2024+ adds `total_customers`.
  15-min cadence. Texas 2021 ≈ 8.9 M rows (254 × 35,040) → ~35 MB compressed.
- Load: never into pandas. DuckDB: `read_csv_auto(path) WHERE state='Texas'` streams in one pass.
  Postgres: `COPY` into unlogged staging, filter on insert. Either way keep the raw CSV; never re-download.
- Gotchas: `fips_code` may parse as int — cast to 5-char string. `run_start_time` timezone
  `[VERIFY-DAY0]` (assumed UTC; if it is local, the Uri peak lands 6 h off and acceptance #5 catches it).
  `coverage_history.csv` matters: spec 02 excludes state-years with < 60 % coverage.

**S6 — NOAA Storm Events** → `storm_events`
- Directory `https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/`. Filenames carry a
  publish suffix that rotates (`StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz`), so
  `download.sh` lists the directory and greps `d{YEAR}_`. ~10 MB each gz.
- County FIPS = `STATE_FIPS*1000 + CZ_FIPS` **only when `CZ_TYPE='C'`**. Winter storms are mostly
  zone rows (`CZ_TYPE='Z'`) and need zone→county expansion: NWS correlation file
  `https://www.weather.gov/source/gis/Shapefiles/WSOM/bp05mr24.dbx` `[UNVERIFIED filename; pattern bpDDmmYY.dbx]`;
  fallback = zone shapefile `z_05mr24.zip` `[UNVERIFIED]` + sjoin of county centroids.
  Acceptance #8 needs ≥ 150 Texas winter rows for Feb 2021 *after* expansion — if the
  correlation file is unreachable this is where we lose time; test the URL on Day 0.

**S7 — HRRR weather (county-hour)** → `weather_hourly` — *the expensive one, 2.5 h*
- AWS Open Data `s3://noaa-hrrr-bdp-pds`, anonymous. Keys `hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcf00.grib2`
  (~145 MB/hour full). Use **`herbie`** with byte-range subsetting via the `.idx` files: four fields
  ≈ 2–3 MB/hour. Example:
  ```python
  from herbie import Herbie
  H = Herbie("2021-02-15 06:00", model="hrrr", product="sfc", fxx=0)
  ds = H.xarray(":(UGRD|VGRD):10 m above ground|:GUST:surface|:TMP:2 m above ground")
  ```
  (`search=` regex in current herbie; older releases call it `searchString=`.)
  Precip: `APCP:surface` 1-h accumulation from `fxx=1` (not in `f00`). Ice: `FRZR:surface`
  `[UNVERIFIED present in Feb-2021 sfc files]`; fallback `ice_mm = precip_mm where temp_c <= 0`.
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
  `forecast_72h` = latest run `fxx=1..48`, hours 49–72 copy hour 48 with a `stale` flag.
  P0 volume: ~240 + 96 h ≈ 340 hours × 3 MB ≈ 1 GB, ~30–60 min wall time depending on S3 throughput.
- **Full-year weather is needed by specs 02 and 08 and is not in P0** — see §9, I-1/I-2, and the
  ISD plan under P1 below.

**S14 — DoD installation boundaries** → `critical_loads(kind='dod')`
- NTAD Military Bases, CC0, ArcGIS FeatureServer, GeoJSON:
  `https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Military_Bases/FeatureServer/0/query?where=stateNameCode%3D%27TX%27&outFields=*&returnGeometry=true&outSR=4326&f=geojson`.
  Fields `siteName, siteReportingComponent, siteOperationalStatus, stateNameCode, isJointBase`.
  Max 2,000 records/page; TX fits in one, CONUS needs `resultOffset` paging.
- Keep `siteOperationalStatus='Active'` and area > 1 km²; `lon/lat` = polygon centroid
  (`.to_crs(3083).centroid.to_crs(4326)` — compute centroids in a projected CRS, Texas Albers 3083,
  or GeoPandas warns and the result is subtly wrong). Acceptance #9 needs a row matching
  `Cavazos|Hood` with a non-NULL `bus_id`.

**S8 — NWS alerts** → helper `nws_alerts` (forecast_72h)
- `https://api.weather.gov/alerts/active?area=TX`, GeoJSON. **Requires a `User-Agent`** header
  (`(flux-grid-twin, <team email>)`); undocumented rate limit, retry after 5 s. Snapshot to
  `data/raw/nws/alerts_TX_<UTC hour>.geojson`.

**S17 — County → balancing authority** → `counties.ba_code` (via `buses.ba_code`)
- Hand-curated dict in `pipelines/ba_map.py`. Default `ERCO`; El Paso/Hudspeth/Culberson → `EPE`;
  ~33 Panhandle/South Plains counties → `SWPP`; ~23 East Texas counties → `MISO`. `[UNVERIFIED
  boundaries; split counties by majority]`. Low blast radius — only `ERCO` scaling touches physics.

**Scenarios seed** → `scenarios` (4 rows; see §9, I-5 for the Uri end-time conflict).

### P1 (do after Gate B, or in the background on Day 1)

**S7b — NOAA ISD station hourlies** → `weather_hourly` for **full years** (the fix for I-1/I-2)
- Station list `https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv` (filter `STATE='TX'`,
  active through the year) → ~200 stations. Files
  `https://www.ncei.noaa.gov/data/global-hourly/access/{YEAR}/{USAF}{WBAN}.csv`, ~2–5 MB each,
  ~1 GB per year total. Open, no account.
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
- `https://www.eia.gov/electricity/data/eia861/archive/zip/f861{YYYY}.zip`, ~4 MB. Inside:
  `Reliability_{YYYY}.xlsx`, `Service_Territory_{YYYY}.xlsx` `[UNVERIFIED inner sheet names]`.
  Spec 07 needs 2018–2023 for the SAIDI trend.

**S10 — USFS Wildfire Hazard Potential** → `hazard_static.wildfire_hazard`
- `https://www.fs.usda.gov/rds/archive/products/RDS-2015-0047-4/RDS-2015-0047-4_Data.zip`, 368 MB,
  270 m GeoTIFF. Zonal mean per county needs **`rasterio` + `rasterstats` — not in `pyproject.toml`**.
  P0 shortcut: leave NULL and let 02/04 use `nri_hazards.WFIR_RISKS`.

**S11 — USGS NSHM 2023 PGA** → `hazard_static.seismic_pga`
- ScienceBase, 59 MB, gridded PGA 2 %-in-50-yr site class BC `[UNVERIFIED inner format]`.
  County mean; also per-site for spec 04's S3 criterion.

**S12 — Real transmission geometry overlay** → helpers `real_lines`, `real_substations`
- HIFLD archived lines: DataLumos 240591 — **gated** (Cloudflare + free ICPSR account, browser only).
  Drop into `data/raw/hifld/`. Spec 08 wants this for owner attribution (≥ 50 % match on ≥ 230 kV).
- Scriptable fallback: Geofabrik `texas-latest.osm.pbf` (684 MB) →
  `osmium tags-filter … nwr/power=line,minor_line,cable,substation nwr/amenity=hospital nwr/man_made=water_works`
  (**`osmium` CLI is a system package**, `apt install osmium-tool`) → `pyosmium` or `osmnx` to read.
  Overlay only; **never joined into `lines`/`buses`**.

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
  activsg.py       xlsx + .m → buses, lines, gens, loads; to_pandapower() pickle for spec 03
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
2. `[VERIFY-DAY0]` checklist:
   - `uv run python -c "import duckdb, pandapower, lightgbm, geopandas, herbie, cfgrib"` on every data-lane laptop.
   - `openpyxl`, `rapidfuzz`, `rasterio`/`rasterstats` presence; add to `pyproject.toml` if missing (ask first — A2 says one root env).
   - Storm Events zone→county correlation file URL resolves.
   - EAGLE-I `run_start_time` timezone (open the 2021 file, find 2021-02-15, compare the Texas peak hour against the known ~07:00 UTC load-shed).
   - Spot-check 20 bus numbers xlsx vs `.m` on `base_kv`.
   - `herbie` can fetch one Uri hour with the field regex above.
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
2. `buses/lines/gens/loads` from the xlsx. Line `length_km` = haversine × 1.15 when the case has
   none; `geom_wkb` = straight `LINESTRING`. Transformers kept in `lines` with `is_transformer=TRUE`,
   `length_km=0`. `[1.0 h]`
3. **J1 bus→county** (§6). `[0.3 h]`
4. **J2 county→BA**, `buses.ba_code` inherits. `[0.2 h]`
5. `to_pandapower()` → `data/parquet/twin_ACTIVSg2000.p`; assert `rundcpp` converges, total load =
   `SUM(loads.p_mw_nominal)` ± 0.1 %. `[0.3 h]`
6. `scenarios` seed. `export_parquet()`. `[0.2 h]`

### Gate A — 12:00 — every lane runs on the fixture DB.

### Step 2 — 13:00–15:00 · Load, weather, events, critical loads · **Gate: `weather_hourly` covers Uri for 254 counties**
1. `ba_load_hourly` from EIA-930 2021 H1 + 2024 H2. Check the 07:00 UTC Uri hour. `[0.4 h]`
2. `eaglei_outages` 2021 + 2024 TX, `county_customers` from MCC + 2024 `total_customers`. Print the
   Uri peak; it must be 4.0–4.8 M. `[0.6 h]`
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
| A2 | 2000 buses, 3206 lines (2359 + 847), 544 gens, 1125 loads, 67,109 MW ± 1 % | wrong sheet, dropped transformers |
| A2 | every bus inside TX bbox (−106.7..−93.5, 25.8..36.6) | lat/lon swapped |
| A2 | 20 random buses agree on `base_kv` xlsx vs `.m` | case-version mismatch |
| A3 | 100 % `lon/lat` non-NULL, ≥ 99 % `county_fips` | broken join |
| A5 | Uri 15-min statewide `SUM(customers_out)` max in 4.0–4.8 M | timezone, state filter, dupes |
| A6 | ERCO 2021-02-15 07:00 UTC demand < 50 GW; ≤ 0.5 % NULL H1-2021 | wrong demand column, local-time parse |
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
| Excel | `openpyxl` | `[VERIFY-DAY0]` |
| Spatial | `geopandas`, `shapely`, `pyproj`; `scipy.spatial.cKDTree` / `sklearn.neighbors.BallTree` | installed |
| GRIB | `herbie-data`, `xarray`, `cfgrib` + **ecCodes system lib** | `[VERIFY-DAY0]` |
| Raster zonal (P1) | `rasterio`, `rasterstats` | **missing** |
| Fuzzy match (fallback) | `rapidfuzz` | **missing** |
| OSM (P1) | `osmium-tool` CLI + `pyosmium` | **missing** |
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

**I-4 · Bus coordinates source.** Spec 03 says they come from the `.AUX`; spec 01 says the xlsx
`Substations` sheet, AUX not needed. We use the xlsx; 03 reads `buses` either way, so this is
cosmetic — but say so.

**I-5 · Uri window end.** `00` §2.3: `ts_end` 2021-02-20T23:00Z. Spec 01 seed and spec 03's "168 h"
imply 2021-02-20T00:00Z; spec 02 expects 28 six-hour windows (= 7 days). **Propose 00:00Z
(168 h)** and amend `00`. Our HRRR pull covers 02-11..02-21 regardless.

**I-6 · Site `bus_id` kV threshold.** Spec 01: nearest bus ≥ 230 kV. Spec 04: ≥ 138 kV within
40 km, else `unconnected`. Different thresholds produce different candidate sets. **Propose 04's
rule** (it owns the semantics) and record the distance so 04 can re-filter.

**I-7 · Critical load → bus: same-county constraint?** Spec 03 says "≥ 115 kV within the same
county"; spec 01 says nearest ≥ 115 kV, no county constraint. Propose same-county first, fallback
nearest, `critical_load_bus_dist` records which.

**I-8 · Layers spec 04 needs that nobody downloads in 01** (tracts, NFHL, NHDPlus, PAD-US, 3DEP,
NWI). Agree owner and paths on Day 0.

**I-9 · Missing Python deps** (`openpyxl`?, `rapidfuzz`, `rasterio`, `rasterstats`, `pyosmium`, a
Postgres driver if chosen) and system deps (ecCodes, osmium-tool). A2 says one root env — add
via PR to `pyproject.toml`, not ad hoc installs.

**I-10 · HRRR `FRZR` availability** for Feb 2021 sfc files `[UNVERIFIED]`. Fallback defined; check
on Day 0 with one file so 02 knows which `ice_mm` they are getting.

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
| xlsx ↔ `.m` bus-number mismatch | Medium | No geography → no map | 5-min spot-check first thing; gazetteer + manual CSV fallback |
| Storm Events zone→county file unreachable | Medium | A8 fails, 02 loses features | Zone shapefile sjoin fallback; test URL Day 0 |
| Google Drive link changes behaviour | Low | S1 blocked | CSV mirror on GitHub (no coords) + gazetteer geocode |
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
- [ ] I-1 through I-8 raised with their owners and the resolution recorded in `00-overview.md` amendments.
- [ ] `weather_hourly` full-year coverage for 2021 + 2024 (ISD) delivered to 02 and 08 by Day 1 evening.
