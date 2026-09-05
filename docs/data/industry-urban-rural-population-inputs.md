---
title: "Industry, urban–rural, population-growth and ecological inputs — candidate sources"
status: complete
issue: 2WKG-139
assessed: 2026-09-05
assessor: Ghadi Khoury
scope: "Next wave. Non-blocking for the current Texas demo."
feeds: 2WKG-134 (source dictionary), 2WKG-138 (Texas + New York feasibility)
---

# Candidate context inputs — sources, granularity and joins

Four dimensions were asked for: **industry**, **urban/rural density**, **population growth**,
and **ecological context**. Three have clean, public, county-resolution sources. The fourth
(ecological) does **not**, and is recorded as unavailable at county granularity rather than
imputed.

Nothing here is required for the current Texas demo. This is next-wave input curation.

---

## 0. The join spine: 5-digit county FIPS

Every source below is assessed against one key: the **5-digit county FIPS code**.

This is the right spine because the repo contract already carries it — `buses.county_fips`
joins to a `counties` table (`docs/specs/00-overview.md`). Texas has **254 counties**, the most
of any state, which is a genuine advantage: county resolution is comparatively fine-grained here.

**The hard limit of this spine, stated once and applying to every table below:** these are all
**county-level** sources. A county contains many buses. Nothing in this collection can
differentiate two buses inside the same county. Any per-bus figure derived from a county figure
is an allocation assumption, not data — and under the project's honesty rules it must be
labelled as such or not made.

---

## 1. Population growth — **AVAILABLE**

| Field | Value |
|---|---|
| Source | US Census Bureau, Population Estimates Program (PEP) |
| Vintage | **2025** (most recent complete), covering 2020–2025 |
| Granularity | County, annual, with age/sex/race-ethnicity breakdowns available |
| Join key | County FIPS, native |
| License | US federal government work — public domain |
| Access | Bulk CSV from the PEP data-sets pages |

**Caveat that matters:** the Census Data API requires a key, and **current estimates are not
served by the API** — historical vintages only. Plan on downloading the bulk files, not on a
live API call. Do not design anything that fetches this at runtime.

**Texas alternative:** the Texas Demographic Center publishes state-produced county and place
estimates (July 1 for 2021–2024, plus January 1 2025). Useful as a cross-check. If the two
disagree, say which one is displayed — do not average them.

---

## 2. Urban / rural density — **AVAILABLE**

| Field | Value |
|---|---|
| Source | USDA Economic Research Service, **Rural-Urban Continuum Codes (RUCC), 2023** |
| Granularity | County, 9 ordinal codes (3 metro, 6 nonmetro) |
| Coverage | 3,235 counties and county-equivalents, incl. Puerto Rico and territories |
| Join key | County FIPS, native |
| License | Public domain |
| Access | Single Excel file from the ERS documentation page |

This is the cleanest source of the four — one small file, one code per county, no assembly.

**Caveat that matters:** the 2023 revision **raised the urban-area population threshold from
2,500 to 5,000**, following the Census Bureau's 2020 urban-area redefinition. RUCC 2023 codes
are therefore **not directly comparable to earlier vintages**. If any trend or before/after
comparison uses RUCC, it is comparing two different definitions. Use one vintage only.

RUCC is an ordinal category, not a density figure. If an actual density (people per square mile)
is wanted, that is a separate derivation from PEP population ÷ county land area, and should be
labelled as derived.

---

## 3. Industry — **AVAILABLE, WITH SUPPRESSION**

Two candidates. **Recommend QCEW.**

| | **BLS QCEW** (recommended) | Census County Business Patterns |
|---|---|---|
| Granularity | County × NAICS to 6 digits | County × NAICS |
| Time | Quarterly + annual averages | **March only**, annual |
| Coverage | >95% of US jobs (UI-covered employment) | Establishment surveys + admin records |
| Join key | County FIPS, native | County FIPS, native |
| Access | Open Data Access files, Data Viewer, state/county map | Census bulk + API |
| License | Public domain | Public domain |

QCEW wins on time resolution (quarterly vs. a single March snapshot) and on being a near-census
of covered employment rather than a survey.

**The caveat that matters most in this whole document:** QCEW publishes detailed NAICS at county
level **only where disclosure restrictions are met**. In counties with few establishments in an
industry, cells are **suppressed** to protect employer confidentiality. Texas has many
low-population rural counties, so suppression will be common exactly where the grid questions
are often most interesting.

