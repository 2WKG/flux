# Minnesota primary-source and citation inventory

**Purpose.** This is an intake inventory for a Minnesota extension. It is a
source map, not a claim that a fully resolved Minnesota network model exists.
The public sources below support aggregate, county, utility-service-area, and
project-context claims. They do **not** make a public, electrically connected
transmission model available.

**Conventions.** URLs are direct publisher or primary-data links, accessed
2026-09-05. Keep source values with their published vintage and units; do not
silently substitute a map, county total, or balancing-authority total for a
facility or feeder measurement. `county_fips` is the five-character Census
`STATEFP + COUNTYFP` string (Minnesota prefix `27`), `utility_id_eia` is the
EIA utility identifier, and `ba_code` is the EIA balancing-authority code.
Geometry stored by Flux is EPSG:4326 WKB/lon-lat after an explicit reprojection.

## Decision summary

| Need | Recommended source of record | Usable join | What it can substantiate | Important boundary |
| --- | --- | --- | --- | --- |
| County geography | Census TIGER/Line 2024 counties | `county_fips` | Minnesota county map, area, spatial joins | Legal/statistical county geometry, not utility territory |
| Electric-service geography | MnGeo/PUC electric service areas | utility/service-area identifier; spatial overlap, then EIA utility ID crosswalk | Retail service-area and utility-context claims | Not a balancing-area map; overlap must be retained rather than forced to a single owner |
| Generators and capacity | EIA-860 annual files | `plant_id_eia`, generator ID, county/geocode | Facility-level nameplate, fuel, status, planned retirements | Annual snapshot; it is not dispatch or an electrical connectivity model |
| Aggregate system demand | EIA-930 | `ba_code`, UTC hour | Hourly MISO BA demand/generation/interchange context | BA total is multi-state and cannot be allocated to Minnesota counties without an explicit method |
| County sales/customers/reliability | EIA-861 | `utility_id_eia`, reporting year; county name needs Census crosswalk | Annual retail, customer and reported reliability context | County/service-territory reporting is not hourly load or outage truth |
| Weather/hazards | NOAA HRRR, NCEI ISD and Storm Events | UTC timestamp; station ID or gridded cell; county spatial join | Observed/forecast meteorology and documented event context | County values require stated aggregation; Storm Events is event reporting, not a weather time series |
| Outage truth | EAGLE-I public release | published FIPS and timestamp fields | County outage observations where release coverage permits | Coverage and `total_customers` vary by release/year; do not infer missing customers or utilities |
| Interventions | MN PUC dockets/IRP/IDP and project pages | docket + utility/project + geography/date | Filed or approved project and planning context | A filing or approval is not a built asset nor a quantitative impact estimate |

## Geography and service areas

### G1 — Census TIGER/Line counties

- **Publisher/version/date/license/access:** U.S. Census Bureau, TIGER/Line
  2024 county shapefile; public-domain U.S. Government work; open ZIP download:
  <https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip>.
- **Coverage/granularity/units:** U.S. county and county-equivalent polygons;
  filter `STATEFP == "27"`. Native geographic CRS is NAD83 (EPSG:4269);
  attributes include `STATEFP`, `COUNTYFP`, `GEOID`, `NAME`, `ALAND`, and
  `AWATER` (square metres).
- **Join keys:** `county_fips = GEOID`; use spatial intersection only after
  reprojection to EPSG:4326.
- **Expected claim use:** authoritative county names/boundaries, county-level
  aggregation, and a transparent geographic denominator for Minnesota claims.
- **Limitations:** County borders do not describe utility territories,
  balancing areas, topology, or a population distribution within the county.

### G2 — Minnesota electric utility service areas

- **Publisher/version/date/license/access:** Minnesota Geospatial Information
  Office (MnGeo), PUC-reviewed statewide electric utility service-area data;
  the agency landing page, metadata and download/viewing links are at
  <https://www.mngeo.state.mn.us/chouse/utilities.html>. Access is public;
  retain the dataset’s own metadata/vintage and terms with any derivative.
- **Coverage/granularity/units:** Minnesota retail electric service-area
  polygons and utility identifiers; polygon geometry, not lines or substations.
