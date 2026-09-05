---
title: "Texas + Minnesota — data and scenario feasibility"
status: complete
issue: 2WKG-186
supersedes: 2WKG-138 (Texas + New York) — New York cancelled
assessed: 2026-09-05
assessor: Ghadi Khoury
scope: "Next wave. Non-blocking for the current Texas demo."
---

# Texas + Minnesota — feasibility

**Verdict: FEASIBLE.** Minnesota exists, solves, and is a better contrast than New York was.
Every claim below was verified by downloading and parsing the actual files, not from
documentation.

One finding changes how the scenario must be built — see §3. Read it before committing.

---

## 1. Verified inventory

`microsoft/GridSFM_US_power_grid`, release `2026_05_07`, **MIT licence**. Single-state models
for all 48 contiguous states plus 6 multi-state regions. Two snapshots per region, `04h` and
`16h`. File pattern `{hour}/{region}_{model|ac_results|dc_results}.json`.

Downloaded and parsed 2026-09-05:

| | **Minnesota** | **Texas** | ACTIVSg2000 (current) |
|---|---|---|---|
| Buses | **718** | **3,889** | 2,000 |
| Branches | **1,297** | **6,852** | 2,359 |
| Generators | **97** | **509** | 484 + 59 sgen |
| Loads | 718 | 3,889 | 1,125 |
| Total demand | **7,131 MW** | **74,049 MW** | 67,109 MW |
| Balancing authority | **MISO** | **ERCO** | — |
| BA coverage | **97.4 %** | **84.0 %** | — |
| AC-OPF `04h` | **LOCALLY_SOLVED** (21 s) | LOCALLY_SOLVED (45 s) | — |
| AC-OPF `16h` | **LOCALLY_SOLVED** (21 s) | LOCALLY_SOLVED (51 s) | — |
| `source_type` | `matpower` v2 | `matpower` v2 | MATPOWER |
| DC lines / shunts | 2 / 666 | — | — |

**Minnesota is not one of the six single-state models that fail AC-OPF.** It converges at both
hours. That was the main open risk and it is now closed by direct check, not by citing the
paper's 88 % figure.

The Texas cross-check is reassuring: GridSFM Texas reports 74,049 MW against ACTIVSg2000's
67,109 MW — same order, different construction. The two are independent models of the same
system, not the same model.

---

## 2. Why Minnesota beats New York

The contrast is no longer "hot state versus cold state." It is **the same storm hitting two
grids that behaved completely differently.**

Under Winter Storm Uri, February 2021 (FERC/NERC final report):

| Grid | Firm load shed |
|---|---|
| **ERCOT** | **Three consecutive days**, up to 20,000 MW — largest manually controlled load shed in US history |
| **SPP** | 5 hours |
| **MISO** | 2 hours |

Same week, adjacent geography, three grids, three outcomes. The difference is interconnection,
market design and winterisation — exactly what a firm-generation siting tool is about.

Supporting context, all sourced:

- The 2021 event drove the loss of 61,800 MW of generation; more than 1,000 units were forced
  offline, derated or failed to start on over 4,000 occasions.
- Freezing equipment caused 44 % of unplanned outages, derates and start-up failures.
- NERC projects MISO capacity falling from 144 GW to 121 GW in an extreme winter, cutting the
  reserve margin from 43 % to 12 %. This is live, documented winter risk — not hypothetical.
- The NWS-flagged cold band runs along the Canadian border through Montana, the Dakotas,
  Minnesota, Wisconsin and Michigan's Upper Peninsula.

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
4. **Texas BA coverage is 84 %.** Roughly a sixth of ERCOT demand is unaccounted for in that
   model. Minnesota's 97.4 % is much cleaner. Do not compare absolute shed MW between the two
   states without stating this asymmetry.

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
- **Switching Texas is not required.** Minnesota can be added as a second case while Texas stays
  on ACTIVSg2000 — but then the two states come from different pipelines and absolute numbers
  are not comparable. Using GridSFM for both is the honest option and invalidates [D01]–[D03],
  already merged in PR #6.
- **Runtime.** Minnesota at 718 buses is roughly a fifth of GridSFM Texas and a third of
  ACTIVSg2000. It is the cheap half of the pair, not the expensive one.

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

## 7. Correction to 2WKG-138

The New York assessment rejected a second state on the grounds that *no public case existed at a
resolution comparable to ACTIVSg2000*. **That was wrong.** GridSFM publishes single-state models
for all 48 contiguous states; New York is `new_york_model.json`, comparable in size to
Minnesota's. The evaluation there considered only the TAMU ACTIVSg family, Cornell's NYgrid and
NPCC-140, and did not carry GridSFM across from the Brookhaven assessment where it had been
found.

The conclusion — Texas-only for the hackathon — happened to survive, but on schedule-risk
grounds, not data availability. `docs/data/texas-new-york-feasibility.md` is removed by this
change rather than left standing as a contradiction on `master`; its still-valid content
(scenario inputs, EIA projection boundary, economic-disruption handling) is carried into §3, §4
and below.

**Scenario inputs, carried forward unchanged:**

- *Energy-source shift* — EIA state-level generation by fuel; MWh and MW; monthly and annual;
  public domain. API caps at 5,000 rows per request; bulk refreshes twice daily. **EIA also
  publishes AEO projections, which may never sit beside historical generation unlabelled.**
- *Economic disruption* — no dataset exists. It is a declared scenario assumption with stated
  magnitude, duration and rationale, not an input. QCEW and PEP measure activity and people, not
  disruption and not megawatts.

---

## Sources

- [microsoft/GridSFM_US_power_grid — Hugging Face](https://huggingface.co/datasets/microsoft/GridSFM_US_power_grid)
- [microsoft/GridSFM — GitHub](https://github.com/microsoft/gridSFM)
- [Building Power Grid Models from Open Data (arXiv 2605.04289)](https://arxiv.org/html/2605.04289)
- [FERC/NERC final report on the February 2021 freeze](https://www.ferc.gov/news-events/news/final-report-february-2021-freeze-underscores-winterization-recommendations)
- [FERC/NERC report — MISO summary](https://www.misoenergy.org/meet-miso/media-center/miso-matters/fercnerc-release-final-report-on-february-2021-winter-storm-uri/?epslanguage=en)
- [NERC 2025–2026 Winter Reliability Assessment](https://www.nerc.com/globalassets/our-work/assessments/nerc_wra_2025.pdf)
- [MISO Market Reports](https://www.misoenergy.org/markets-and-operations/real-time--market-data/market-reports/)
- [MISO real-time 5-min LMP public API](https://public-api.misoenergy.org/api/MarketPricing/GetRealTimeFiveMinExPost/Rolling)
- [gridstatus — MISO support](https://opensource.gridstatus.io/en/latest/autoapi/gridstatus/miso/index.html)
- [EIA Open Data](https://www.eia.gov/opendata/)
