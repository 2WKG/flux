---
title: "Texas + New York — data and scenario feasibility"
status: open — data gathered, decision deferred
issue: 2WKG-138
sibling: "docs/data/texas-minnesota-feasibility.md (2WKG-186)"
assessed: 2026-09-05
assessor: Ghadi Khoury
scope: "Next wave. Non-blocking for the current Texas demo."
---

# Texas + New York — feasibility

**Status: undecided. New York is not cancelled.** This records what was verified so the choice
of second state can be made on evidence later, alongside
`docs/data/texas-minnesota-feasibility.md`.

Everything below was verified by downloading and parsing the actual files.

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

## 2. Verified inventory

`microsoft/GridSFM_US_power_grid`, release `2026_05_07`, MIT. Downloaded and parsed 2026-09-05.

| | **New York** | Minnesota | Texas | ACTIVSg2000 (current) |
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

New York is a clean single-BA model with the highest BA coverage of the three — better than
Texas's 84 %.

---

## 3. The finding that matters most: New York does not solve cleanly

This is the one hard result separating New York from Minnesota.

| | AC-OPF `04h` | AC-OPF `16h` |
|---|---|---|
| **New York** | LOCALLY_SOLVED at **level 3, "Aggressive"** — 253 s | LOCALLY_SOLVED at **level 5, "Full relaxation"** — 322 s |
| Minnesota | LOCALLY_SOLVED at **level 0, "Strict"** — 21 s | LOCALLY_SOLVED at **level 0, "Strict"** — 21 s |
| Texas | LOCALLY_SOLVED at level 0, "Strict" — 45 s | LOCALLY_SOLVED at level 0, "Strict" — 51 s |

Zero units were decommitted in any case, so this is about constraint relaxation, not unserved
load.

**New York is one of the six single-state models that fail AC-OPF at the strictest relaxation
level** — the 42/48 figure in the GridSFM paper. Its peak case needs *full* relaxation to
converge at all.

Two consequences:

1. **A relaxed solution is a weaker basis for a siting comparison.** The whole demo rests on
   "adding 300 MW here versus there changes shed MW by this much." If the New York base case
   only converges with constraints relaxed, the delta is measured against a base that is
   already bending the physics. That is defensible only if stated plainly on screen.
2. **It is 12–15× slower than Minnesota despite being smaller.** 322 s versus 21 s, at 626
   buses versus 718. Every scenario re-run pays that cost. Task [S09] exists precisely to
   protect the runtime budget.

**645 generators on 626 buses** is also worth a look before committing — more generating units
than buses, presumably many small units mapped to shared buses. Not necessarily wrong, but
unexamined.

---

## 4. What New York has going for it

Recorded honestly, because the decision is still open:

- **Highest BA coverage of the three** — 98.1 %, against Texas's 84 %. Its demand comes from a
  single balancing authority (NYIS) via EIA-930 at 100 % coverage, rather than a multi-BA blend.
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
- **Texas BA coverage is 84 %**, so absolute shed MW is not comparable across states without
  saying so.
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

Both New York and Minnesota are available, MIT-licensed, and comparable in size. The trade is:

| | New York | Minnesota |
|---|---|---|
| Solves at strict relaxation | **No** — needs L3/L5 | **Yes** — L0 both hours |
| Solve time | 253–322 s | 21 s |
| BA coverage | 98.1 % | 97.4 % |
| Load scale vs Texas | ~1 : 2.7 | ~1 : 10 |
| Contrast | Urban density, different ISO, coastal | Same-storm Uri comparison, extreme cold |

**No recommendation is made here.** The Texas-only fallback in
`docs/data/texas-minnesota-feasibility.md` §6 remains the safe path either way, and the build
plan's rule stands: no second state until the complete Texas demo is frozen and rehearsed.

**What would settle it:** whether the demo needs a defensible per-site delta (favours Minnesota,
because a strict-relaxation base case is easier to defend) or a scale/urban contrast (favours
New York, where load is within a factor of three of Texas rather than a factor of ten).

---

## Sources

- [microsoft/GridSFM_US_power_grid — Hugging Face](https://huggingface.co/datasets/microsoft/GridSFM_US_power_grid)
- [Building Power Grid Models from Open Data (arXiv 2605.04289)](https://arxiv.org/html/2605.04289)
- [NYgrid — AndersonEnergyLab-Cornell (GitHub, MIT)](https://github.com/AndersonEnergyLab-Cornell/NYgrid)
- [An Open Source Representation for the NYS Electric Grid (arXiv 2112.06756)](https://arxiv.org/pdf/2112.06756)
- [Texas A&M Electric Grid Test Case Repository](https://electricgrids.engr.tamu.edu/electric-grid-test-cases/)
- [EIA Open Data](https://www.eia.gov/opendata/)