- **Join keys:** source utility identifier/name → an explicit, versioned
  crosswalk to EIA-861 `utility_id_eia`; county assignment is an area-weighted
  spatial overlay with TIGER `county_fips`, preserving one-to-many overlaps.
- **Expected claim use:** which retail utility service areas touch a place;
  provenance for utility-level EIA-861 facts and regulatory filings.
- **Limitations:** The publisher notes that boundary changes remain under
  review. It must not be treated as a single-utility county map, an electrical
  feeder map, or proof of customer shares.

### G3 — Census population and community denominators

- **Publisher/version/date/license/access:** U.S. Census Bureau, ACS 5-year
  Data Profiles API (use a pinned release, e.g. 2024 when available in a run);
  public access: <https://api.census.gov/data.html>. Example group metadata:
  <https://api.census.gov/data/2023/acs/acs5/profile/groups/DP05.json>.
- **Coverage/granularity/units:** annual release of five-year estimates by
  county; people and published margins of error.
- **Join keys:** state/county FIPS → `county_fips`; retain release year and
  ACS vintage.
- **Expected claim use:** population-normalized exposure and equity-context
  descriptions, always labelled as estimates.
- **Limitations:** ACS is a survey estimate, is neither utility-customer count
  nor hourly population, and must not be used to fabricate outages or demand.

## Energy, topology, and aggregate inputs

### E1 — EIA Form 860 annual plant/generator data

- **Publisher/version/date/license/access:** U.S. Energy Information
  Administration (EIA), Form EIA-860 annual data; use the named annual ZIP
  rather than an undated scrape. 2024 release:
  <https://www.eia.gov/electricity/data/eia860/xls/eia8602024.zip>;
  landing page: <https://www.eia.gov/electricity/data/eia860/>. Public EIA
  data; cite the form year and file checksum downloaded for the run.
- **Coverage/granularity/units:** U.S. plants/generators; annual reported
  nameplate capacity (MW), energy source/fuel, operating status, retirement
  and planned-operation fields, with plant latitude/longitude where reported.
- **Join keys:** `plant_id_eia` and generator ID; geocode → TIGER county;
  crosswalk only by documented utility identifiers, not name matching alone.
- **Expected claim use:** facility inventory, fuel/capacity mix, and
  announced/recorded generator status for Minnesota.
- **Limitations:** A plant coordinate is not a point of interconnection;
  Form 860 provides no branch impedance, line rating, bus assignment, dispatch,
  or hourly availability.

### E2 — EIA Form 923 generation and fuel receipts

- **Publisher/version/date/license/access:** EIA, Form EIA-923 annual data;
  2024 release: <https://www.eia.gov/electricity/data/eia923/xls/f923_2024.zip>;
  landing page: <https://www.eia.gov/electricity/data/eia923/>. Public access.
- **Coverage/granularity/units:** plant/fuel monthly generation and fuel data;
  reported net generation is MWh, fuel is in source-specific published units.
- **Join keys:** `plant_id_eia` (+ prime mover/fuel as appropriate) → E1.
- **Expected claim use:** historical facility-output/fuel context and an
  auditable capacity-versus-generation distinction.
- **Limitations:** Monthly values cannot validate an hourly scenario or imply
  power flow; plants with withheld/suppressed detail must remain unavailable.

### E3 — EIA-930 hourly balancing-authority operations

- **Publisher/version/date/license/access:** EIA Form EIA-930, hourly BA
  operations; reference tables:
  <https://www.eia.gov/electricity/930-content/EIA930_Reference_Tables.xlsx>;
  data documentation and files:
  <https://www.eia.gov/electricity/gridmonitor/about>. Public access.
- **Coverage/granularity/units:** hourly/daily BA demand, net generation and
  interchange in MW/MWh as named by the released fields; timestamps are UTC.
  Minnesota is primarily contextualized through `MISO` rather than a
  Minnesota-only BA series.
- **Join keys:** `ba_code`, UTC `ts`; source BA reference table is required
  before filtering or naming a BA.
- **Expected claim use:** regional demand/weather episode context and
  time-series checks at BA scale.
- **Limitations:** **No public county-hourly Minnesota demand is created by
  this source.** MISO BA totals cross state borders; never allocate them to a
  Minnesota county or retail utility without a separate, documented allocation.

### E4 — EIA Form 861 retail sales, customers, service territory and reliability

