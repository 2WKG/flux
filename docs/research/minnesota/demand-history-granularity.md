# Minnesota demand history and usable geographic granularity

**Assessment date:** 2026-09-05
**Decision:** support an hourly **MISO Local Resource Zone 1 (LRZ 1)** load
series only when the extract identifies `LRZ1` and is retained with its MISO
source metadata. Label it **"MISO LRZ 1 (Minnesota/North Dakota region), not
Minnesota statewide"**. It is the smallest source-backed operational area found
in this assessment. Do **not** create Minnesota county demand observations or
describe LRZ 1 as statewide Minnesota demand.

If a reproducible LRZ 1 extract cannot be obtained from MISO's Data Exchange,
fall back to the public EIA-930 `MISO` balancing-authority series, labeled
**"MISO balancing authority"**. That fallback is useful for regional load-shape
analysis only; it is not a Minnesota measurement.

## Findings

| Candidate | Temporal coverage and units | Smallest usable geography / join | Access | What it cannot support |
|---|---|---|---|---|
| **MISO Historical Daily Forecast and Actual Load by LRZ** | The reader's guide describes `MarketDay`, `HourEnding`, `LocalResourceZone`, `MTLF`, and `ActualLoad`; load is MW and the historical report is hourly within each market day. A published 2015 example establishes the report family's age, but a reproducible three-year extract must be confirmed from MISO before this becomes the production series. | **LRZ 1.** MISO identifies LRZ 1 with local balancing authorities DPC, GRE, MDU, MP, NSP, OTP, and SMP; MISO separately characterizes LRZ 1 as the Minnesota/North Dakota region. This is a multi-state zone, not a Minnesota boundary. Retain MISO's zone label as the key; do not spatially split it. | MISO publishes the report family and maps it to the Load, Generation, and Interchange API. Its market-report page says pricing/load reports are moving to the Data Exchange API and old reports expire, so acquisition must be tested and versioned at ingestion time. | Minnesota-only MW; utility-only MW; county MW; any county share of an LRZ value. LRZ 1 may not be summed with another source to claim the state total. |
| **EIA-930 MISO balancing-authority demand** | Hourly actual and forecast demand in MW. EIA says original elements are available back to July 2015, so 2022--2024 is a clean three-calendar-year extract. The public six-month CSVs expose `Demand (MW)`, `Demand (MW) (Adjusted)`, imputation flags, and UTC hour-end timestamps. | **MISO balancing-authority footprint.** Use `Balancing Authority = MISO`; no spatial join is appropriate. | Public EIA CSV downloads; the API requires a registered key. The cited 2024 H1 CSV is a direct reproducible example. | Minnesota statewide, LRZ, utility, or county demand. Treat adjusted and imputation fields as data-quality metadata, not a geographic disaggregation. |
| **EIA-930 MISO subregion series** | Hourly MW; EIA began collecting demand by subregion in July 2018, providing more than three years. The public file uses a `Sub-Region` identifier (for example, numeric codes in the 2024 H1 file). | Potentially below BA level, but **not accepted for Minnesota use yet**. This assessment did not find an authoritative public crosswalk from EIA's MISO subregion identifiers to Minnesota, LRZ 1, counties, or service territories. | Public CSV download / key-based EIA API. | A Minnesota or county series until MISO or EIA supplies a versioned identifier crosswalk. Do not guess from code values or geography. |
| **FERC Form 714 planning-area hourly demand** | Planning-area actual hourly demand is reported in MW. FERC provides historical downloads from 2011 onward (and an older 2006--2020 database), so multiple Minnesota utility/planning-area histories can exceed three years. | A respondent's **planning area**, not a county. A utility-area footprint can be associated with EIA-861 service-territory county membership, but that file only says where a utility has distribution equipment. | Public FERC downloads/eForms; retain filing year, respondent, time zone, and filing version. | County MW. A county can have multiple utilities, and service-territory membership provides no allocation weight. It also should not be silently treated as MISO operational load. |
| **EIA-861 annual sales plus service territory** | Annual sales are MWh, with revenue and customer counts; sales history runs from 1990. It is useful for long-run annual energy context, not hourly demand or MW peak. | Sales are reported by state, sector, and balancing authority. The separate service-territory file lists counties where a utility has distribution equipment. These files are not a county-sales join. | Public, published detailed files; no license statement is asserted here beyond the cited public availability. | Hourly demand, MW peak, or county MWh/MW. Do not allocate utility sales to every listed county (or by population/customers/area) without a separately documented source. |
| **Minnesota Commerce Rule 7610 filings** | The state lists annual reporting dockets for 2019--2025; nine utilities must submit a forecast section. This establishes a multi-year filing trail, not a standardized public actual-hourly dataset. | Utility/service-area reporting, where a filed workbook makes a field available. | Public docket references and downloadable blank forms; obtain and inspect each public filing before use. | A complete statewide hourly series, standardized utility history, or county observations. Forecasts must remain forecasts and must not be labeled historical actual demand. |

