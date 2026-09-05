# Texas demo coverage

The current Flux demo is Texas-only. It uses ACTIVSg2000 as the synthetic
power-flow case and combines it with national and Texas-specific public data.
The ingestion interfaces should remain region-agnostic, but the demo must not
claim that cross-state generalizability has already been validated.

## Coverage matrix

| Modeling need | Primary sources | What it supports |
|---|---|---|
| Grid topology and power flow | ACTIVSg2000; HIFLD; EIA-860 | Synthetic network scenarios and capacity constraints |
| Load, generation, and prices | ERCOT; EIA-930; EIA-923; EPA CAMPD | Hourly operating conditions and market context |
| Planned and forced outages | EAGLE-I; DOE-417; ERCOT; PUCT reports | Event labels, restoration curves, and reliability validation |
| Severe weather | HRRR; NOAA Storm Events; HURDAT2 | Heat, cold, wind, precipitation, and hurricane features |
| Flood and water exposure | FEMA NFHL; USGS hydrography; TWDB | Asset and access-route exposure |
| Wildfire and vegetation | LANDFIRE; USFS WHP; Annual NLCD | Vegetation-contact and fire-risk features |
| Fuel-supply dependence | EIA-860/923; EPA CAMPD; Texas RRC | Gas-electric coupling and fuel-constraint scenarios |
| Critical loads | CMS hospitals; EPA water systems; HHS emPOWER | Consequence-weighted restoration and investment |
| Equity and vulnerability | ACS; CDC SVI; HHS emPOWER | Distributional impact and fairness guardrails |
| Restoration logistics | OpenFEMA PA; FHWA NBI; PUCT reports | Damage-cost proxies and crew-access constraints |
| Long-term expansion | EIA-860M; LBNL queues/costs; NREL ATB/Cambium; ERCOT planning | Candidate projects, costs, and future scenarios |

## Recommended acquisition order

1. Build the operating table from ERCOT, EIA-930, EIA-860/923, and EPA CAMPD.
2. Add event and outcome data from EAGLE-I, HRRR, NOAA Storm Events, DOE-417,
   and OpenFEMA. Keep missing outage observations distinct from zero outages.
3. Add static exposure layers from FEMA, USGS, LANDFIRE, TWDB, and Texas RRC.
4. Add consequence weights from Census/ACS, CDC SVI, HHS emPOWER, hospitals,
   and water systems.
5. Run cascade and intervention scenarios on ACTIVSg2000. Never present the
   synthetic topology as the actual ERCOT network.

## Minimum viable demo

Use Winter Storm Uri and Hurricane Beryl as contrasting Texas scenarios. Show
baseline risk, one candidate intervention, and the resulting change in unserved
load and consequence-weighted critical-load exposure. Report source coverage
and uncertainty beside each result.

## Important constraints

- Public transmission geometry is not verified electrical connectivity.
- ACTIVSg2000 is synthetic and does not represent the actual ERCOT network.
- Public data does not expose SCADA, protection settings, or full CEII topology.
- EAGLE-I and regulatory reports have uneven utility and temporal coverage.
- HHS emPOWER is claims-based and may undercount electricity-dependent people.
- RRC pipeline geometry is approximate and unsuitable for engineering use.
- CDC SVI percentiles are release-specific and not an absolute time series.