- **Publisher/version/date/license/access:** EIA Form EIA-861 annual survey;
  2024 ZIP: <https://www.eia.gov/electricity/data/eia861/zip/f8612024.zip>;
  landing page: <https://www.eia.gov/electricity/data/eia861/>. Public access.
- **Coverage/granularity/units:** utility/state/county service-territory and
  retail reporting, customer counts, annual MWh sales and reported reliability
  metrics (including published SAIDI/SAIFI fields where supplied). File header
  structure and the reporting year must be recorded during ingestion.
- **Join keys:** `utility_id_eia`; state/county names require a normalized,
  reviewed Census crosswalk; utility-to-BA associations must come from the
  released EIA fields/reference material, not geographic assumption.
- **Expected claim use:** annual utility/customer context, service-territory
  corroboration, and reliability trend context.
- **Limitations:** This is not outage telemetry, hourly load, a line map, or a
  customer-share allocation for overlapping territories.

### E5 — Public transmission and substation references

- **Publisher/version/date/license/access:** EIA Energy Atlas/HIFLD energy
  layers are the public national reference; access and layer documentation:
  <https://atlas.eia.gov/>. Minnesota’s own infrastructure page explicitly
  warns that the former state transmission/substation dataset has accuracy and
  currency problems and is no longer supported for distribution:
  <https://www.mngeo.state.mn.us/chouse/utilities.html>.
- **Coverage/granularity/units:** public map/vector layers where available,
  with line/substation geometry and published attributes; availability and
  licensing must be captured per downloaded layer.
- **Join keys:** spatial proximity only for map display/context; preserve
  source asset IDs. Do not invent a bus ID.
- **Expected claim use:** labelled public infrastructure context and visual
  orientation, subject to the source’s current access terms.
- **Limitations:** **No verified public source in this inventory supplies a
  current, complete Minnesota electrical network with connectivity, impedances,
  thermal ratings, transformer data, or operational topology.** It is therefore
  unavailable for a solved Minnesota power-flow/cascade model. Any public line
  layer remains non-authoritative and unsuitable for operational claims.

## Weather, hazards, and outage evidence

### W1 — NOAA HRRR gridded forecast/analysis fields

- **Publisher/version/date/license/access:** NOAA High-Resolution Rapid
  Refresh (HRRR) on the NOAA Open Data Dissemination Program AWS bucket;
  dataset registry and attribution/access notes:
  <https://registry.opendata.aws/noaa-hrrr-pds/>. Open data; preserve model
  cycle, forecast hour, product name and retrieval time.
- **Coverage/granularity/units:** gridded forecast products, with variable
  units defined by GRIB metadata; use only the domain/product valid for the
  requested Minnesota timestamp.
- **Join keys:** model valid UTC time + grid cell; county values require a
  stated area-weighted or selected-cell spatial aggregation to TIGER geometry.
- **Expected claim use:** forecast scenario weather drivers (wind, gust,
  temperature, precipitation/ice only when the selected product defines it).
- **Limitations:** Forecasts are not observations; changing model cycles and
  grid fields require pinning. Do not claim station-level measurement or a
  county-wide extreme without declaring the aggregation.

### W2 — NOAA Integrated Surface Database (ISD)

- **Publisher/version/date/license/access:** NOAA NCEI, ISD global hourly
  station observations; landing page:
  <https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database>.
  Public access; cite station, source file and retrieval/vintage.
- **Coverage/granularity/units:** station-hour observations; units and quality
  flags are defined in the release documentation.
- **Join keys:** station identifier + UTC `ts`; station point → county through
  TIGER spatial join, retaining distance/elevation where material.
- **Expected claim use:** observed weather validation and an auditable weather
  narrative near a named station.
- **Limitations:** A station is not a county average; gaps, flags, sensor siting
  and sparse northern/rural coverage must remain visible.

### W3 — NCEI Storm Events Database

- **Publisher/version/date/license/access:** NOAA NCEI Storm Events bulk CSV
  archive and data-format document:
  <https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/> and
  <https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/Storm-Data-Bulk-csv-Format.pdf>.
  Public access; archive filenames encode the reporting year/revision.
- **Coverage/granularity/units:** documented severe-weather events, with event
  type, begin/end time, county or forecast-zone location, magnitude and
  published property/casualty fields where reported.
