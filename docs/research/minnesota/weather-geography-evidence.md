# Minnesota weather and geography evidence intake

## Boundary and handling rules

This is an intake inventory for **Minnesota, county-resolved analysis**.  Preserve
the source record's time, location, units, quality flags, retrieval URL, and
retrieval time; use UTC timestamps in derived records and EPSG:4326 geometry.
The current Flux product contract is Texas-first, so this inventory is not a
claim that Minnesota has been loaded into `weather_hourly`, joined to topology,
or is model-ready.  It identifies a reproducible evidence path if that scope is
selected later.

`county_fips` is the analysis join key: spatially join an observation point to
the versioned county polygon at ingest, retain `station_id`/coordinates, and do
not replace the original point with a county centroid.  For a county-hour, keep
the aggregation rule and contributing-station count.  A missing reading stays
missing; it is never a zero-weather value.

## Evidence inventory

| Evidence | Coverage and resolution | Fields/units to retain | Access, identity, and intended join | Limits |
| --- | --- | --- | --- | --- |
| [NOAA NCEI Integrated Surface Database (ISD)](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database) | Station observations, hourly/synoptic (some sub-hourly), 1901–present; station periods have gaps. Filter the station inventory to Minnesota and the selected time window—do not assert a station count until the inventory is queried. | Observation timestamp; station identifiers; latitude/longitude/elevation; air temperature °C; wind direction degrees, wind speed and gust m/s; precipitation depth mm; source/quality flags. Preserve the raw reported interval for precipitation. | Public HTTPS/data-access service. Use the [station-history and ISD inventory](https://www.ncei.noaa.gov/products/land-based-station/station-histories) to version the station metadata, then point-in-polygon to `county_fips`; aggregate to an hour only after quality filtering. Record source URL and content date because NCEI notes ongoing cloud migration. | Observations are point measurements, not county-wide truth. Field availability and cadence differ by station; no interpolation, representativeness, or ice-accretion claim follows from ISD alone. NCEI provides public access but this inventory makes no blanket licence claim—retain source attribution and recheck terms at acquisition. |
| [NOAA GHCN-Daily documentation](https://www.ncei.noaa.gov/pub/data/cdo/documentation/GHCND_documentation.pdf) | Station-day climate records; suitable for daily cross-checks, not hourly features. Station metadata includes identifier, latitude, longitude, elevation and date. | `TMAX`/`TMIN` in °C; `PRCP`, `SNOW`, `SNWD` in mm; station/date; measurement, quality, and source flags. Normalize only after preserving the delivered units and flags. | Public NCEI delivery. Join `station_id + date`; map the station point to the same versioned county polygon. Use to validate daily ISD aggregates or characterize snow/cold conditions, not to backfill hourly observations. | Daily observation time may be local and precipitation can be a multi-day total; records with failed quality flags must not become features. The documentation flags restrictions for some non-U.S. source data; this intake is restricted to Minnesota stations, but provenance must still be retained. |
| [NCEI Storm Events bulk data and format](https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/) | Event-level start/end, location and event type; county, forecast-zone, or marine geography varies by record. | Event ID, begin/end local time and time-zone offset, event type, magnitude/unit, `cz_type`, `cz_name`, FIPS where supplied, begin/end coordinates, narrative, and source vintage. | Public bulk CSV. Convert supplied times to UTC; use county FIPS only when the record is explicitly county-coded. For a zone-coded event, retain the zone key and use an independently versioned zone-to-county crosswalk rather than silently expanding it to each county. | This is weather-event context, **not an outage label or replay**. A weather event may not be represented as an outage replay without independently sourced, observed outage outcomes keyed to the same geography and time. Narratives and damage fields do not establish customers out. |
| [Minnesota county boundaries](https://gisdata.mn.gov/dataset/bdry-counties) (MnDOT/MnGeo) | 87 county polygons; the published ArcGIS item reports NAD 1983 UTM Zone 15N and a 2024-09-10 update. | Source feature ID, county name/code fields, geometry, CRS, dataset version/update date and download checksum. Transform a copy to EPSG:4326 for the Flux contract. | State-managed downloadable/service layer. Make `state_fips + county_code` the canonical five-digit `county_fips`; validate 27 + three digits, uniqueness, and 87 rows before spatial joins. | Administrative boundaries are the aggregation support, not utility territory, line footprint, service area, or an outage observation. Check the release's metadata/licence before redistribution; do not merge geometries across vintages. |
| [USGS 3DEP 1/3 arc-second DEM](https://data.usgs.gov/datacatalog/data/USGS%3A3a81321b-c153-416f-98b7-cc8e5f0e17c3) | CONUS bare-earth elevation raster at approximately 10 m (1/3 arc-second), NAD83 horizontal reference and NAVD88 vertical reference; current and historical tiles exist. | Tile/version, acquisition or product date, EPSG/datum, elevation m, nodata mask, and the point or zonal-statistic method. | Public-domain USGS download/service. Join sampled elevation to a station, site, or geometry by coordinates; for county summaries retain the raster version and statistic. | Elevation is terrain context only—not flood depth, icing, wind exposure, line clearance, or a site-suitability conclusion. Its continuously updated current folder means an analysis must pin the dated artifact. |
| [USGS 3D Hydrography Program (3DHP)](https://www.usgs.gov/3d-hydrography-program/access-3dhp-data-products) | National hydrography as downloadable data and web services; services update quarterly and annual downloads are versioned. | Feature geometry/type, source version, `reachcode`/Mainstem ID where present, and spatial relationship (intersects/nearest/within distance). | Public/open federal data. Spatially join water features to county polygons or sites; retain the hydro feature identifier rather than converting it to a binary county flag. | Do not use it for site-specific regulatory determinations or infer flood risk/water availability. USGS notes legacy NHD/WBD/NHDPlus HR are no longer maintained; prefer the current 3DHP release and pin its version. |
| [NWS API](https://www.weather.gov/documentation/services-web-api) | Live forecast/alert/observation service. Forecast grids are about 2.5 km and a point lookup returns a WFO/grid mapping; hourly forecasts cover roughly the next seven days. | Request time, point coordinates, WFO/grid X/Y, valid time, issuance/update time, forecast values/units, alert ID and geometry. | Free/open federal API; send an identifying `User-Agent`. Resolve each location through `/points/{lat},{lon}` at refresh time, then retain the returned grid identity and raw response snapshot. | Forecasts and active alerts are prospective context, not historical observations and not outcomes. Grid/WFO mappings can change; never use current API output to reconstruct a past weather event or outage. |

## Minimum intake acceptance checks

1. Pin a source version or retrieval timestamp and checksum; retain raw artefacts outside Git.
2. Reject records outside Minnesota geometry, invalid coordinates, impossible timestamps, duplicate
   source keys, and weather values that fail source quality rules. Log rather than impute rejected data.
3. Test every spatial join against the pinned county vintage; retain unmatched stations/events for
   diagnosis. Do not join event-zone names by text alone.
4. Publish coverage diagnostics by `county_fips`, UTC hour/day, station count, missingness, and
   source vintage before any downstream feature calculation.
5. Keep observed-outage evidence in a separately sourced outcome table. Without that independent
   time-and-geography match, the only valid statement is that weather/geographic conditions were
   observed or forecast—not that an outage occurred or was replayed.

## Verification performed

On 2026-09-05, the cited NCEI ISD, MnGeo county-boundary, and USGS 3DEP pages returned HTTP
success responses.  The source pages/documentation were checked for field scope, cadence,
coordinate/units, access path, and stated caveats; no dataset was downloaded or coverage count
was inferred in this issue.
