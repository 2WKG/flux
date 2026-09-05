---
title: "Source-backed multi-energy stress shortlist"
status: research
issue: 2WKG-279
created: 2026-09-05
scope: "Post-freeze scenario selection; not a replacement for the static Texas demo."
---

# Source-backed multi-energy stress shortlist

## Decision

Use one alternative operating condition after the frozen Texas cold-stress
comparison is stable: **September 6, 2023 evening net-load stress**.  It gives
the next implementation a clearly different mix of demand, wind, and solar
conditions without claiming a new grid model, an outage reconstruction, or
storage behavior the current static fixture cannot represent.

Keep **February 2021 cold weather and fuel/generator outages** as the first
historical anchor.  **Hurricane Beryl** is the next network-damage candidate.
Heat/drought and demand-growth cases remain research inputs, not executable
scenarios, until a source-backed mapping to fixture inputs is defined.

The rankings below choose what to configure and run, not what happened in the
real Texas grid.  Flux results remain comparative outputs on a synthetic
network.

## Ranked shortlist

| Rank | Candidate and category | Source-backed observed evidence | Geography and time coverage | Proposed fixture use — hypothetical, not observed | Feasibility and reason for rank |
|---|---|---|---|---|---|
| 1 | **February 2021 cold weather plus fuel/generator outage** (winter/cold; fuel/generator outage) | The joint [FERC/NERC final report](https://www.ferc.gov/sites/default/files/2021-12/Cold%20Weather%20Report_%202021_120821.pdf) documents extreme cold and freezing precipitation in its February 8–20 event window, as well as generation outages and derates by fuel. It reports gas and coal outages rising on February 15 and wind outages earlier in the event. | ERCOT is part of the report's Texas and South Central event area; the report's full window is February 8–20, 2021. The frozen fixture's four-hour cold stress is an illustrative snapshot, not a reconstruction of that window. | Keep the existing named cold preset as a static comparison. Any demand multiplier, duration, fuel-specific generator derate, or mapping of a published outage to a synthetic bus must be declared configuration, not attributed to FERC/NERC. | **Selected baseline.** This is a multi-energy stress across thermal/fuel supply and wind availability. It is the strongest historical anchor and already shapes the frozen demo; splitting freezing and fuel risk into independent event claims would be misleading. |
| 2 | **September 6, 2023 evening net-load stress** (low wind/solar; peak demand) | [ERCOT's contemporaneous release](https://www.ercot.com/news/release/2023-09-06-ercot-has-exited) says high heat-driven demand, lower wind generation, and declining solar generation at sunset contributed to low reserves, lower frequency, and an EEA 2; it also says no ERCOT-grid outages were necessary. Its reported September peak that day was 82,705 MW. | ERCOT-wide, September 6, 2023; the operational stress is an evening condition, not a claim about every hour or location. | Select one fixed stress snapshot from the documented condition. A load scale, wind/solar availability factors, dispatchable-resource availability, and any bus-level allocation are configuration assumptions. Do not label the resulting synthetic shed as an observed 2023 outage. | **First alternative to run.** It gives an explicit energy-mix contrast with rank 1: a heat/evening net-load condition with lower variable renewable output, rather than cold-driven thermal/fuel and wind failures. It fits a static DC comparison without an hourly weather, storage-state, or new-topology model. |
| 3 | **Hurricane Beryl outage and network-damage stress** (storm/network damage) | [DOE's July 9, 2024 Situation Report](https://www.energy.gov/sites/default/files/2024-07/TLP-CLEAR-DOE-Situation-Report-Beryl-02-clean.pdf) reports Beryl's July 8 landfall near Matagorda, Texas, winds, rainfall, storm surge and flooding, and about 2.108 million Texas customer outages as of July 9. [NOAA NCEI Storm Events](https://www.ncei.noaa.gov/stormevents/) is the authoritative event-record source for a later event-window and county join. | Southeast Texas; landfall July 8, 2024 and DOE's reported outage snapshot July 9. The DOE customer-outage count is not a transmission-element failure list. | A future configuration may choose a finite, explicitly hypothetical set of synthetic line or generator outages. It must not infer those elements from customer outages or present the set as observed damage. | **Second alternative.** Strong observed event and outage evidence, but lower readiness: a defensible synthetic-element mapping and disconnected-island handling are prerequisites. |
| 4 | **Heat/drought compound stress** (heat/drought) | [ERCOT's 2024 load forecast materials](https://www.ercot.com/gridinfo/load/forecast/2024) provide hourly base-load, PV, and net-load forecasts and separate peak-demand scenarios. [NCEI's Climate at a Glance](https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/) can supply documented temperature/precipitation context. Neither source alone establishes a Texas-wide drought-induced generator derate. | ERCOT forecast coverage is system-wide and 2024–2033; NCEI coverage depends on the selected Texas geography and period. Forecasts are projections, not measured history. | No configuration is proposed yet. Heat, drought, demand, and resource effects need individually named sources and a reviewed translation before any fixed factors are set. | **Deferred.** It is relevant but would otherwise combine observed weather with unsupported water-availability and resource-derate assumptions. |

## Category disposition and exclusions

| Required category | Disposition | Why it is not another independent scenario now |
|---|---|---|
| Winter/cold | Covered by rank 1. | The frozen cold snapshot remains illustrative; it is not a Uri replay. |
| Heat/drought | Deferred at rank 4. | No verified source-to-fixture mapping for drought-related availability is ready. |
| Storm/network damage | Covered by rank 3. | Customer outages cannot identify synthetic failed network elements. |
| Low wind/solar at peak demand | Covered by rank 2. | ERCOT documents the compound condition; the fixture still needs declared availability assumptions. |
| Fuel/generator outage | Covered with rank 1. | The final report identifies overlapping freezing and fuel causes, so a separate fuel-only event would fabricate independence. |
| Demand growth | **Deferred, forecast-only.** | ERCOT's [Capacity, Demand, and Reserves report](https://www.ercot.com/gridinfo/resource/2024) is a planning forecast, not observed demand. Use it only as a labeled future scenario input after the static comparison supports a separate demand setting. |

Do not select these in this work package:

- **A second state or topology:** Texas remains the only committed case; a second
  model would obscure scenario contrast with incompatible network resolution.
  New York and Minnesota remain future candidates, not this work package's
  scenarios.
- **Storage duration or state-of-charge behavior:** the current fixture has no
  stateful storage model. A power-only availability factor is not evidence of a
  storage dispatch result.
- **Historical reconstruction claims:** observed event sources define context and
  candidate windows. They do not validate synthetic bus placement, duration,
  availability factors, or simulated loss of load.

## Handoff to configuration and execution

The follow-on configuration should contain only a name, scenario class,
source links, observed-context notes, and declared fixture assumptions.  The
first execution pair is the existing cold snapshot and rank 2.  It should fail
explicitly if an assumed outage disconnects the synthetic network or leaves no
finite slack; it must not substitute zero impact.

## Source notes

- FERC/NERC is the primary final event investigation for February 2021 and
  supports the cold, freezing-precipitation, fuel, and generator-outage claims
  used above.
- ERCOT is the primary system operator for the September 2023 operating
  condition and for its load/resource forecasts.
- DOE's Beryl situation report supports the reported landfall, hazard, time,
  and customer-outage context only. NOAA NCEI is the source for a reproducible
  storm-event join if rank 3 is implemented.