- **Join keys:** source event ID; county FIPS only when present/derivable under
  the documented source geography; otherwise retain forecast-zone/location
  semantics and spatially join cautiously.
- **Expected claim use:** a cited intervention/outage scenario’s weather-event
  context and event chronology.
- **Limitations:** Event reports are not a gridded meteorological measurement;
  zone-based records can span counties and absence of a record is not proof of
  absence of hazardous weather.

### W4 — EAGLE-I county outage data

- **Publisher/version/date/license/access:** Oak Ridge National Laboratory’s
  EAGLE-I public Figshare collection; landing record:
  <https://figshare.com/articles/dataset/EAGLE-I_2024_Electricity_Outage_Data/24237376>.
  Use the license and exact file identifier shown by the release rather than a
  guessed filename; retain attribution required by the record.
- **Coverage/granularity/units:** released outage observations by published
  county FIPS/timestamp fields, generally `customers_out`; cadence and fields
  differ by release year.
- **Join keys:** published FIPS normalized to five-character `county_fips` +
  timestamp converted with declared timezone/UTC provenance; merge customer
  denominators only from the release’s associated coverage/customer file.
- **Expected claim use:** observed county outage count/time series where the
  source explicitly covers Minnesota and the selected period.
- **Limitations:** Coverage, `total_customers`, source utilities and reporting
  latency are release/year-specific. Missing observations, zero values and
  missing denominators are distinct states; never synthesize an outage rate or
  claim statewide completeness without a release-specific audit.

## Demand and intervention context

### D1 — Minnesota Commerce electricity-generation dashboards/reports

- **Publisher/version/date/license/access:** Minnesota Department of Commerce,
  Energy Policy, Data & Reports / Energy Data Dashboard:
  <https://mn.gov/commerce/energy/policy-data-reports/energy-data/>. Public
  dashboard/report access; cite the dashboard extract timestamp or named report
  date rather than calling a live visualization a fixed version.
- **Coverage/granularity/units:** state-level published electricity-generation
  context, with units and vintage as displayed/exported by the publisher.
- **Join keys:** state (`MN`) and report period; no valid county-hourly join.
- **Expected claim use:** state policy/generation context and a primary state
  citation alongside EIA facility records.
- **Limitations:** Dashboard aggregates cannot supply county load, topology,
  dispatch, or project completion facts unless an underlying dated extract says
  so.

### D2 — Minnesota PUC annual utility reporting (Rule 7610)

- **Publisher/version/date/license/access:** Minnesota Department of Commerce,
  electric utility annual reporting page and docket index:
  <https://mn.gov/commerce/energy/industry-government/utilities/annual-reporting.jsp>.
  Public filing context; individual eDockets documents should be cited by
  docket, filing date, submitter and document URL.
- **Coverage/granularity/units:** annual utility reports on generation, tariffs,
  interconnection and forecast information as specified by the filing form.
- **Join keys:** docket number + reporting year + utility legal name; map to
  EIA utility ID only through a reviewed crosswalk.
- **Expected claim use:** utility-specific planning/demand/interconnection
  context and a citation trail to Minnesota primary filings.
- **Limitations:** Filed forecasts are proposals/forecasts, not observed hourly
  demand or a statewide total; source documents may have changing formats.

### I1 — Minnesota PUC eDockets, IRP and integrated distribution planning

- **Publisher/version/date/license/access:** Minnesota Public Utilities
  Commission eDockets search:
  <https://mn.gov/puc/edockets/>; IRP programme:
  <https://mn.gov/puc/activities/economic-analysis/planning/irp/>; IDP programme:
  <https://mn.gov/puc/activities/economic-analysis/planning/idp/>. Public
  records access; use the final order/filing URL plus docket and filing date.
- **Coverage/granularity/units:** utility-specific resource, distribution,
  DER, electrification, reliability, forecast and investment material; temporal
  and spatial precision is document-specific.
- **Join keys:** docket number, filing document ID/date, utility, named project
  and geography; do not treat a title alone as a key.
- **Expected claim use:** proposed/approved intervention inventory, planned
  timing/cost/need claims when directly stated in a primary filing or order,
  and retrieval corpus documents.
