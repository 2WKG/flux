# David Project Hackathon — Pitches and Design Outlines

*3 Sept 2026. Three ideas, ranked for this judge panel (defense / national-security / tech-policy heavy). Each has: the spoken pitch, what it does in plain terms, a design outline, the causal-AI layer, the data, the recommendations it outputs, a demo script, judge hooks, and a weekend build plan. A shared technical stack is at the end so all three can be built on the same base.*

---

# Idea 1 (Rank #1) — National Grid Digital Twin with Outage Prediction and Nuclear Siting

## The pitch (90 seconds, spoken)

America is about to add more electric load in ten years than it added in the last thirty — data centers, reindustrialization, and defense installations that cannot go dark. The grid that has to carry it is run by 3,000 separate utilities, none of whom can see the whole system, and the tools for deciding where to put new firm power are PDF reports and a 2022 government GIS screener with no grid data in it.

We built the first national grid model that connects three questions nobody currently connects: where will the grid fail, what does that failure cascade into, and where should the next gigawatt of firm generation go so the whole system gets stronger. You pick a storm, we replay it across the grid and show which counties go dark and which substations carry the cascade. You pick a nuclear site, we show how much loss-of-load it removes, whether it clears NRC safety rules, and which defense installation it protects. It's the planning layer that sits above every utility — the operating picture for American power.

## What it does, in simple terms

1. Shows the whole US grid on a map: lines, substations, power plants, and who serves each county.
2. Predicts outages: given the weather forecast, which counties are likely to lose power and how many customers.
3. Simulates cascades: if this substation or line fails, what else fails, and who ends up in the dark — including military bases and other critical loads.
4. Ranks nuclear sites: for every retiring coal plant, existing nuclear site, and federal site, scores how *safe* it is (NRC rules) and how much it *strengthens the grid* (reduced loss-of-load, reduced congestion, faster black-start).
5. Answers questions in English with citations: "Where should the next 2 GW of firm generation go in Texas and why?"

## Design outline

