---
title: "Texas + New York — data and scenario feasibility"
status: open — 2WKG-137 and 2WKG-140 pending; decision deferred
issue: 2WKG-138
sibling: "docs/data/texas-minnesota-feasibility.md (2WKG-186)"
assessed: 2026-09-05
assessor: Ghadi Khoury
scope: "Next wave. Non-blocking for the current Texas demo."
depends_on: "2WKG-137 (weather/overlays) and 2WKG-140 (demand history) — both still open"
---

# Texas + New York — feasibility

**Status: undecided. New York is not cancelled.** This records the available evidence and open
limitations for a later second-state decision, alongside
`docs/data/texas-minnesota-feasibility.md`.

**Open prerequisites:** 2WKG-137 must establish weather and overlay inputs; 2WKG-140 must
establish usable demand history. Both remain open, so this document does not close those risks.

---

## 1. Correction to the first version of this assessment

The original version of this document rejected New York on the grounds that *no public case
existed at a resolution comparable to ACTIVSg2000*. **That was wrong**, and the error is
recorded here rather than quietly dropped.

That assessment evaluated only the TAMU ACTIVSg family, Cornell's NYgrid, and NPCC-140. It
missed `microsoft/GridSFM_US_power_grid`, which publishes **single-state models for all 48
contiguous states** — New York included — under MIT licence. GridSFM had already been found
during the Brookhaven assessment (2WKG-133) and was not carried across.

New York is available. The question is whether it is the *best* second state, which is a
different and still-open question.

---

## 2. Provisional GridSFM inventory **[UNVERIFIED]**

`microsoft/GridSFM_US_power_grid`, release `2026_05_07`, MIT. The values below have no committed
parsing script, raw output, file manifest, or checksum in this PR. They are **[UNVERIFIED]** and
must not decide between states until reproduced from the pinned release.

| | **New York** | Minnesota | Texas | ACTIVSg2000 (current synthetic case) |
|---|---|---|---|---|
| Buses | **626** | 718 | 3,889 | 2,000 |
| Branches (lines + transformers) | **1,157** | 1,297 | 6,852 | 3,206 |
| Generators | **645** | 97 | 509 | 544 |
| Loads | 626 | 718 | 3,889 | 1,125 |
| Demand, `04h` off-peak | **19,115 MW** | 4,716 MW | 47,608 MW | — |
| Demand, `16h` peak | **27,746 MW** | 7,131 MW | 74,049 MW | 67,109 MW |
| Balancing authority | **NYIS** | MISO | ERCO | — |
| BA coverage | **98.1 %** | 97.4 % | 84.0 % | — |
| Demand source | **EIA-930 (NYIS) × 100 %** | Multi-BA (2 BAs) | Multi-BA (4 BAs) | — |
| Load allocation | `census` | `per_ba_census` | `per_ba_census` | — |
| DC lines / shunts | 0 / 510 | 2 / 666 | — | — |

The table records GridSFM metadata only. It does not interpret the reported BA-coverage field as
a fraction of demand represented by the model.

---

## 3. Provisional solver concern **[UNVERIFIED]**

These provisional results are a potential difference between New York and Minnesota.

**[UNVERIFIED]** The solve results below require the same pinned-release reproduction artifact as
the inventory before they can serve as state-selection evidence.

| | AC-OPF `04h` | AC-OPF `16h` |
|---|---|---|
| **New York** | LOCALLY_SOLVED at **level 3, "Aggressive"** — 253 s | LOCALLY_SOLVED at **level 5, "Full relaxation"** — 322 s |
| Minnesota | LOCALLY_SOLVED at **level 0, "Strict"** — 21 s | LOCALLY_SOLVED at **level 0, "Strict"** — 21 s |
| Texas | LOCALLY_SOLVED at level 0, "Strict" — 45 s | LOCALLY_SOLVED at level 0, "Strict" — 51 s |

The reported unit-commitment values should be reproduced before drawing conclusions about
constraint relaxation or unserved load.

If reproduced, the reported result would place New York among the six single-state models that
do not solve at the strictest relaxation level in the GridSFM paper's 42/48 summary.

Two consequences to validate if the result reproduces:

1. **A relaxed solution would be a weaker basis for a siting comparison.** The whole demo rests on
   "adding 300 MW here versus there changes shed MW by this much." If the New York base case
   only converges with constraints relaxed, the delta is measured against a base that is
   already bending the physics. That is defensible only if stated plainly on screen.
2. **It may be slower than Minnesota despite being smaller.** The reported runtime values need
   reproduction before they affect the runtime budget.

