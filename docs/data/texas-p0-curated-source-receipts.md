# Texas P0 bounded public-source receipts

This receipt set records seven public source families actually retrieved and
validated on 2026-09-06. It is legacy Texas data-intake evidence only; it does
not change the Minnesota demo authority, create a real ERCOT topology, or make
an untracked database artifact available in a fresh clone.

| Source | Evidence | Validation |
| --- | --- | --- |
| Census TIGER/Line 2024 counties | [`texas-tiger-2024.json`](../../data/sources/texas-tiger-2024.json) | `load_counties` loaded 254 Texas counties and transformed geometry to EPSG:4326. |
| FEMA NRI v1.20 counties | [`texas-nri-v1.20.json`](../../data/sources/texas-nri-v1.20.json) | `load_nri` loaded 254 Texas county rows, with no missing population or NRI score. |
| PUDL EIA-860 v2026.2.0 | [`texas-pudl-eia860-v2026.2.0.json`](../../data/sources/texas-pudl-eia860-v2026.2.0.json) | `load_eia860_plants` loaded 1,584 Texas plants and 628,701 generator-history rows. |
| EIA-930 2021 H1 and 2024 H2 | [`texas-eia930-2021-2024.json`](../../data/sources/texas-eia930-2021-2024.json) | `load_eia930` loaded 35,040 rows across four declared BAs. |
| NOAA Storm Events 2021 and 2024 | [`texas-noaa-storm-events-2021-2024.json`](../../data/sources/texas-noaa-storm-events-2021-2024.json) | `load_storm_events` loaded 10,355 qualified expanded rows; 22 unsupported 2021 legacy-zone rows are retained in the receipt. |
| NWS bp16ap26 zone-to-county crosswalk | [`texas-nws-zone-county-bp16ap26.json`](../../data/sources/texas-nws-zone-county-bp16ap26.json) | 308 TX rows cover 298 zones and all 254 county FIPS. |
| NTAD military bases FY2024 | [`texas-ntad-military-bases-fy2024.json`](../../data/sources/texas-ntad-military-bases-fy2024.json) | `load_dod` loaded 21 active, at-least-1-km² facilities from 32 TX source features. |
| EAGLE-I 2021 and 2024 annual outages | [`texas-eaglei-2021-2024.json`](../../data/sources/texas-eaglei-2021-2024.json) | UTC streaming intake loaded 2,443,041 (2021) and 2,921,200 (2024) TX observations; Uri and Beryl fixed-window coverage and blank targets are recorded. |

The source URLs, versions, licenses, raw paths, byte counts, SHA-256 values,
coverage, units, and uncertainty boundaries remain in the inventory and linked
receipts. Raw archives/Parquet and temporary DuckDB validation outputs are
gitignored.

[`texas-hrrr-manifest-feasibility.json`](../../data/sources/texas-hrrr-manifest-feasibility.json)
records a reproducible rule for the fixed Uri and Beryl contract windows and
four byte-range probes of official archive objects. It is not an ingestion
receipt: this checkout has no HRRR county-grid index, loader, or aggregation
artifact to validate `weather_hourly`.

## Reproduce the bounded intake

```sh
mkdir -p data/raw/tiger/2024 data/raw/nri/v1.20 data/raw/pudl/v2026.2.0
curl --fail --location --output data/raw/tiger/2024/tl_2024_us_county.zip \
  https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip
curl --fail --location --output data/raw/nri/v1.20/NRI_Table_Counties.zip \
  https://www.fema.gov/about/reports-and-data/openfema/nri/v120/NRI_Table_Counties.zip
curl --fail --location --output data/raw/pudl/v2026.2.0/out_eia__yearly_plants.parquet \
  https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/v2026.2.0/out_eia__yearly_plants.parquet
curl --fail --location --output data/raw/pudl/v2026.2.0/out_eia__yearly_generators.parquet \
  https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/v2026.2.0/out_eia__yearly_generators.parquet
mkdir -p data/raw/eia930/2021_h1 data/raw/eia930/2024_h2 data/raw/storm_events/{2021,2024} data/raw/nws_zone_county/{bp10nv20,bp05mr24} data/raw/ntad_military_bases/fy2024
curl --fail --location --output data/raw/eia930/2021_h1/EIA930_BALANCE_2021_Jan_Jun.csv https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2021_Jan_Jun.csv
curl --fail --location --output data/raw/eia930/2024_h2/EIA930_BALANCE_2024_Jul_Dec.csv https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2024_Jul_Dec.csv
curl --fail --location --output data/raw/storm_events/2021/StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz
curl --fail --location --output data/raw/storm_events/2024/StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz
curl --fail --location --output data/raw/nws_zone_county/bp10nv20/bp10nv20.dbx 'https://web.archive.org/web/20201019003757id_/https://www.weather.gov/source/gis/Shapefiles/County/bp10nv20.dbx'
curl --fail --location --output data/raw/nws_zone_county/bp05mr24/bp05mr24.dbx 'https://web.archive.org/web/20240928223402id_/https://www.weather.gov/source/gis/Shapefiles/County/bp05mr24.dbx'
curl --fail --location --output data/raw/ntad_military_bases/fy2024/texas.geojson 'https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Military_Bases/FeatureServer/0/query?where=stateNameCode%3D%27TX%27&outFields=*&returnGeometry=true&outSR=4326&f=geojson'
uv run --extra dev python scripts/validate_texas_p0_inventory.py --raw-root data/raw
```

HRRR remains unavailable despite a reproducible fixed-window manifest because
this checkout lacks the county-grid index, loader, and aggregation transform.
Storm Events selects historical NWS crosswalk editions by pinned effective
interval and fails closed outside their verified windows; archive hosting is
recorded in the receipt.
No successful source receipt authorizes a synthetic-to-real connectivity claim.
