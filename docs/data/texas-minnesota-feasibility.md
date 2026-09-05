---
title: "Texas + Minnesota — data and scenario feasibility"
status: complete
issue: 2WKG-186
sibling: "docs/data/texas-new-york-feasibility.md (2WKG-138) — New York remains an open candidate"
assessed: 2026-09-05
assessor: Ghadi Khoury
scope: "Next wave. Non-blocking for the current Texas demo."
---

# Texas + Minnesota — feasibility

**Verdict: pending reproducible evidence.** Minnesota is an available candidate, but the
GridSFM inventory and solve results below are **[UNVERIFIED]** until this repository contains
the pinned release inputs and the commands or output needed to reproduce them. They are not
decision evidence in their current form.

**This does not close out New York.** Both states are live candidates; the choice is deferred
until more data is in. New York's provisional inventory and the head-to-head trade-off are in
`docs/data/texas-new-york-feasibility.md`.

One finding changes how the scenario must be built — see §3. Read it before committing.

---

## 1. Provisional GridSFM inventory **[UNVERIFIED]**

`microsoft/GridSFM_US_power_grid`, release `2026_05_07`, **MIT licence**. Single-state models
for all 48 contiguous states plus 6 multi-state regions. Two snapshots per region, `04h` and
`16h`. File pattern `{hour}/{region}_{model|ac_results|dc_results}.json`.

The values below were recorded as a working note, but this PR includes no parsing script, raw
output, file manifest, or checksum to reproduce them. **Do not use this table to choose a state
until it is reproduced from the pinned release.**

| | **Minnesota** | **Texas** | ACTIVSg2000 (current synthetic case) |
|---|---|---|---|
| Buses | **718** | **3,889** | 2,000 |
| Branches (lines + transformers) | **1,297** | **6,852** | 3,206 (2,359 line + 847 transformer) |
| Generators | **97** | **509** | 544 (484 gen + 59 sgen + 1 ext_grid) |
| Loads | 718 | 3,889 | 1,125 |
| Demand, `04h` off-peak | **4,716 MW** | 47,608 MW | — |
| Demand, `16h` peak | **7,131 MW** | **74,049 MW** | 67,109 MW (single base case) |
| Balancing authority | **MISO** | **ERCO** | — |
| BA coverage | **97.4 %** | **84.0 %** | — |
| AC-OPF `04h` | **LOCALLY_SOLVED**, L0 Strict, 21 s | LOCALLY_SOLVED, L0 Strict, 45 s | — |
| AC-OPF `16h` | **LOCALLY_SOLVED**, L0 Strict, 21 s | LOCALLY_SOLVED, L0 Strict, 51 s | — |
| Units decommitted to solve | **0** | 0 | — |
| `source_type` | `matpower` v2 | `matpower` v2 | MATPOWER |
| DC lines / shunts | 2 / 666 | — | — |

If reproduced, branch counts should be compared like for like: GridSFM's `branch` table holds
lines *and* transformers together, while the documented ACTIVSg2000 import splits them into
`net.line` and `net.impedance`.

The Minnesota AC-OPF and unit-commitment entries in the table are likewise **[UNVERIFIED]**;
they do not close the solver risk until a reproducible check is committed.

GridSFM and ACTIVSg2000 have different modelling origins. ACTIVSg2000 is a synthetic topology,
and agreement in aggregate MW would not independently validate either model's topology.

---

## 2. The case for Minnesota

Minnesota's distinctive argument is not "hot state versus cold state." It is **the same storm
hitting two grids that behaved completely differently.**

Under Winter Storm Uri, February 2021 (FERC/NERC final report):

| Grid | Firm load shed |
|---|---|
| **ERCOT** | **Three consecutive days**, up to 20,000 MW — largest manually controlled load shed in US history |
| **SPP** | 5 hours |
| **MISO** | 2 hours |

Same week, adjacent geography, three grids, three outcomes. The difference is interconnection,
market design and winterisation — exactly what a firm-generation siting tool is about.

Supporting context:

- Freezing equipment caused 44 % of unplanned outages, derates and start-up failures.
- In its **2014–15** Winter Reliability Assessment extreme-winter scenario, NERC projected MISO
  available capacity falling from 144 GW to 121 GW and reserve margin from 43 % to 12 %.
  This is historical scenario context, not a current forecast.

Minnesota is in the grid that held. Texas is the grid that did not.

---

## 3. The finding that changes the scenario: **these are July models**

Both Minnesota and Texas models carry `target_datetime = 2024-07-15T16:00`.

**The shipped demand allocation is a mid-July afternoon.** The `04h` / `16h` pair is off-peak
and peak *on a summer day* — not a winter morning, and not a time series.

Consequences, none fatal but all load-bearing:

1. **The baseline is a summer snapshot.** Our stress preset ([S01]–[S04]) already scales demand
   and derates generation on a copy of the network, so applying a cold-weather stress on top is
   the existing design. But the starting point is July, and that must be said out loud.
