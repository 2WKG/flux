# 04 — Siting Engine (`siting/`)

> **Scope order:** Minnesota is the current case ([`10-minnesota-demo.md`](10-minnesota-demo.md)); Texas is second; further states follow. Texas references below describe the second case, not the current one.

Status: draft · Scope: Texas-first (ERCOT / ACTIVSg2000) · Owner: siting team

## Purpose

Rank places to put the next firm (nuclear) gigawatt in Texas with **two independent scores** per
candidate site: a **safety/buildability score** (an open-data re-implementation of the OR-SAGE
exclusion-and-avoidance criteria — ORNL/TM-2011/157 large-reactor and ORNL/TM-2012/403 SMR values) and a **grid-value score** (drop a 300 MW or 1 GW unit at
the site's bus in the twin, re-run the stress scenarios from spec 03, and measure loss-of-load
reduction, congestion relief, and black-start reach). Attach a **regulatory-path label** to each
site. Expose `score_site(site_id, unit_mw, scenario_id)` to the copilot and persist everything to
`site_candidates` / `site_scores`.

Three modules: `siting/candidates.py`, `siting/safety.py`, `siting/grid_value.py`, plus
`siting/rank.py` (combination + label) and `siting/tools.py` (copilot wrapper).

## Inputs

| Input | Source | Notes |
|---|---|---|
| Retired / retiring coal units, existing nuclear | EIA-860 via PUDL (`data/raw/pudl/` — `core_eia860__scd_generators`, `core_eia860__scd_plants`) filtered `state='TX'`, `prime_mover/fuel` coal, `operational_status in (retired, proposed retirement)`, `retirement_date` ≥ 2010 or planned ≤ 2032 | Gives plant lat/lon, nameplate (→ `capacity_slot_mw`), `eia_plant_id`. |
| DOE federal sites | Static CSV `data/raw/siting/doe_federal_sites.csv` (INL, Oak Ridge, Paducah, Savannah River — DOE's July 2025 selections for AI data-center + energy projects, verified) | None are in Texas; they are loaded for the national scale slide and the `kind='doe_federal'` code path, and for Pantex (Amarillo, TX) as the one Texas DOE/NNSA site **[UNVERIFIED whether Pantex is in scope of any DOE authorization; label it `doe_federal` with a caveat]**. Pantex's utility is SPS (DOE FEMP page), i.e. SPP, NOT ERCOT — `interconnection='spp'`, `bus_id = NULL`. |
| DoD installations | Public DoD installation boundaries (`data/raw/dod/`; the "Military Installations, Ranges, and Training Areas" public layer) filtered to Texas, area ≥ 5 000 acres. Verified against the Texas Comptroller 2021 military-economy tables: Fort Hood (~217 000 ac; Fort Cavazos May 2023 → Fort Hood again July 28, 2025, army.mil), Fort Bliss (~1.1 M ac incl. NM), JBSA (> 46 000 ac), Red River AD (15 375 ac), Dyess (6 409 ac), Sheppard (5 736 ac), NAS Corpus Christi (5 662 ac), Laughlin AFB (5 347 ac — was missing from this list); Goodfellow (1 235 ac) is below the cut. **Interconnection (verified via PUC Texas "Utilities Outside ERCOT" + El Paso Electric):** Fort Bliss is El Paso Electric / WECC and Red River AD is SWEPCO / SPP — both OUTSIDE ERCOT; the rest are ERCOT (Oncor / CPS / AEP Texas). | Also the `critical_loads(kind='dod')` source in spec 01. Rows carry `interconnection in {ercot, spp, wecc}`; non-ERCOT rows get `bus_id = NULL` (see candidates step 4). |
| Population | Census block-group or tract population + geometry (`data/raw/census/`) | For the 20-mile density criterion. |
| Seismic | USGS NSHM 2023 PGA (2 % in 50 yr) raster or county summary → `hazard_static.seismic_pga` | |
| Floodplain | FEMA NFHL 100-yr zones (`data/raw/fema_nfhl/`, Texas subset) — fallback: FEMA NRI riverine/coastal flood risk index at county level if NFHL download is too large | |
| Cooling water | NHDPlus flowlines with mean annual flow (`data/raw/nhd/`), major reservoirs (NHD waterbody ≥ 2 km²), Gulf coast | |
| Protected land | PAD-US (GAP status 1–2 + all federal designations) | |
| Slope | USGS 3DEP 1-arc-second DEM → slope at site and within 1 km | |
| Wildfire | USFS Wildfire Hazard Potential → `hazard_static.wildfire_hazard` | |
| State moratorium | Static table `data/raw/siting/state_moratoria.csv` (state, status, statute) — Texas: none | |
| Twin | spec 03 `run_scenario`, `run_cascade` | For grid value. |
| DuckDB | `buses`, `lines`, `gens`, `loads`, `counties`, `critical_loads`, `scenarios`, `hazard_static`, `cascade_runs` | |

## Outputs

- `site_candidates(site_id, name, kind[coal_retired|coal_retiring|nuclear_existing|doe_federal|dod], lon, lat, county_fips, bus_id, capacity_slot_mw)` — `bus_id` = nearest twin bus with `base_kv ≥ 138` within 40 km; else NULL and the site is `unconnected` (still safety-scored, grid-value NULL).
- `site_scores(site_id, scenario_id, unit_mw, safety_score, safety_flags_json, grid_value_score, lol_reduction_mwh, congestion_relief_pct, blackstart_reach_mw)` — one row per (site, scenario, unit size). `scenario_id='all'` rows hold the scenario-averaged values used for ranking.
  - `safety_flags_json`: list of `{"criterion": str, "kind": "exclusion"|"avoidance", "value": float, "threshold": float, "passed": bool, "source": str}`.
- `data/parquet/site_scores.parquet` and `site_cards/<site_id>.json` (for the front end: three reasons, three risks, regulatory path, DoD installations covered).
- `SiteScore` dataclass returned by `score_site`.

## Algorithm or Design

### `siting/candidates.py`

1. Coal: from PUDL generators, group by plant; `kind = coal_retired` if all coal units retired,
   `coal_retiring` if any unit has a planned retirement ≤ 2032; `capacity_slot_mw` = sum of
   retired/retiring nameplate (a proxy for the interconnection/right-of-way slot). **CORRECTED
   expectation (owner/ERCOT/PUC sources checked 2026-09-05; the PUDL/EIA-860M pull is still the
   authoritative list):** the filter yields roughly **12 plants, not 15–25** —
   `coal_retired`: Monticello (Jan 2018), Sandow (Jan 2018), Big Brown (Feb 2018), Gibbons Creek
   (mothballed 2018, permanent retirement notice to ERCOT eff. Oct 2019), J.T. Deely (CPS, Dec
   2018 — was missing from the old list), Oklaunion (ERCOT NSO: retired Oct 1, 2020), Pirkey
   (SWEPCO, 2023), plus Harrington (Xcel/SPS, converted to gas by May 2025 — EIA-860 shows it as
   a fuel switch, not a retirement; classify as `coal_retired` only if the PUDL rows say so);
   `coal_retiring`: Coleto Creek (Vistra: retire 2027 / gas repower), Welsh (SWEPCO: off coal
   2028), J.K. Spruce 1 (CPS: shut by 2028), Tolk (Xcel/SPS: 2028 per NM PRC settlement).
   Martin Lake, W.A. Parish, San Miguel, Limestone, Oak Grove, Twin Oaks and Fayette/Sam Seymour
   have **no announced retirement date** and therefore do NOT pass this filter; they appear only
   if `include_operating=True`. **Four of the twelve are outside ERCOT** (Pirkey, Welsh in
   SWEPCO/SPP; Harrington, Tolk in SPS/SPP — PUC Texas lists SWEPCO and SPS as utilities outside
   ERCOT) and are tagged `interconnection='spp'`. Individual unit-level statuses remain
   **[UNVERIFIED against EIA-860M]** until the PUDL pull runs.
2. Nuclear existing: Comanche Peak (Somervell County, 2 units, 1 259 + 1 245 MWe after the 2008
   NRC uprate — NRC News 08-122) and South Texas Project (Matagorda County, 2 units, ~2 700 MWe
   combined — STPNOC; STP Unit 1 tripped 05:37 Feb 15, 2021 in Uri from frozen feedwater
   pressure-sensing lines); both ERCOT. `capacity_slot_mw = 1200` per proposed added unit is a
   design placeholder **[UNVERIFIED — the historical COL applications were 2 × 1 350 MWe ABWR at
   STP 3&4 and 2 × 1 700 MWe US-APWR at Comanche Peak 3&4; use those if the card cites them]**.
3. DOE federal, DoD: from the static/boundary sources above; DoD `lon,lat` = boundary centroid.
4. `bus_id` assignment: KD-tree over `buses` filtered `base_kv >= 138`; take nearest within 40 km.
   Verified against the twin: `base_kv >= 138` keeps the 161/230/500 kV buses (725 of 2000) and
   drops all 826 115 kV buses — intentional (a GW unit connects at ≥ 161 kV here), state it on the
   card. Sites with `interconnection != 'ercot'` get `bus_id = NULL` regardless of distance:
   ACTIVSg2000 is "entirely synthetic, built on the footprint of Texas" and "bears no relation to
   the actual grid" (TAMU case page) — it does not model the SPP/WECC parts of Texas as separate
   interconnections, so a synthetic bus near Amarillo or Texarkana is not that site's grid.
   **[UNVERIFIED whether the synthetic footprint even excludes El Paso / the Panhandle — TAMU's
   page does not say; check `buses.lon/lat` extent once spec 01 lands.]**
5. Idempotent upsert into `site_candidates` keyed by `site_id` (`f"{kind}:{eia_plant_id or slug}"`).

### `siting/safety.py` — OR-SAGE on open layers

OR-SAGE defines site selection & evaluation criteria (SSEC) as **exclusionary** (hard fail) or
**avoidance** (penalty). **CORRECTED citations (primary PDFs read 2026-09-05):**
ORNL/TM-2012/403 (Sept 2012, Belles/Mays/Omitaomu/Poore) is "Updated Application of Spatial
Data Modeling and GIS for Identification of Potential Siting Options for **Small Modular
Reactors**" (https://info.ornl.gov/sites/publications/files/Pub39008.pdf); the "Various
Electrical Generation Sources" title belongs to the LARGE-reactor study ORNL/TM-2011/157/R1
(May 2012, Mays et al., https://info.ornl.gov/sites/publications/files/Pub30613.pdf). DOE's
Sept 2024 "Evaluation of Nuclear Power Plant and Coal Power Plant Sites for New Nuclear
Capacity" is **ORNL/SPR-2024/3483** (Sept 3, 2024; Omitaomu, Belles, Davidson — ORNL — and
T.K. Kim — ANL) and it uses **OR-SAGE, not STAND** (the string "STAND" does not occur in the
report; STAND is a separate INL/NRIC tool — its criteria are **[UNVERIFIED]** here and nothing
below relies on them). Headline numbers of that report, for the national slide: 128–174 GWe
backfit potential at 145 coal-plant sites; 60–95 GWe at 54 operating + 11 retired NPP sites.
The Sept 2022 predecessor INL/RPT-22-67964 (INL/ANL/ORNL) screened 157 retired + 237 operating
coal sites and found 64.8 GWe at 125 retired and 198.5 GWe at 190 operating sites amenable.
The OR-SAGE thresholds, quoted from the two ORNL reports (§2.1 of each):

| SSEC | Large reactor (ORNL/TM-2011/157/R1; EPRI 2002 basis) | SMR ≤ 540 MW(e) (ORNL/TM-2012/403) |
|---|---|---|
| Population | > 500 people/sq mi excluded, incl. a 20-mile buffer | same, incl. a 10-mile buffer |
| SSE PGA (2 % in 50 yr) | > 0.3 g excluded | > 0.5 g excluded |
| Slope | > 12 % (~7°) excluded ("based on 2002 EPRI guidance") | > 18 % (~10°) excluded |
| Cooling water makeup | > 20 miles from a source with ≥ 200 000 gpm excluded | ≥ 65 000 gpm |
| Wetlands / open water; protected lands; 100-yr floodplain; moderate-OR-high landslide susceptibility | excluded | excluded |
| Hazardous facilities | airports 5 mi, oil refineries 1 mi — *avoided* | same |
| Fault lines | standoff by fault length (excluded) | same |

The PDF is NOT in the repo (there is no `data/raw/siting/` yet); download it from the ORNL URL
above into `data/raw/siting/ORNL-TM-2012-403.pdf` (7.7 MB; `pypdf` extracts the text cleanly).
Each criterion below names its open source; thresholds still marked **[UNVERIFIED]** are our
own design choices with no OR-SAGE/NRC number behind them:

| # | Criterion | Kind | Rule (site passes if …) | Open source |
|---|---|---|---|---|
| S1 | Population density | exclusion | pop density within 20-mile radius ≤ 500 people/sq mi (RG 4.7 **Rev 4, Feb 2024**, ML23348A082: "averaged over any radial distance out to 20 miles (cumulative population at a distance divided by the area at that distance), is at most 500 persons per square mile", at initial site approval and ~5 years after — verified; note RG 4.7 is a cumulative average at EVERY radius ≤ 20 mi, so the test is `max over r ≤ 20 mi`, not one 20-mile disc; OR-SAGE's variant is a 20-mile buffer around > 500 ppsm cells) | Census tracts, area-weighted |
| S2 | Population center | avoidance | no place ≥ 25 000 residents within 4 miles (10 CFR 100.21(b), verified: population center distance "must be at least one and one-third times the distance from the reactor to the outer boundary of the **low population zone**" — LPZ, not EAB; §100.3 defines a population center as "more than about 25,000 residents". The 4-mile figure is our proxy because the LPZ is site-specific **[UNVERIFIED distance — replace with 1⅓ × the applicant's LPZ radius when known]**) | Census places |
| S3 | Seismic | exclusion | SSE PGA (2 % in 50 yr) ≤ 0.3 g for the 1 GW unit (ORNL/TM-2011/157 large-reactor SSEC, verified), ≤ 0.5 g for the 300 MW unit (ORNL/TM-2012/403 SMR SSEC, verified) — threshold is a function of `unit_mw` | USGS NSHM 2023 |
| S4 | Floodplain | exclusion | site not inside 100-yr floodplain | FEMA NFHL / NRI fallback |
| S5 | Cooling water | avoidance | within 20 miles of a makeup source: a stream with low flow ≥ 200 000 gpm for the 1 GW unit / ≥ 65 000 gpm for the 300 MW unit (OR-SAGE values, verified; OR-SAGE treats this as an *exclusion* and uses low stream flow, not mean flow — our avoidance/mean-flow reading is a deliberate softening and the card says so), or a reservoir ≥ 2 km² **[UNVERIFIED size — our choice]** or the Gulf coast | NHDPlus |
| S6 | Protected land | exclusion | site not within PAD-US GAP 1–2 or national park/wilderness/wildlife refuge | PAD-US |
| S7 | Slope | exclusion | mean slope within 1 km ≤ 12 % for the 1 GW unit (ORNL/TM-2011/157: "limited the slope to 12% based on 2002 EPRI guidance" — EPRI 1006878, verified only as ORNL's attribution; the EPRI PDF itself is not public) / ≤ 18 % for the 300 MW unit (ORNL/TM-2012/403) | 3DEP DEM |
| S8 | Wildfire | avoidance | USFS WHP class ≤ "moderate" | USFS WHP |
| S9 | Hazardous facilities | avoidance | no airport within 5 miles and no oil refinery within 1 mile (OR-SAGE distances, verified; ORNL/SPR-2024/3483 flags 1–10 miles); military ordnance and LNG/chem facilities within 5 miles are our addition **[UNVERIFIED distance]** | HIFLD/OSM |
| S10 | Landslide | avoidance | not in USGS landslide-susceptibility "moderate" or "high" (OR-SAGE excludes both, verified; we soften exclusion → avoidance, deliberately) | USGS |
| S11 | State moratorium | exclusion | state has no new-nuclear moratorium (Texas: pass) | static table |
| S12 | Wetlands | avoidance | site footprint (1 km²) < 25 % NWI wetlands (OR-SAGE excludes wetlands/open water outright at cell level; the 25 % footprint rule is ours **[UNVERIFIED]**) | USFWS NWI |

Scoring: `safety_score = 0` if any exclusion fails; else
`100 × ∏(avoidance passed ? 1 : penalty_i)` with `penalty = {S2: 0.6, S5: 0.5, S8: 0.8, S9: 0.7, S10: 0.8, S12: 0.9}`.
Every criterion emits one `safety_flags_json` entry with the measured value, threshold and source
so the card can say "population density 61 /sq mi within 20 mi (limit 500)".

Population-density special case (**CORRECTED**, primary sources read 2026-09-05): 10 CFR
**53.530 is already FINAL**, not proposed — Part 53 was published at 91 FR 15696 (March 30,
2026, NRC-2019-0062) and took effect April 29, 2026; §53.530(b) says the site must either
"(1) provide a population center distance of at least one and one-third times the distance …
or (2) be found acceptable to the NRC based on assessments of societal risks in comparison to
societal benefits for the specific site", and (c) "reactor sites should be located away from
very densely populated centers or otherwise be shown to be acceptable by assessments of
societal risks in comparison to societal benefits". The **July 16, 2026 proposed rule**
("Modernizing Reactor Licensing, Safety Oversight, and Siting Practices", 91 FR 44560–44716,
NRC-2025-0975, RIN 3150-AL44, comments closed Aug 31, 2026; 157 FR pages — the 553-page figure
is the pre-publication PDF ML26176A438) does not touch §53.530; it proposes the same
societal-risk alternative for Part 50/52 applicants by revising **10 CFR 100.10, 100.11(a)(3),
100.21(b) and 100.21(h)**, and explicitly leaves the RG 4.7 500 ppsm number to future
implementing guidance. So: an S1 failure is downgraded from exclusion to avoidance
(`penalty 0.4`) and the site's regulatory path is labelled `nrc_tier2_societal_risk` (see
labels below); the card states whether that rests on final §53.530(b)(2) (a Part 53
application) or on the proposed §100.21(b)(1)(ii) (Part 50/52). The Tier 1/Tier 2 nomenclature
is the pitch's term — neither rule uses it (verified absent from the rule texts read); the card
prints the §53.530 / proposed §100.21 language.

### `siting/grid_value.py` — the number nobody else produces

For `(site, unit_mw, scenario_id)`:

1. `net_with = add_unit(net, bus_id, unit_mw)` — `pp.create_gen(net, bus, p_mw=unit_mw,
   vm_pu=1.0, max_p_mw=unit_mw, min_p_mw=0.3*unit_mw, name=site_id, element_id=f"gen:{site_id}")`
   with fuel `nuclear` (so spec 03's cold-weather derate treats it as nuclear).
   Dispatch: existing generators are scaled down pro-rata by `unit_mw` so total gen still equals
   total load (DC PF constraint); this is the honest "displaces marginal gen" assumption.
2. `base = run_scenario(scenario_id, seed=0, net=base_net, write=False)`
   `with_ = run_scenario(scenario_id, seed=0, net=net_with, write=False)` — (amendment A1 in 00-overview: after ranking, re-run the #1 site with `write=True`, `run_id="uri_2021-s0-cf-<site_id>-1000"`, `counterfactual_site_id=<site_id>` so the UI toggle has a row) — **same seed, so the
   weather sample is identical** and the difference is purely the do-operation.
3. `lol_reduction_mwh = Σ_h (base.lost_load_mw − with_.lost_load_mw)` (hourly rows, 1 h steps).
4. `congestion_relief_pct = 100 × (1 − Σ_h Σ_lines max(0, loading_with − 90) / Σ_h Σ_lines max(0, loading_base − 90))`
   — relief of the >90 %-loading exceedance mass on the base case; 0 if base has none.
5. `blackstart_reach_mw` = load (MW, base scaled at scenario peak hour) at buses reachable from the
   site's bus through in-service ≥ 138 kV lines within 3 hops AND within `unit_mw` cumulative
   load (a greedy BFS that "energizes" nearest load first). Proxy for cranking-path reach; it is
   a graph metric, not a transient-stability claim, and the card says so.
6. `critical_loads_protected` = DoD/hospital/water `cl_id`s that are in
   `base.critical_loads_lost` but not `with_.critical_loads_lost`.
7. `grid_value_score` (0–100) = `40 × z(lol_reduction_mwh) + 30 × z(congestion_relief_pct) +
   20 × z(blackstart_reach_mw) + 10 × min(1, len(critical_loads_protected)/3)` where `z` is
   min–max over all candidate sites for the same `(scenario_id, unit_mw)`; `scenario_id='all'`
   averages over `uri_2021`, `beryl_2024`, `helene_2024` (Helene did not touch Texas — its
   ERCOT-scaled run is near-zero LOL and is kept so the scoring code is scenario-agnostic;
   ranking weight for Helene in Texas = 0 in `params.yaml`).

Runtime (CORRECTED — spec 03 re-measured pandapower DC at **9–14 ms/solve warm**, the earlier
0.84 s was the one-time first-call cost; lightsim2grid cannot load this net, see spec 03 Speed):
3 scenarios × ~12–20 sites × 2 unit sizes × full 168-h replay ≈ 500–850 solves each ≈ 6–12 s per
site-scenario → the full-replay batch is ≈ 10–25 min of pure solves. So:
(a) grid value uses **stress hours only** via `run_scenario(..., hours=stress_hours(sid, 12))`:
the 12 hours with highest `base.lost_load_mw` per scenario (pre-computed from spec 03's baseline
`cascade_runs`) → 12 × ~4 stages ≈ 50 solves ≈ **< 1 s** per site-scenario with pandapower;
(b) the base run per (scenario, hours) is computed once and shared across all sites;
(c) results are cached in `site_scores` and `score_site` re-runs only on cache miss or `force=True`.
Whole Texas batch target: **< 5 min with pandapower on stress hours** (the 20 min budget in
acceptance 6 is the hard ceiling and carries 4× headroom); a full-replay batch is an overnight
option, stated in the run summary.

### `siting/rank.py` — combination + regulatory path

`combined = safety_score^0.5 × grid_value_score^0.5` (geometric mean; a zero safety score
zeros the site). Ties broken by `lol_reduction_mwh`.

Regulatory-path label (one per site, first match):

| Label | Rule | Basis (verified unless marked) |
|---|---|---|
| `doe_authorized_federal_land` | `kind='doe_federal'` | DOE's July 24, 2025 selection of INL / Oak Ridge Reservation / Paducah / Savannah River for AI data-center + energy projects (energy.gov, verified). **CORRECTED EO:** the DOE-site pathway is **EO 14299** "Deploying Advanced Nuclear Reactor Technologies for National Security" (May 23, 2025, 90 FR 22581), §4(b)–(c): DOE to "site, approve, and authorize … privately funded advanced nuclear reactor technologies at Department of Energy-owned or controlled sites for the purpose of powering AI infrastructure". EO 14301 (90 FR 22591) is DOE reactor *testing* and §3 limits DOE jurisdiction to reactors that "do not produce commercial electric power"; EO 14300 is NRC reform; EO 14302 (90 FR 22595) is the industrial base. **Resolved: DOE authorization does NOT substitute for NRC licensing of commercial grid units** — the label applies only to DOE-regulated reactors serving DOE-site/AI loads, and the card must say so. |
| `advance_act_brownfield` | `kind in (coal_retired, coal_retiring)` and S1–S7 pass | ADVANCE Act (P.L. 118-67, Div. B, July 9, 2024) **§206** "Regulatory Issues for Nuclear Facilities at Brownfield Sites" (verified, congress.gov): NRC must evaluate within 1 year what regulation/guidance changes are needed "to enable efficient, timely, and predictable licensing reviews" at "covered sites" (brownfield and/or retired fossil-fuel sites), report within 14 months, and within 2 years "develop strategies or initiate rulemaking" — it mandates a *process*, not a finished pathway. **CORRECTED fee claim:** §201 caps the hourly fee for advanced-reactor applicants at "the hourly rate for mission-direct program salaries and benefits" (effective Oct 1, 2025); the statute contains no percentage — NRC's FY2025 fee rule makes it $148/hr vs $318/hr, "an over 50 percent reduction" (≈ 53 %), not 55 %. |
| `nrc_tier1_low_density` | S1 passes and S2 passes, non-federal | Existing preference for low-population siting (RG 4.7 Rev 4; 10 CFR 100.21(h) "Reactor sites should be located away from very densely populated centers. Areas of low population density are, generally, preferred." — verified); pitch's "Tier 1" |
| `nrc_tier2_societal_risk` | S1 or S2 fails but all other exclusions pass | Final 10 CFR 53.530(b)(2)/(c) societal risk-vs-benefit alternative (verified, 91 FR 15696) for Part 53 applicants; proposed 10 CFR 100.21(b)(1)(ii) (91 FR 44560, July 16, 2026) for Part 50/52 |
| `dod_installation` | `kind='dod'` | EO 14299 §3(a) (verified): the Army "shall commence the operation of a nuclear reactor, regulated by the United States Army, at a domestic military base or installation no later than September 30, 2028". Army Janus microreactor program / Project Pele context **[UNVERIFIED program details]**; card notes DoD sites may use DOE/DoD authorization only for the installation's own load, not commercial units |
| `excluded` | any non-population exclusion fails | — |

Site card: three biggest reasons = top-3 positive contributors among `{lol_reduction_mwh,
congestion_relief_pct, blackstart_reach_mw, critical_loads_protected, capacity_slot_mw, S5 pass}`;
three biggest risks = failed/penalized flags plus `unconnected` if applicable. Citations are
strings the copilot can paste (all verified 2026-09-05): `10 CFR 100.21(b)` and `10 CFR 100.3`
(population center distance / > 25 000 residents), `10 CFR 53.530(b)(2)` (91 FR 15696, final
Mar 30 2026), `NRC proposed rule 91 FR 44560 (July 16, 2026) — proposed 10 CFR 100.21(b)(1)(ii)`,
`Reg Guide 4.7 Rev 4 (Feb 2024, ML23348A082)`, `ORNL/TM-2011/157/R1` (large-reactor SSEC),
`ORNL/TM-2012/403` (SMR SSEC), `ORNL/SPR-2024/3483` (DOE Sept 2024 NPP/CPP site evaluation),
`INL/RPT-22-67964` (Sept 2022 coal-to-nuclear), `ADVANCE Act of 2024 §201, §206 (P.L. 118-67)`,
`EO 14299 (90 FR 22581)`.

## Interfaces

```python
# siting/candidates.py
def build_candidates(state: str = "TX", duck_path: Path = Path("data/duck/grid.duckdb"),
                     pudl_dir: Path = Path("data/raw/pudl")) -> pandas.DataFrame   # also upserts site_candidates
def assign_bus(lon: float, lat: float, min_kv: float = 138.0, max_km: float = 40.0) -> str | None

# siting/safety.py
@dataclass(frozen=True)
class SafetyFlag: criterion: str; kind: Literal["exclusion","avoidance"]; value: float; threshold: float; passed: bool; source: str
@dataclass(frozen=True)
class SafetyResult: site_id: str; safety_score: float; flags: list[SafetyFlag]; population_downgraded: bool
def score_safety(site_id: str, lon: float, lat: float, layers: SitingLayers, unit_mw: int = 1000,   # S3/S5/S7 thresholds depend on unit size (OR-SAGE large vs SMR)
                 proposed_rule_mode: bool = True) -> SafetyResult   # True = apply the §53.530(b)(2) / proposed §100.21(b)(1)(ii) societal-risk downgrade
def load_layers(raw_dir: Path = Path("data/raw")) -> SitingLayers     # loads/caches all rasters + vectors once
def population_density_within(lon: float, lat: float, radius_mi: float, tracts) -> float   # exposed for tests

# siting/grid_value.py
@dataclass(frozen=True)
class GridValueResult:
    site_id: str; scenario_id: str; unit_mw: int
    lol_reduction_mwh: float; congestion_relief_pct: float; blackstart_reach_mw: float
    critical_loads_protected: list[str]; grid_value_score: float | None; hours_evaluated: list[int]
def add_unit(net: pandapowerNet, bus_id: str, unit_mw: int, site_id: str) -> pandapowerNet
def stress_hours(scenario_id: str, n: int = 12) -> list[int]
def score_grid_value(site_id: str, unit_mw: int, scenario_id: str, base_net: pandapowerNet | None = None,
                     hours: list[int] | None = None) -> GridValueResult      # grid_value_score None until normalized in batch
def blackstart_reach(net: pandapowerNet, bus_id: str, unit_mw: int, max_hops: int = 3, min_kv: float = 138.0) -> float

# siting/rank.py
@dataclass(frozen=True)
class SiteScore:
    site_id: str; scenario_id: str; unit_mw: int; safety: SafetyResult; grid: GridValueResult
    combined: float; regulatory_path: str; reasons: list[str]; risks: list[str]; citations: list[str]
def score_all(unit_sizes: tuple[int, ...] = (300, 1000), scenarios: tuple[str, ...] = ("uri_2021","beryl_2024","helene_2024"),
              force: bool = False) -> list[SiteScore]     # batch; writes site_scores incl. scenario_id='all'
def regulatory_path(kind: str, safety: SafetyResult) -> str
def write_site_scores(scores: list[SiteScore], duck_path: Path = ...) -> int

# siting/tools.py — copilot wrapper (exact contract signature)
def score_site(site_id: str, unit_mw: int, scenario_id: str) -> dict
    # cache hit → site_scores row + card; miss → score_safety + score_grid_value (stress hours) + rank, persist, return asdict(SiteScore)
```

CLI: `uv run python -m siting.candidates`, `uv run python -m siting.rank --unit 1000 --scenario all`.

## Acceptance criteria

1. `build_candidates("TX")` yields ≥ 8 coal sites (expected ≈ 12 under the retired/retiring
   filter; ≥ 6 of them `interconnection='ercot'`), exactly 2 `nuclear_existing`, ≥ 6 `dod` rows
   (8 expected at ≥ 5 000 ac); every row has `county_fips` in `counties`; every
   `interconnection='ercot'` row has a non-null `bus_id` within 40 km and every non-ERCOT row
   (Pirkey, Welsh, Harrington, Tolk, Fort Bliss, Red River AD, Pantex) has `bus_id IS NULL` — a
   KD-tree that ignores interconnection assigns them a synthetic bus and this turns red.
2. `score_safety` on Comanche Peak and STP returns `safety_score > 0` with S1, S3, S4, S6, S7
   passing (existing licensed sites must not be excluded by our re-implementation — a
   sanity anchor; note Comanche Peak is in ERCOT/Oncor country and STP on the Gulf coast — S5
   must pass for both via reservoir/coast). A synthetic point in downtown Houston (29.76, −95.37) fails S1 with
   `population_downgraded=True` under `proposed_rule_mode=True` and `safety_score == 0` with
   `proposed_rule_mode=False`.
3. Every `safety_flags_json` entry has a non-empty `source` and a numeric `value`; no criterion is
   silently skipped — a missing layer raises `MissingLayerError`, it does not "pass".
4. `score_grid_value` for the same `(site, unit, scenario)` run twice gives identical numbers
   (inherits spec 03 determinism); base and with-unit runs use the same seed (asserted by
   comparing `cause="weather"` trip sets at every evaluated hour, which must be equal AND
   non-empty for at least one hour — an empty-equals-empty comparison proves nothing).
5. Adding a 1 GW unit never increases `lost_load_mwh` summed over stress hours by more than 1 %
   (a "unit made things worse" result flags a dispatch/scaling bug, not a finding), AND the
   with-unit net differs from the base net in exactly one added `gen` row with
   `p_mw == unit_mw`, `fuel == 'nuclear'`, while `sum(gen.p_mw) + sum(sgen.p_mw) + ext_grid` is
   unchanged within 1e-6 (pins the pro-rata displacement; `pp.create_gen(net, bus, p_mw,
   vm_pu=1.0, max_p_mw=…, min_p_mw=…, name=…, **kwargs)` verified to accept `max_p_mw`/`min_p_mw`
   and to pass extra kwargs like `element_id` through as columns).
6. Batch `score_all()` over Texas completes in < 20 min and writes exactly 1 row per
   (site, scenario ∈ {3 scenarios + 'all'}, unit ∈ {300, 1000}) — the test computes the expected
   row count from `site_candidates` and asserts equality, and asserts at least one site has
   `lol_reduction_mwh > 0` for `uri_2021` (a batch that writes rows of zeros passes the count
   check but not this one).
7. Ranking sanity: the top-3 by `combined` for `unit=1000, scenario='all'` all have
   `regulatory_path != 'excluded'` and non-null `bus_id`; the card lists ≥ 1 reason and ≥ 1 risk
   with a citation string.
8. `score_site("coal_retired:XXXX", 1000, "uri_2021")` returns in < 15 s on a cache miss
   (pandapower, 12 stress hours; measured spec 03 solve time makes this ≈ 1–3 s) and < 0.5 s on
   a hit; the returned dict round-trips through `json.dumps`.
9. **Break-it probe (must turn red):** replace `add_unit` with a no-op (return the base net
   unchanged). The test asserts `lol_reduction_mwh > 0` for the top-ranked site at Uri and MUST
   FAIL under the mutation — proving grid value is a real intervention, not a constant. Second
   probe: swap the PAD-US layer for an empty GeoDataFrame; the test asserts a known protected-land
   point (Big Bend NP, 29.25, −103.25) fails S6 and MUST FAIL under the mutation.

## Demo hook

Demo beat 4: "Texas coal sites ranked" table (~12 sites under the retired/retiring filter — see candidates step 1; the earlier "30" was not supported by any source) (site_scores, `scenario='all', unit=1000`),
click #1 → safety card (flags with values/thresholds) → counterfactual replay: Uri with the site
online, the Fort Hood panel stays green, "X MWh of load loss avoided" from
`lol_reduction_mwh`, customer-hours = `Σ_h Δcustomers_out`. Beat 5: copilot answers "why this
site over the one near Houston?" from two `score_site` calls: S1 density values, S5 cooling
water, `congestion_relief_pct`, citing 10 CFR 100 and the proposed §53.530.

## Risks / unknowns

- OR-SAGE numeric thresholds are now quoted from both ORNL reports in the table above (read with
  `pypdf` from the 7.7 MB ORNL PDF on 2026-09-05); the residual gap is EPRI 1006878 itself (not
  public), so the 12 % slope is citable only as ORNL's attribution.
- Layer downloads (NFHL, NHDPlus, 3DEP, PAD-US) are large; Texas clips only, and each has a
  county-level fallback named above. Never let a missing layer pass silently (acceptance 3).
- Grid value is only as good as spec 03's fragility priors; the delta between two runs with
  the same seed is robust to that, but absolute MWh is not — the card shows both the delta and
  the base.
- DC dispatch assumption (pro-rata displacement) ignores unit commitment; a nuclear unit's real
  value in Uri was availability under cold, which we model via the derate table.
- "Tier 1/Tier 2" is pitch vocabulary; use the rule's own §53.530 language on the card.
- Pantex: it was candidate #15 of 16 in DOE's April 10, 2025 RFI for AI infrastructure on DOE
  lands (~380 acres identified) but was NOT among the four sites selected July 24, 2025, and no
  DOE reactor authorization for it exists — label with caveats, do not assert. DoD authorization
  (EO 14299 §3) covers Army-regulated reactors on installations, not commercial units.
- "1000 persons/sq mi over plant lifetime" (older RG 4.7 language) was NOT found in Rev 3 (2014)
  or Rev 4 (2024) — do not cite it.

## Weekend time-box

| Task | Hours |
|---|---|
| Candidates from PUDL + DoD + static CSVs, bus assignment | 2.0 |
| Read OR-SAGE thresholds from the ORNL PDF; layer download/clip (TX) | 2.0 |
| `safety.py` 12 criteria + flags + proposed-rule downgrade | 3.0 |
| `grid_value.py` (add_unit, stress hours, 3 metrics, cache) | 3.0 |
| `rank.py` + regulatory labels + site cards + `score_site` | 1.5 |
| Acceptance tests incl. both break-it probes | 1.5 |
| **Total** | **13 h** (Day 2 morning is the critical path; start candidates + layers Day 1 evening) |
| Stretch: DoWhy/synthetic-control "firm generation near X shortened restoration" from EAGLE-I | +3 h |
