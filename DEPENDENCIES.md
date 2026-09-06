# Flux dependencies and environment evidence

Recorded 2026-09-05 on the laptop
(`/Users/joshua/buckeye-swarm/flux`). This is setup evidence only; no product
code exists yet.

## Completed setup

- `uv sync --frozen --extra dev` completed with the existing lockfile unchanged.
- `pnpm --dir web install --frozen-lockfile` completed with the existing
  lockfile unchanged.
- The development extras are installed.

## Toolchain

| Tool | Version | Notes |
|---|---|---|
| uv | 0.11.16 | manages the Python env; `uv sync` |
| Python | 3.12.13 (uv-managed) | pinned `>=3.12,<3.13` in `pyproject.toml` |
| Node / pnpm | 26.0.0 / present | `web/` |
| libomp (brew) | installed | required by LightGBM on macOS arm64 |
| psql | present | only if PostGIS is wanted; DuckDB is the default |

## Python (`pyproject.toml`, development extras installed)

Key imports pass. A DuckDB query passes, and a tiny LightGBM fit passes.

- storage / geo: duckdb 1.5.5, pyarrow, polars, pandas, geopandas, shapely, pyproj, h3, networkx, xarray, netcdf4, cfgrib, herbie-data, gridstatus
- physics: pandapower 3.5.3, lightsim2grid, pypsa, scipy, **matpower** (bundles `case_ACTIVSg2000.m`, 10k, 25k, 70k), **matpowercaseframes** (required by pandapower's `.m` importer)
- ML / causal: lightgbm 4.7.0, scikit-learn, dowhy, econml, pgmpy
- copilot: fastapi, uvicorn, sse-starlette, anthropic 1.4.0, pydantic, pypdf, rank-bm25, python-dotenv
- installed extra: `dev` (pytest, ruff, jupyter); `stretch` (grid2op) and
  `gnn` (torch, torch-geometric) remain optional

Proof the twin dependency chain works end to end:

```
from pandapower.converter.matpower import from_mpc   # NOT pandapower.converter.from_mpc
net = from_mpc(".venv/.../matpower/data/case_ACTIVSg2000.m", f_hz=60)
# 2000 buses, 2359 lines, 847 impedance branches (transformers land in net.impedance, not net.trafo),
# 484 gen + 59 sgen + 1 ext_grid, 1125 loads, 67,109.21 MW; pp.rundcpp() passes.
# lightsim2grid CANNOT load this case ("Unsupported element (Impedance)"): stretch-only.
```

## Web (`web/package.json`, pnpm installed)

react 19.2, deck.gl 9.3.11 (+ core, layers, geo-layers, aggregation-layers, mapbox overlay), maplibre-gl 6.7, react-map-gl 8.1, h3-js 4.5, apache-arrow 21, @tanstack/react-query 5, zustand 5, d3-scale; vite 8.2, @vitejs/plugin-react 6, typescript 5.9 — versions match `docs/specs/06-frontend.md`.

## Data sources — verified status

| Source | Status | Location / URL |
|---|---|---|
| ACTIVSg2000 CURRENT version (TAMU) | **downloaded** | `data/raw/activsg2000_current/` from `https://drive.usercontent.google.com/download?id=1tC-ofbw1EE46hoZeSfiBAWnSAhG0SmVu&export=download&confirm=t` (125 MB). Bus lat/lon = `ACTIVSg2000.aux` Substation/Bus blocks; maps all 2,000 pip-case bus ids (fact-check 01-02, 0 kV mismatches). |
| ACTIVSg2000 June-2016 bundle (PREVIOUS version) | downloaded, **do not use for coordinates** | `data/raw/activsg2000/…/Texas2000_June2016.*` — 2,007 buses / 49,776 MW; only 98 of 2,000 bus numbers match the pip case. Kept for reference only. |
| ACTIVSg2000 electrical case | **installed** | pip `matpower` package data dir |
| EAGLE-I outages 2014–2025 | **open, not downloaded** (~1.1–1.4 GB per year) | figshare article 24237376; e.g. 2021 `https://ndownloader.figshare.com/files/42547891`, 2025 `https://ndownloader.figshare.com/files/62164877`, MCC.csv `https://ndownloader.figshare.com/files/42547708`. No Globus needed. |
| EIA-860 2024 | open (200) | `https://www.eia.gov/electricity/data/eia860/xls/eia8602024.zip` |
| PUDL nightly parquet (EIA-860 plants) | open (200) | `https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/core_eia860__scd_plants.parquet` |
| EIA-930 hourly BA demand | open (200) | `https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2021_Jan_Jun.csv` (half-year files) |
| NOAA Storm Events | open (200) | `https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/` |
| HRRR on AWS | open (200) | `https://noaa-hrrr-bdp-pds.s3.amazonaws.com/` via herbie |
| Census TIGER counties 2024 | open (200) | `https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip` |
| Census Gazetteer places (geocode fallback) | open (200) | `https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip` |
| HIFLD transmission lines / hospitals (archived) | gated: free ICPSR/DataLumos account, browser download (Cloudflare) | DataLumos 240591 (lines), 239108 (hospitals); OSM Texas PBF via Geofabrik is the open fallback |
| FEMA National Risk Index county table v1.20 | loaded from FEMA official ArcGIS service; bulk OpenFEMA ZIP is WAF-sensitive | state-filtered official service query recorded in `scripts/data/fetch_p0.py` |
| DoD installation boundaries (NTAD Military Bases) | open (GeoJSON query verified, CC0) | `https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Military_Bases/FeatureServer/0/query?where=stateNameCode%3D%27TX%27&outFields=*&returnGeometry=true&outSR=4326&f=geojson` |
| OpenFreeMap tiles (basemap) | open (200) | `https://tiles.openfreemap.org/styles/liberty` |
| Microsoft GridSFM, PyPSA-USA | repos reachable | stretch only |

`scripts/data/download.sh` is specified in `docs/specs/01-data-ingest.md`; it has
not been run for the large files (EAGLE-I, HRRR).