**Layer 1 — Grid model (the twin).**
Use a synthetic-but-realistic national grid (Texas A&M ACTIVSg82k, or Microsoft's open GridSFM 48-state model) as the electrical skeleton, and overlay the *real* geography: archived HIFLD transmission lines and substations, real EIA-860 power plants with lat/lon, real utility service territories, and real counties. A join table connects synthetic buses to real counties and balancing authorities, which is what lets real outage and load data attach to the model. Say plainly in the demo that the topology is synthetic; real topology is restricted (CEII), and the architecture has a slot for it.

**Layer 2 — Load and weather.**
Hourly demand by balancing authority from EIA-930 scales the model's load hour by hour. Weather comes from NOAA storm events (history), HRRR reanalysis (wind, ice, temperature per line segment), NWS live alert polygons (demo "live" layer), FEMA National Risk Index and USFS wildfire hazard (chronic exposure).

**Layer 3 — Outage prediction (learned).**
A gradient-boosted model (LightGBM) trained on ORNL's EAGLE-I dataset — county-level customers-out every 15 minutes, 2014–2025 — with weather, hazard, season, and utility reliability history (EIA-861 SAIDI/SAIFI) as features. Validate by holding out Winter Storm Uri (2021), Hurricane Beryl (2024), and Helene (2024) and replaying them.

**Layer 4 — Cascade simulation (physics).**
pandapower on the synthetic grid: apply weather-driven failure probabilities to lines, drop the failed elements, re-run DC power flow, trip anything overloaded, repeat until stable, then translate lost load back to counties and customers. Tag critical loads (DoD installations from public boundary data, hospitals, water) so the output says "Fort Hood loses supply at hour 3." Optionally wrap in Grid2Op so an "operator agent" can try remediations (redispatch, topology changes).

**Layer 5 — Siting engine.**
Candidate set = retired and retiring coal plants (EIA-860), existing nuclear sites, DOE's four federal AI/energy sites (INL, Oak Ridge, Paducah, Savannah River), and large defense installations. Two scores per site:
- *Safety/buildability* — a re-implementation of the published OR-SAGE/STAND criteria on open layers: population density (≤500 people/sq mi within 20 miles), seismic hazard (USGS), floodplain (FEMA), cooling water (NHD), protected land (PAD-US), slope, wildfire, state moratorium flag.
- *Grid-strength value* — put a 300 MW / 1 GW unit at the site in the twin, re-run the stress scenarios, measure the drop in expected loss-of-load, congestion relief, and black-start reach. This is the number nobody else produces.

**Layer 6 — Copilot.**
A tool-calling LLM agent (the GridMind / Grid-Agent pattern from 2025 papers). The model never does arithmetic; it calls `predict_outage(county, horizon)`, `run_cascade(element_ids, hour)`, `score_site(lat, lon, size)`, `sql(...)`, and retrieves from 10 CFR 100, the DOE coal-to-nuclear report, and the May 2025 nuclear executive orders for citations.

**Interface.** deck.gl + MapLibre map with layers: line loading, county outage-risk choropleth, animated storm polygon, cascade playback (elements trip in sequence), candidate-site pins with score cards, and a critical-load panel. One "Ask" box.

## Causal-AI layer (fits well here)

The physics simulator *is* a structural causal model: interventions ("place a reactor here," "harden this line") are literal do-operations on the graph, and counterfactuals ("would Uri have blacked out Austin if this site had been online?") are just re-runs. Make that explicit in the pitch — it's the difference between correlation dashboards and a decision engine.

Where learned causality adds value:
- **Outage causal graph.** Build a Bayesian network / structural model (pgmpy or DoWhy) with nodes: weather severity → vegetation/wildfire exposure → line failures → substation loss → customers out, with utility investment (SAIDI trend, rate-case hardening spend) as a confounder. Use it to answer "how much of this county's outage risk is weather vs. under-investment" — a question judges from a policy background will love.
- **Effect estimation.** Estimate the causal effect of past hardening or generation additions on outage duration using synthetic control or difference-in-differences across similar counties in EAGLE-I. This lets the siting score claim "historically, adding firm generation near X reduced restoration time by Y."
- **Counterfactual replay.** For each held-out storm, show the actual outage map next to the counterfactual map with the recommended site online. That's your closing slide.

## Data checklist

Grid geometry: archived HIFLD lines/substations (DataLumos, Data Rescue Project, HIFLD Next), OSM power tags as backup. Topology: ACTIVSg82k / ACTIVSg2000 (Texas), Microsoft GridSFM, PyPSA-USA. Plants: EIA-860 via PUDL. Load: EIA-930 (hourly by BA), FERC 714. Outages: EAGLE-I 2014–2025 (Globus), ODIN live API, DOE OE-417. Reliability: EIA-861 SAIDI/SAIFI. Weather/hazard: NOAA Storm Events, HRRR, NWS API, FEMA NRI, USFS wildfire, USGS NSHM 2023, NHD, PAD-US, Census. Siting references: DOE coal-to-nuclear reports (2022, Sept 2024), OR-SAGE method papers, 10 CFR 100, Reg Guide 4.7, NRC July 2026 proposed siting rule, EO 14299–14302. Critical loads: DoD installation boundaries (public), HIFLD hospitals (archived). Load growth: LBNL Queued Up 2026, Cleanview data-center map.

## Recommendations the tool outputs

- Top-N counties at outage risk for the next 72 hours, with customers-at-risk and the driver (wind, ice, wildfire, heat).
- Top-N critical elements whose loss cascades furthest, with the critical loads they strand.
- Ranked nuclear/firm-generation sites with two scores (safety, grid-strength), the loss-of-load reduction in MWh, the defense installations covered, and the regulatory path (NRC Tier 1/2 under the proposed rule, DOE-authorized on federal land, brownfield fast track under the ADVANCE Act).
- For each recommended site: the three biggest reasons and the three biggest risks, with citations.

## Demo script (5 minutes)

1. National map, zoom to Texas. "This is the grid as public data lets us see it."
2. Load the Winter Storm Uri weather. Outage model lights up counties; compare to what actually happened (EAGLE-I) — show the accuracy.
3. Trigger the cascade: watch lines trip; a defense installation panel turns red at hour 3.
4. Open siting: 30 Texas coal sites ranked. Pick #1. Show safety card, then the counterfactual replay: same storm, the site online, the installation stays green, X million customer-hours avoided.
5. Ask the copilot: "Why this site over the one near Houston?" It answers with population-density, cooling water, congestion relief, and cites 10 CFR 100.
6. Zoom out to the 82k-bus national model: "This scales. The architecture has a slot for real utility data under CEII."

## Judge hooks

Second Front (Sweatt, Bosquez, Utt): CEII-ready, air-gappable architecture; path to accreditation; deploys inside a utility, RTO, or DoD enclave. a16z / Department of War (Cronin, Booher): critical-infrastructure defense without being a weapons program; the Army's Janus microreactor program (Aug 2026), Project Pele, and EO 14299 make "which base first" a live procurement question. FAI (Levine, Dauber): NRC's July 2026 siting rule invites exactly the societal risk-benefit quantification this produces; Brookhaven's GridFM (Sept 1, 2026) shows the government wants a national model — you're the decision layer on top. Craft Ventures (Murray): utilities, RTOs, developers, DOE, and hyperscalers are all buyers; Enverus/Pearl Street proves the siting market, GridCARE's $64M proves investor appetite. Forterra/Dirac/KAIROS: it's a real systems product with physics under it, not a chatbot.

## Risks and honest answers

"Your topology is fake." — Yes; real topology is CEII. Synthetic grids are the research standard (Microsoft, DOE, Texas A&M) and the architecture swaps in real data under a data-use agreement.
"Palantir will do this." — Palantir's Chain Reaction is workflow and ontology; it has no grid physics and no siting engine. We're the engine they'd want to partner with or buy.
"Nuclear takes a decade." — The siting decision is being made *now* (Janus, DOE federal sites, 10 large reactors by 2030 under EO 14302); the tool is for the decision, not the construction.

## Weekend build plan

Day 1 morning: PUDL + EAGLE-I + HIFLD + ACTIVSg2000 loaded into DuckDB/PostGIS; bus↔county join. Day 1 afternoon: LightGBM outage model on Texas counties; Uri holdout. Day 1 evening: pandapower cascade loop with critical-load tagging. Day 2 morning: siting scorer (exclusions + grid-strength delta) on Texas coal sites. Day 2 afternoon: deck.gl front end + copilot with four tools. Day 2 evening: counterfactual replay slide, national map for scale, rehearse. Stretch: DoWhy causal effect of past hardening on outage duration; Grid2Op operator agent.

---

# Idea 2 (Rank #2) — Data Center Load Verification and Grid Impact Scoring

## The pitch (90 seconds, spoken)

Utilities are planning to build for 90 gigawatts of data-center load by 2030. Independent analysts think about 65 will show up. Camus Energy sees five to ten times more requests than builds. The same project shows up in three utilities' queues at once. Every gigawatt of phantom load that gets built for is billions of ratepayer dollars and years of interconnection delay for the loads that are real — including the defense and manufacturing loads the country actually needs.

Three months ago FERC ordered all six grid operators to fix their large-load rules, and the responses just came in. But nobody — not FERC, not the states, not the utilities — has a tool that reconciles what's announced, what's in the queue, and what's being forecast, or that scores whether a proposed data center helps or hurts the grid.

We built it. For every utility in America, it shows the gap between announced, queued, forecast, and real load. And for any proposed data center, it produces a grid-impact score: how flexible it is, whether it brings its own power, what headroom exists at that location, and what it will cost everyone else if it's built for and never shows up.

## What it does, in simple terms

1. A map of every utility showing four numbers: data-center load announced, in the queue, in the utility's forecast, and actually operating. The gap is the phantom ratio.
2. A duplicate detector: the same project or developer appearing in multiple queues.
3. A cost estimate: what building for the phantom load would cost ratepayers.
4. A Grid Impact Score for any proposed data center (0–100) with a plain-English explanation and a "what would make this a 90" recommendation.
5. A copilot for regulators: "Which three PJM projects should Virginia review most skeptically?"

## Design outline

**Layer 1 — Project registry.** Pull announced projects from Cleanview's free tier and EEI's large-customer list; queue data from ERCOT's monthly Large Load Interconnection Status reports and Batch Zero list, PJM's load-forecast large-load adjustments by transmission owner, SPP's HILLGA; utility forecasts from FERC Form 714 and IRP filings; operating load from EIA-860/861 and Cleanview. Normalize to a common schema (developer, site, MW, stage, utility, ISO, date).

**Layer 2 — Entity resolution.** Match projects across sources by developer name, county, MW, and filing dates (fuzzy matching + geographic proximity). Flag likely duplicates and "shopping" (same developer, same MW, three utilities).

**Layer 3 — Reality model.** Estimate the probability each project reaches operation and its likely load factor, using historical conversion rates (LBNL Queued Up history for generation as a prior; ERCOT and PJM stage transitions for load), stage, developer track record, tariff terms (minimum-demand commitments, collateral), and whether generation is co-located. Aggregate to utility level: expected real MW vs. forecast MW.

**Layer 4 — Grid Impact Score.** For a proposed site: flexibility commitment (curtailable share and response time, per EPRI DCFlex categories), bring-your-own generation/storage, load factor, local headroom (Duke's per-balancing-authority curtailment-headroom tables + EIA-930 hourly load), local congestion (gridstatus LMP spreads), transmission service type (firm vs. the new non-firm/interim services FERC ordered PJM to create), and tariff terms. Weighted to a 0–100 score; each component explained.

**Layer 5 — Cost model.** Phantom MW × cost-to-serve (transmission and generation capacity cost per MW from FERC Form 1 / IRP figures) = stranded-cost exposure per utility, and the delay imposed on real loads behind them in the queue.

**Layer 6 — Copilot.** Tools: `phantom_ratio(utility)`, `duplicates(developer)`, `score_site(lat, lon, params)`, `cost_exposure(utility)`, plus retrieval over the six RTO show-cause responses, PJM's CIFP decision, ERCOT SB6 rules, and the FERC RM26-4 docket.

**Interface.** US map by utility colored by phantom ratio; utility drill-down with four bars (announced/queued/forecast/operating); duplicate-project table; site-scoring form that returns the score card and "what would make this a 90"; copilot box.

## Causal-AI layer (fits well here)

- **Conversion causal model.** The core question — "what makes a data-center request actually get built?" — is causal. Build a DAG: developer type, tariff terms (minimum demand, collateral), co-located generation, ISO rules, local headroom → probability of operation and time-to-energize. Estimate effects with DoWhy/EconML on ERCOT and PJM stage histories. This turns the reality model from a guess into an evidence-based estimate and lets the tool say "minimum-demand tariffs raise conversion probability by X points."
- **Policy counterfactuals.** "If Virginia adopted AEP Ohio's 85% minimum-demand tariff, expected phantom load falls by Y GW." That is the exact question the FAI judges and state commissions ask.
- **Duplicate detection as causal structure.** Multiple filings by one developer are correlated draws from one underlying project; model it as a latent variable so the aggregate doesn't triple-count.

## Data checklist

Cleanview US data-center map (free tier); EEI list of large-customer projects and tariffs (Aug 2026); ERCOT Large Load Interconnection Status monthly reports and Batch Zero lists; PJM load forecast reports and queue; SPP HILLGA; MISO/NYISO/ISO-NE/CAISO show-cause responses (FERC eLibrary, docket RM26-4 and the six Section 206 dockets); FERC Form 714 and Form 1 via PUDL; EIA-860/861/930; Duke Nicholas Institute "Rethinking Load Growth" tables; gridstatus LMPs; LBNL Large Load Literature Review data-source catalog (May 2026) and Queued Up 2026; Grid Strategies load-growth reports; Halcyon large-load tariff tracker; Cleanview behind-the-meter report (59 BTM data centers); OpenG2G if a physics layer is wanted.

## Recommendations the tool outputs

- Per utility: phantom ratio, expected real MW, stranded-cost exposure, and the top duplicate/shopping flags.
- Per proposed site: Grid Impact Score, the three components dragging it down, and specific fixes ("commit to 200 hours/yr curtailment → unlocks interconnection 18 months sooner; add 100 MW storage → score 78→91").
- Per state: which tariff or interconnection rule change most reduces phantom load, with estimated effect.
- Per ISO: which projects in the queue are most likely real, so real loads (including defense and manufacturing) can be prioritized.

## Demo script (5 minutes)

1. National map: utilities colored by phantom ratio. Zoom to a hotspot (Dominion / Virginia, or ERCOT).
2. Drill in: four bars. "This utility is forecasting 3x what's likely to be built. Here's the ratepayer exposure."
3. Duplicate table: one developer, same 500 MW, three queues.
4. Score a real proposed site: 54/100. Click "what makes this 90": curtailment commitment + storage. Re-score: 91. "That's 18 months faster to power."
5. Copilot: "Which PJM projects should Virginia's commission review most skeptically?" — answer with citations to filings.
6. Close: "FERC ordered the fix in June. This is the fix."

## Judge hooks

White House anti-fraud (McCarthy): phantom load is misrepresentation in regulated filings with public cost; entity resolution and duplicate detection are anti-fraud tooling. FAI (Levine, Dauber): this is the AI-power-buildout policy fight; the tool produces policy counterfactuals. Craft Ventures (Murray): buyers are state PUCs, RTOs, utilities, and the hyperscalers who need to prove they're real; Emerald ($150M last week) and GridCARE ($64M) validate the market. Defense judges: real defense and manufacturing loads are stuck behind phantom ones; verification is what gets them to the front. OPM (Hennecken): government-operations efficiency framing — regulators doing in minutes what takes staff months.

## Risks and honest answers

"Cleanview already tracks projects." — It tracks announcements; it doesn't reconcile them against queues and forecasts or score sites.
"Utilities have this data internally." — Each has its own slice; none sees other utilities' queues, which is where duplicates hide.
"Your conversion estimates are uncertain." — Yes, and we show intervals; the point is that today's number is a guess with no interval at all.

## Weekend build plan

Day 1: scrape/load the registries into one schema; entity resolution; utility-level four-bar chart on a map. Day 2 morning: conversion model (start with stage-based priors; add the causal estimate if time); cost exposure. Day 2 afternoon: Grid Impact Score form; copilot with retrieval over the FERC docket; rehearse. Stretch: DoWhy tariff-effect estimate; OpenG2G physics for one site.

---

# Idea 3 (Rank #3) — Transmission Line Upgrade Prioritization

## The pitch (90 seconds, spoken)

Congestion on America's transmission lines cost $12 billion in 2024. New transmission corridors take a decade and DOE just cancelled every national corridor it had proposed. But existing lines can carry far more than they do today: dynamic line ratings raise capacity 15–30% with sensors and software, and reconductoring with advanced conductors roughly doubles it on the same towers. DOE just put $1.9 billion behind exactly this, and sixteen states now require utilities to consider it.

The missing piece is simple: nobody has a public answer to "which lines first?" The industry told DOE in writing last November that the blocker is line-level data. We built the ranker. For every high-voltage line in the country, it estimates the congestion it causes, the capacity a dynamic rating would add given local wind, the capacity reconductoring would add given what the wire is made of, and the cost — and outputs the cheapest megawatts of new capacity in each region.

## What it does, in simple terms

1. A national map of transmission lines colored by "megawatts unlocked per dollar."
2. For each line: how congested it is, how much dynamic rating would help, how much reconductoring would help, and which is cheaper.
3. A regional top-10: the cheapest capacity in MISO, PJM, ERCOT, etc.
4. A screen matching FERC's proposed rule (congestion above $500k/yr plus wind) and a flag for DOE SPARK eligibility.
5. A copilot: "What are the ten cheapest MW of capacity in MISO and which technology gets them?"

## Design outline

**Layer 1 — Line inventory.** Archived HIFLD transmission lines (69–765 kV) with voltage and owner, cleaned with OSM where HIFLD is blank. FERC Form 1 schedule 422 (via PUDL) gives conductor type, size, length, and voltage for investor-owned utilities' lines — join by owner + voltage + length to attach "what the wire is made of."

**Layer 2 — Congestion attribution.** Pull binding constraints and shadow prices from RTO feeds and LMP congestion components via gridstatus. Map constraint names to physical lines (PJM's monitored-facility names are the most tractable; ERCOT and MISO next). Compute annual congestion dollars per line.

**Layer 3 — Dynamic-rating uplift.** For each line, wind-speed and temperature climatology from NOAA HRRR / NREL WIND Toolkit, pushed through the public IEEE 738 ampacity equation to estimate hours-per-year and MW of additional capacity over static and ambient-adjusted ratings.

**Layer 4 — Reconductoring uplift.** From conductor type/size and voltage, estimate capacity gain from advanced conductors (ACCC/ACSS-class roughly 1.5–2x) using GridLab/Berkeley and LBNL REFA assumptions; cost per mile from REFA.

**Layer 5 — Ranking and recommendation.** For each line: MW unlocked and cost for DLR, reconductoring, and topology/power-flow control; congestion relieved; payback. Rank by MW per dollar; apply the FERC ANOPR screen; flag SPARK-eligible.

**Layer 6 — Copilot.** Tools: `line_profile(id)`, `top_lines(region, tech, n)`, `screen(ferc_anopr=True)`, retrieval over the FERC ANOPR, Order 881, state GETs statutes, and the WATT/AMP RFI response.

**Interface.** National line map with color by MW-per-dollar; filters by ISO/state/utility/technology; line card with the three options and payback; regional top-10 table; copilot.

## Causal-AI layer (partially applicable)

The core is physics (ampacity) and economics, so causal ML is secondary. Where it earns its place:
- **Effect of DLR on congestion.** Use synthetic control on the PPL/PJM deployment (congestion fell from $66M to $1.6M on one line) and the AES, Great River, and NV Energy pilots to estimate a causal uplift factor rather than quoting vendor claims — then apply it to the ranking.
- **Congestion causal decomposition.** Congestion dollars on a line are caused by load growth, generation additions behind it, and outages of parallel lines; a simple structural model attributes the share, which tells you whether an upgrade would actually clear it or just move it.

## Data checklist

Archived HIFLD lines (DataLumos / Data Rescue Project / HIFLD Next); OSM power tags; FERC Form 1 schedule 422 via PUDL; gridstatus (7 ISOs' LMPs with congestion components; RTO binding-constraint feeds); market-monitor state-of-market reports; Grid Strategies 2024 congestion report; NOAA HRRR; NREL WIND Toolkit; IEEE 738; LBNL REFA cost assumptions; GridLab/Berkeley reconductoring study (PNAS 2024); OASIS ATC/TTC postings; FERC DLR ANOPR (RM24-6), Order 881 compliance dates; state GETs laws (WATT tracker); DOE SPARK funding notice; WATT/AMP Speed-to-Power RFI response (Nov 2025).

## Recommendations the tool outputs

- Per region: top-10 cheapest MW of new capacity with technology, cost, and payback.
- Per line: DLR vs. reconductor vs. topology recommendation with the reasoning.
- Per state: lines that satisfy the new state GETs-consideration statutes.
- SPARK-eligible shortlist for DOE reviewers and utilities.

## Demo script (5 minutes)

1. National map colored by MW-per-dollar. "The cheapest capacity in America is already built; it's just under-rated."
2. Zoom to PJM; click the PPL corridor: "Here's the line where DLR cut congestion 97%. Our model would have flagged it."
3. Regional top-10 for MISO; one line card showing DLR vs. reconductor economics.
4. Toggle the FERC screen: "These are the lines FERC's own proposed rule would target — the rule is stalled, so nobody has run it. We did."
5. Copilot question; close on SPARK: "$1.9B is being awarded this fall; this is the lead list."

## Judge hooks

Craft Ventures: vendors (LineVision, Heimdall, TS Conductor, Smart Wires) need lead lists; RTOs and state commissions need to implement new laws. Defense judges: capacity without new corridors means hardening supply to installations without decade-long NEPA fights; corridor criticality doubles as a restoration-planning view. FAI: the permitting-reform story (REWIRE Act would give reconductoring a categorical exclusion). Dirac/Forterra/KAIROS: it's an honest engineering product.

## Risks and honest answers

"Constraint-to-line mapping is hard." — Yes; we do PJM cleanly and approximate elsewhere, and say so.
"No one on the panel is a transmission engineer." — Correct, which is why this ranks third here; it's a feature inside Idea 1 rather than a standalone entry for this room.

## Weekend build plan

Day 1: HIFLD + Form 1 join; gridstatus congestion pull for PJM; constraint mapping for PJM only. Day 2 morning: IEEE 738 uplift from HRRR climatology; reconductor uplift and REFA costs; ranking. Day 2 afternoon: map + line cards + copilot; rehearse. Stretch: synthetic-control DLR effect; MISO/ERCOT mapping.

---

# Shared technical stack (build once, use for all three)

Storage: DuckDB + Parquet for time series, PostGIS for geometry, networkx (or Neo4j) for the grid graph. Ingest: PUDL (EIA/FERC), gridstatus (ISO data), Globus (EAGLE-I), archived HIFLD, NOAA/HRRR on AWS. Physics: pandapower (+ lightsim2grid), PyPSA-USA for expansion runs, IEEE 738 for ampacity. ML: LightGBM, PyTorch Geometric for graph models, DoWhy / EconML / pgmpy for the causal layer. Front end: deck.gl + MapLibre with free tiles (OpenFreeMap / Protomaps), H3 for national aggregation. Copilot: a tool-calling LLM with typed functions and retrieval over regulatory PDFs; the model narrates and plans, never computes.

# Final recommendation

Enter Idea 1 as the headline, with Idea 3's line-upgrade ranking as one screen inside it ("the twin also tells you which existing wires to upgrade") and the defense-critical-load / black-start chapter as the second hero screen. Keep Idea 2 as a fully separate backup pitch — it is the strongest standalone if the format allows two entries or if the judges signal they want something narrower and nearer-term. All three run on the same stack, so the shared data work on Day 1 is not wasted whichever you lead with.