## Recommended contract and claim limits

Use a narrow source-backed table for the preferred series:

```text
miso_lrz_load_hourly(
  market_day, hour_ending, lrz, actual_load_mw, forecast_load_mw,
  source_url, retrieved_at, source_version
)
```

- Permit `lrz = "LRZ1"` only after validating the downloaded MISO record's
  field names and units against the reader's guide.
- The UI and documentation must say **"MISO LRZ 1 (Minnesota/North Dakota
  region) actual load, MW"**. It may be used for regional load-shape,
  weather-correlation, and scenario context.
- Do not call it ``Minnesota demand`` without the regional qualifier; do not
  use it to rank Minnesota counties, estimate county customers, or calibrate a
  county model target.
- A county-level feature may join the *same regional value* only as an
  explicitly regional covariate (`miso_lrz1_actual_load_mw`), never as an
  observation of that county's demand. No proportional allocation is permitted.
- Keep EIA-930 `MISO` as a documented fallback/check series. Preserve
  `Demand (MW) (Adjusted)` and the imputation indicator; do not interpolate or
  allocate missing values geographically.

## Sources

1. [MISO Market Reports](https://www.misoenergy.org/markets-and-operations/real-time--market-data/market-reports/) — identifies the historical LRZ actual/forecast-load report and states the transition of load reports to the Data Exchange API.
2. [MISO historical LRZ load reader's guide](https://docs.misoenergy.org/marketreports/Historical%20Daily%20Forecast%20and%20Actual%20Load%20by%20Local%20Resource%20Zone_Historical%20Daily%20Forecast%20and%20Actual%20Load%20by%20Local%20Resource%20Zone%20Readers%20Guide.pdf) — report fields, hourly `HourEnding`, and MW actual-load example.
3. [MISO report-to-endpoint mapping](https://cdn.misoenergy.org/Data%20Exchange%20Report%20to%20Endpoint%20Mapping726669.pdf?v=20251107140821) — maps the historical LRZ report to MISO's Load, Generation, and Interchange API.
4. [MISO LRZ 1 local-balancing-authority list](https://cdn.misoenergy.org/20251120%20RSC%20Item%2008%20Generator%20Winterization%20Survey727988.pdf) and [MISO's Minnesota/North Dakota LRZ 1 description](https://cdn.misoenergy.org/2025-11-21_MISO%20Response%20RFI%20-%20Accelerating%20Speed%20to%20Power728943.pdf) — the basis for the regional label and its multi-state limitation.
5. [EIA description of the Hourly Electric Grid Monitor and EIA-930 coverage](https://www.eia.gov/todayinenergy/detail.php?id=40993) — hourly demand, July 2015 original-history availability, July 2018 subregion collection, and MISO as a subregion reporter.
6. [EIA-930 2024 H1 balancing-authority CSV](https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2024_Jan_Jun.csv) and [subregion CSV](https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_SUBREGION_2024_Jan_Jun.csv) — direct source files and schemas.
7. [FERC Form 714 overview](https://www.ferc.gov/industries-data/electric/general-information/electric-industry-forms/form-no-714-annual-electric/overview) and [downloads](https://www.ferc.gov/industries-data/electric/general-information/electric-industry-forms/form-no-714-annual-electric/data) — planning-area hourly demand and public historical availability.
8. [EIA Form 861 detailed files](https://www.eia.gov/electricity/data/eia861/) and [EIA county-data FAQ](https://www.eia.gov/TOOLS/FAQS/faq.php?id=448&t=5) — annual sales scope and the service-territory county limitation.
9. [Minnesota Commerce annual electric reporting](https://mn.gov/commerce/energy/industry-government/utilities/annual-reporting.jsp) — reporting years, forecast-section utilities, and docket access.