- **Limitations:** An IRP/IDP is a planning record; it does not prove an asset
  is in service or quantify causal benefits. PDFs may be scanned, revised or
  superseded, so chunk provenance must include the exact document URL/date.

### I2 — Minnesota Energy Connection project record

- **Publisher/version/date/license/access:** Minnesota PUC project page:
  <https://mn.gov/puc/activities/energy-facilities/power-plants-transmission-lines/tranche-one/minnesota-energy-connection/>.
  The page identifies the project, certificate-of-need and route-permit dockets
  (`CN-22-131`, `TL-22-132`) and the cited planning context.
- **Coverage/granularity/units:** named 345-kV project and named endpoint/
  county context as published by the Commission; use cited docket documents for
  definitive route, dates, costs and conditions.
- **Join keys:** docket number, project name, utility, county/place, and filing
  date.
- **Expected claim use:** a concrete, source-backed intervention/retrieval
  example—properly described as proposed/approved/in-service only according to
  the cited document’s status.
- **Limitations:** This project page is not a GIS line geometry, electrical
  model, construction-completion record, or quantified resilience outcome.

## Citation/retrieval corpus intake

The corpus should contain documents that make a specific planning or
regulatory claim traceable, not raw dashboards or unbounded web crawls.

| Candidate collection | Primary entry point | Include | Chunk/provenance fields | Exclude or label |
| --- | --- | --- | --- | --- |
| PUC eDockets | <https://mn.gov/puc/edockets/> | Final orders, utility filings, agency comments and exhibits for selected IRP/IDP/transmission dockets | `source_url`, docket, document ID/title, filing date, publisher, page, SHA-256, retrieval time, version/supersession status | Search-result snippets; any PDF without page-aware provenance |
| PUC programme/project pages | <https://mn.gov/puc/activities/economic-analysis/planning/> | Stable agency overview and project pages used for high-level process/status context | URL, page title, agency, captured date, quoted section heading | Treat page content as secondary to a dated docket order for a dispositive fact |
| Commerce Rule 7610 reports | <https://mn.gov/commerce/energy/industry-government/utilities/annual-reporting.jsp> | Named annual report forms/filings and their docket context | docket, utility, reporting year, filing date, URL, page/sheet | Forecasts must retain `claim_type=forecast`, not observed fact |
| EIA methodology/reference material | <https://www.eia.gov/electricity/data/eia861/> | Form instructions, reference tables and selected annual release documentation | form, report year, file URL, table/sheet, checksum, retrieval date | Do not embed raw large tables in text RAG; use structured ingestion with citations |
| NOAA documentation | <https://www.ncei.noaa.gov/stormevents/> | Storm Events and model/station documentation used to define weather evidence | dataset, file/station/model cycle, time coverage, URL, page/section | Do not turn event reports into unqualified causal outage conclusions |

**Retrieval guardrails.** A `cite()` response should return at minimum the
publisher, title, direct URL, document date, retrieval date, page/section and
chunk identifier. Claims about a current project must prefer the newest final
order or explicit in-service notice over an earlier application. Structured
source rows should carry the same source URL, release vintage and checksum;
retrieval text cannot replace data provenance.

## Explicitly unavailable or not-yet-resolved dimensions

1. A current, complete public Minnesota AC/DC network model—buses, connectivity,
   impedances, transformer parameters, line thermal limits, switching state and
   dispatch—is **unavailable in this inventory**. CEII/security and source
   limitations mean no solved Minnesota grid, cascade output or line-loading
   claim should be generated from public map layers.
2. A public Minnesota county-hourly demand series is **not identified**. EIA-930
   MISO totals are BA-scale and multi-state; EIA-861/Rule 7610 are annual/report
   context. Any county allocation requires a separately approved method and
   must be labelled modelled.
3. A universal county-to-utility customer-share mapping is **not identified**.
   Service-area polygons can overlap; EIA-861 territory records do not by
   themselves establish contemporaneous customer shares.
4. EAGLE-I outage completeness and denominators must be audited after selecting
   the exact release/year. Until then, Minnesota outage rates and statewide
   completeness are unavailable, not zero.
5. Regulatory records can support what a document says about a project. They
   cannot, without a source-specific evaluation, establish causal reliability,
   resilience, cost-effectiveness or completion outcomes.