**A suppressed cell is not a zero.** It must stay suppressed — carried as explicitly unknown,
never filled with 0, a state average, or an interpolation. This is the "unavailable dimensions
remain unavailable rather than imputed" clause of the acceptance criteria, and it is the single
easiest way for this dataset to produce a dishonest number.

Note also that QCEW counts **jobs by workplace**, not people by residence, and not electricity
consumption. It is a proxy for industrial activity, not a measure of industrial load. Do not
present it as load.

---

## 4. Ecological context — **UNAVAILABLE at county granularity without extra work**

This dimension does not have a ready county-level public table. Three partial options:

**NLCD (National Land Cover Database)** — USGS/MRLC. 30 m resolution, CONUS, now annual for
**1985–2024**. Public domain, freely downloadable or streamable. **But it is raster**, not
county rows. Using it means running our own zonal aggregation to counties — a real geospatial
task with its own methodology choices, not a join.

**IPUMS NHGIS environmental summaries** — publishes NLCD **pre-summarized to counties** (also
tracts, county subdivisions, places). This is the only join-ready option found. **It requires an
NHGIS account/registration**, and its redistribution terms must be read before anything derived
from it is committed. Not assumed here.

**PAD-US (Protected Areas Database)** — USGS Gap Analysis Project. Downloadable by state or
region, available as web services and layers. GIS format, **not county-aggregated**. Same zonal
aggregation problem as NLCD.

**Recorded outcome: unavailable at county granularity as a direct source.** Either accept the
NHGIS registration step, or budget explicit time for raster→county aggregation. Do **not** carry
"ecological context" as though it were collected. It is not.

---

## 5. Join assessment, summarised

| Dimension | Source | County FIPS native? | Ready to join? |
|---|---|---|---|
| Population growth | Census PEP V2025 | Yes | **Yes** (bulk file, not API) |
| Urban / rural | USDA ERS RUCC 2023 | Yes | **Yes** |
| Industry | BLS QCEW | Yes | **Yes**, with suppressed cells preserved |
| Ecological | NLCD / PAD-US | **No** — raster / GIS | **No** — needs aggregation, or NHGIS account |

Three of four join on the existing `county_fips` spine with no transformation. The fourth needs
either a registration decision or a geospatial work item; that is a scope call, not a lookup.

**Cross-state note for 2WKG-138:** PEP, RUCC and QCEW are all national. Extending from Texas to
New York costs nothing on these three — the same files already contain New York's counties. New
York has 62 counties against Texas's 254, so county resolution is materially coarser there. That
asymmetry belongs in the Texas-plus-New-York feasibility decision.

---

## 6. What must not be done with these

Collected here so the constraints travel with the sources:

- **No imputation of suppressed QCEW cells.** Unknown stays unknown.
- **No mixing RUCC vintages.** The 2023 threshold change breaks comparability.
- **No runtime API dependency on Census PEP.** Current estimates are not API-served; use files.
- **No sub-county attribution.** County figures cannot be pushed down to individual buses
  without an explicitly labelled allocation assumption.
- **No presenting employment as electrical load.** QCEW counts jobs, not megawatts.
- **No projections shown as observed history** — carried over from 2WKG-138's framing, and it
  applies to population growth in particular: PEP estimates are estimates, not a census count.

---

## Sources

- [Population and Housing Unit Estimates — US Census Bureau](https://www.census.gov/popest)
- [Population and Housing Unit Estimates Datasets](https://www.census.gov/programs-surveys/popest/data/data-sets.html)
- [County Population by Characteristics: 2020–2025](https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-detail.html)
- [Population Estimates APIs — Census developers](https://www.census.gov/data/developers/data-sets/popest-popproj/popest.html)
- [Texas Demographic Center — Estimates](https://texasdemography.utsa.edu/Estimates/)
- [2023 Rural-Urban Continuum Codes — USDA ERS](https://ers.usda.gov/data-products/rural-urban-continuum-codes)
- [RUCC documentation and download — USDA ERS](https://www.ers.usda.gov/data-products/rural-urban-continuum-codes/documentation)
- [Quarterly Census of Employment and Wages — BLS](https://www.bls.gov/cew/)
- [Alternative measures of county employment — BEA](https://www.bea.gov/sites/default/files/2023-01/alternative_measures_county.pdf)
- [Annual National Land Cover Database — USGS](https://www.usgs.gov/centers/eros/science/annual-national-land-cover-database)
- [Multi-Resolution Land Characteristics Consortium](https://www.mrlc.gov/)
- [Environmental Summaries — IPUMS NHGIS](https://www.nhgis.org/environmental-summaries)
- [PAD-US Data and Maps](https://www.protectedlands.net/data/)