2. **Minnesota is understated.** A July snapshot does not carry winter heating load, which is
   precisely what makes MISO North winter-relevant. Scaling MN summer demand into a winter
   scenario is an assumption with a magnitude, and it needs a stated source or it is invented.
3. **`load_allocation_method` is `per_ba_census`** and `dispatch_method` is `merit_order` —
   demand is allocated to buses by census population within each BA, not measured per bus. Two
   buses in the same area differ by population weight, not by metered load.
4. **Texas reports 84 % BA coverage.** This document does not interpret that metadata as the
   fraction of ERCOT demand missing from the model. The two cases are constructed differently,
   so their absolute shed-MW outputs are case-specific rather than a cross-state comparison.

**Recommendation: keep the stress preset as the single declared scenario, state that the
baseline snapshot is 2024-07-15, and do not describe the result as a winter reconstruction.**
The 48-hour plan already requires this — *"illustrative cold-weather stress, not a Uri forecast
or historical reconstruction."* Uri belongs in the pitch as motivation and as the sourced table
in §2, never as a claimed simulation.

---

## 4. Supporting data for Minnesota

| Need | Source | Minnesota covered? |
|---|---|---|
| Market load, fuel mix, LMP | **MISO Data Exchange** — public API; real-time 5-min LMP endpoint is open; fuel mix and historical reports published | Yes — MISO is MN's BA |
| Generation by fuel | EIA-923 / EIA-860 / EIA-930 | Yes — national |
| Population growth | Census PEP Vintage 2025 | Yes — national |
| Urban / rural | USDA ERS RUCC 2023 | Yes — national |
| Industry | BLS QCEW, county × NAICS | Yes — national, with disclosure suppression |
| Outages | EAGLE-I, DOE-417 | Yes — national |
| Severe weather | NOAA Storm Events, HRRR | Yes — national |

Everything in `docs/data/industry-urban-rural-population-inputs.md` extends to Minnesota at zero
cost — those are national files keyed on county FIPS.

**County resolution:** Texas 254 counties, Minnesota 87. Coarser, but far better than New York's
62, and the county spine (`buses.county_fips`) is unchanged.

The `gridstatus` Python library — already a dependency in `pyproject.toml` — supports MISO for
load, fuel mix and LMP alongside ERCOT. **No new dependency is needed to pull MISO data.**

---

## 5. Integration cost — the real remaining question

Availability is settled. Cost is not.

- **Format.** GridSFM ships PowerModels-compatible JSON with MATPOWER structure, per-unit on a
  100 MVA base. pandapower reads MATPOWER `.m` via `matpowercaseframes`. Reading this JSON needs
  a small converter. This is the one genuine engineering task and it is **unscoped**.
- **Switching Texas is out of scope for 2WKG-186.** Minnesota may be assessed as a second case
  while the current Texas pipeline remains unchanged. This document does not invalidate or
  replace the existing Texas ingest decisions.
- **Runtime.** The reported inventory suggests Minnesota may be smaller, but a reproducible
  solver check is needed before treating that as a runtime estimate.

---

## 6. Texas-only fallback

Unchanged and still the safe path: one grid, one stress preset, two candidate sites, signed
comparison — the frozen scope in the 48-hour build plan.

If Minnesota is cut for time, the contrast survives as a stated argument: the Uri load-shed
table in §2 is sourced and needs no second simulation, and ERCOT's electrical isolation is a
defensible reason Texas is the right first case.

**Decision rule:** add Minnesota only after the complete Texas demo is frozen and rehearsed, per
the build plan's own instruction not to build stretch features before that point.

---

## 7. New York's standing

See `docs/data/texas-new-york-feasibility.md` for the correction, open prerequisites,
interconnection caveat, and second-state trade-off; it is the single source of record for New
York.

---

## Sources

- [microsoft/GridSFM_US_power_grid — Hugging Face](https://huggingface.co/datasets/microsoft/GridSFM_US_power_grid)
- [microsoft/GridSFM — GitHub](https://github.com/microsoft/gridSFM)
- [Building Power Grid Models from Open Data (arXiv 2605.04289)](https://arxiv.org/html/2605.04289)
- [FERC/NERC final report on the February 2021 freeze](https://www.ferc.gov/news-events/news/final-report-february-2021-freeze-underscores-winterization-recommendations)
- [FERC/NERC report — MISO summary](https://www.misoenergy.org/meet-miso/media-center/miso-matters/fercnerc-release-final-report-on-february-2021-winter-storm-uri/?epslanguage=en)
- [EIA Today in Energy: NERC 2014–15 Winter Reliability Assessment](https://www.eia.gov/todayinenergy/detail.php?id=19631)
- [MISO Market Reports](https://www.misoenergy.org/markets-and-operations/real-time--market-data/market-reports/)
- [MISO real-time 5-min LMP public API](https://public-api.misoenergy.org/api/MarketPricing/GetRealTimeFiveMinExPost/Rolling)
- [gridstatus — MISO support](https://opensource.gridstatus.io/en/latest/autoapi/gridstatus/miso/index.html)
- [EIA Open Data](https://www.eia.gov/opendata/)
