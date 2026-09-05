# New York and Texas regional coverage

Flux should treat New York and Texas as two deployments of one national data
model, not as separate prototypes. The common spatial grain is county and
Census tract for impact/risk data, with ISO load zones and synthetic buses for
power-system analysis. Preserve every source's native identifiers and time
zone, then create explicit crosswalks instead of joining on names.

## Why these two states demonstrate generalizability

- Texas tests an energy-only market, large wind/solar fleets, extreme heat and
  cold, hurricanes, wildfire, long rural feeders, and natural-gas dependence.
- New York tests dense urban and underground networks, constrained downstate
  load pockets, hydro and nuclear generation, coastal flooding, winter storms,
  and a different ISO market design.
- National sources provide identical features in both states. State/ISO sources
  add resolution and allow us to test whether the pipeline adapts without
  changing its schema.

## Coverage matrix

| Modeling need | National backbone | New York addition | Texas addition | What it supports |
|---|---|---|---|---|
| Grid topology and power flow | GridSFM; HIFLD; EIA-860 | NYISO Gold Book and active-node metadata | ACTIVSg2000; ERCOT planning reports | Synthetic network scenarios and capacity constraints |
| Load, generation, and prices | EIA-930; EIA-923; EPA CAMPD | NYISO load, fuel mix, LBMP, interfaces | ERCOT load, generation, LMPs | A shared hourly operating table |
| Planned and forced outages | EAGLE-I; DOE-417 | NYISO outage schedules/events; NY DPS reports | ERCOT outages; PUCT service-quality reports | Event labels, restoration curves, reliability validation |
| Severe weather | HRRR; NOAA Storm Events; HURDAT2 | Same national feeds clipped to NY | Same national feeds clipped to TX | Comparable event features across climates |
| Flood and water exposure | FEMA NFHL; USGS hydrography | FEMA/USGS clipped to NY | TWDB statewide flood layers | Substation, line, plant, and access-route exposure |
| Wildfire and vegetation | LANDFIRE; USFS WHP; Annual NLCD | Northeast vegetation and disturbance tiles | Texas vegetation, fuel, and disturbance tiles | Vegetation-contact and fire-risk features |
| Fuel-supply dependence | EIA-860/923; EPA CAMPD | NYISO fuel mix | RRC pipelines, wells, and production | Gas-electric coupling and fuel constraint scenarios |
| Critical loads | CMS hospitals; EPA water systems; HHS emPOWER | NY facility/service-territory layers | Texas facility/service-territory layers | Consequence-weighted restoration and investment |
| Equity and vulnerability | ACS; CDC SVI; HHS emPOWER | NYSERDA disadvantaged communities | CDC SVI Texas extract | Distributional impact and fairness guardrails |
| Restoration logistics | OpenFEMA PA; FHWA NBI | NY utility circuit/action reports | Texas feeder/action reports | Damage-cost proxies and crew-access constraints |
| Long-term expansion | EIA-860M; LBNL queues/costs; NREL ATB/Cambium | NYISO Gold Book | ERCOT planning reports | Candidate projects, cost assumptions, and scenarios |

## Recommended acquisition order

1. Build the common operating table from EIA-930, EIA-860/923, EAGLE-I,
   HRRR, NOAA Storm Events, Census boundaries, ACS, CDC SVI, and HHS emPOWER.
2. Add NYISO and ERCOT hourly feeds using one canonical schema:
   `timestamp_utc`, `region`, `zone`, `metric`, `value`, `unit`, `source_id`.
3. Add static exposure layers: FEMA/USGS/LANDFIRE nationally, TWDB and RRC for
   Texas, and New York service territories/DAC boundaries for New York.
4. Join event outcomes from DOE-417, OpenFEMA, state reliability reports, and
   EAGLE-I. Keep missing outage observations distinct from zero outages.
5. Run identical scenarios in GridSFM state cases; use ACTIVSg2000 only as an
   additional Texas sensitivity case, never as the actual ERCOT network.

## Minimum viable demo

For a defensible hackathon demo, start with one winter event and one warm-season
event per state. Show baseline risk, a candidate intervention, and the resulting
change in unserved load and consequence-weighted critical-load exposure. Report
source coverage and uncertainty beside every comparison.

## Important constraints

- Public transmission geometry is not verified electrical connectivity and
  must not be used to infer an operational network.
- ISO public feeds do not expose SCADA, protection settings, or full CEII
  topology. The power-flow layer must remain explicitly synthetic.
- EAGLE-I and regulatory reliability reports have different utility and temporal
  coverage. Validate overlap before comparing outage rates.
- HHS emPOWER represents Medicare claims and may undercount all electricity-
  dependent residents; it is a vulnerability indicator, not a complete census.
- RRC pipeline geometry is approximate and explicitly unsuitable for excavation,
  surveying, or engineering decisions.
- CDC SVI percentiles are relative to their release year; do not compare scores
  across vintages as though they were an absolute time series.