The reported generator and bus counts are **[UNVERIFIED]** and need inspection after the
reproducibility artifact exists.

**Interconnection boundary caveat:** New York is part of the Eastern Interconnection and has
substantial interstate flows. Any New York demand or shedding result is sensitive to imports
across boundaries that this state model would not represent. That limitation remains part of the
second-state decision.

---

## 4. What New York has going for it

Recorded honestly, because the decision is still open:

- **Single-BA structure** — the provisional metadata identifies NYIS as the balancing authority;
  this is not a claim about the fraction of demand represented.
- **Genuine structural contrast**: dense urban and underground networks, constrained downstate
  load pockets, hydro and nuclear generation, coastal flooding exposure, and a different ISO
  market design from ERCOT.
- **NYISO publishes rich public data** — load, fuel mix, LBMP, interface flows, and the Gold
  Book planning dataset.
- **Cornell's NYgrid** (MIT) remains available as a validated cross-check: reduced from
  NPCC-140, enforcing the 11 NYISO zonal interface constraints, validated against real power
  flow and LMP data. Too coarse to be the primary case, useful as a sanity check. It is MATLAB,
  so running it is not free.

---

## 5. Shared constraints

These apply to any second state and are documented once in
`docs/data/texas-minnesota-feasibility.md` §3:

- **All GridSFM models carry `target_datetime = 2024-07-15T16:00`** — the shipped demand is a
  July afternoon, not winter, and `04h`/`16h` is a pair of snapshots, not a time series.
- **Demand is allocated by census population**, not metered per bus.
- **Reported BA coverage is metadata, not a demand-truncation fraction.** The cases have
  different construction, so absolute shed-MW outputs are case-specific rather than a
  cross-state comparison.
- **Format**: GridSFM ships PowerModels JSON with MATPOWER structure; pandapower reads MATPOWER
  `.m`. A small converter is needed either way. This cost is identical for New York and
  Minnesota.

**County resolution:** Texas 254 counties, Minnesota 87, New York 62. All three join on the
existing `buses.county_fips` spine. The national sources in
`docs/data/industry-urban-rural-population-inputs.md` cover every state at no extra cost.

---

## 6. Scenario inputs

- **Energy-source shift — available as measured history.** EIA state-level generation by fuel
  and prime mover; MWh and MW; monthly and annual; public domain. API caps at 5,000 rows per
  request (300 XML); bulk refreshes twice daily, 05:00 and 15:00 ET. **EIA also publishes AEO
  projections — modelled futures that may never sit beside historical generation unlabelled.**
- **Economic disruption — no dataset exists.** It is a declared scenario assumption with stated
  magnitude, duration and rationale, not an input. QCEW measures jobs by workplace and PEP
  measures estimated population; neither measures disruption, and neither measures megawatts.

---

## 7. Open decision

Both New York and Minnesota are available under MIT licence. The following comparison contains
provisional GridSFM values and must not decide between states until reproduced:

| | New York | Minnesota |
|---|---|---|
| Reported solve at strict relaxation **[UNVERIFIED]** | **No** — needs L3/L5 | **Yes** — L0 both hours |
| Reported solve time **[UNVERIFIED]** | 253–322 s | 21 s |
| Reported BA coverage **[UNVERIFIED]** | 98.1 % | 97.4 % |
| Load scale vs Texas | ~1 : 2.7 | ~1 : 10 |
| Contrast | Urban density, different ISO, coastal | Same-storm Uri comparison, extreme cold |

**No recommendation is made here.** The Texas-only fallback in
`docs/data/texas-minnesota-feasibility.md` §6 remains the safe path either way, and the build
plan's rule stands: no second state until the complete Texas demo is frozen and rehearsed.

**What would settle it:** a reproducible solver comparison, resolution of 2WKG-137 and
2WKG-140, and an explicit treatment of New York's interconnection-boundary limitation.

---

## Sources

- [microsoft/GridSFM_US_power_grid — Hugging Face](https://huggingface.co/datasets/microsoft/GridSFM_US_power_grid)
- [Building Power Grid Models from Open Data (arXiv 2605.04289)](https://arxiv.org/html/2605.04289)
- [NYgrid — AndersonEnergyLab-Cornell (GitHub, MIT)](https://github.com/AndersonEnergyLab-Cornell/NYgrid)
- [An Open Source Representation for the NYS Electric Grid (arXiv 2112.06756)](https://arxiv.org/pdf/2112.06756)
- [Texas A&M Electric Grid Test Case Repository](https://electricgrids.engr.tamu.edu/electric-grid-test-cases/)
- [EIA Open Data](https://www.eia.gov/opendata/)
