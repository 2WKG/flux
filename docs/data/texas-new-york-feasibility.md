---
title: "Texas + New York — data and scenario feasibility"
status: complete (two inputs pending, marked inline)
issue: 2WKG-138
assessed: 2026-09-05
assessor: Ghadi Khoury
scope: "Next wave. Non-blocking for the current Texas demo."
depends_on: "2WKG-137 (weather/overlays) and 2WKG-140 (demand history) — both still open"
---

# Texas + New York — feasibility

> **Stale scope (2026-09-05).** Written when Texas was the first case. The current order is
> **Minnesota → Texas → further states**. The verified inventory and the AC-OPF relaxation findings
> below still hold; the framing of Texas as "the first case" does not.

## Verdict: **Texas-only. Do not add New York as a second simulated grid.**

The issue asks for New York "only if data/scenario feasibility supports it." It does not.

The blocker is not licensing, cost, or effort. It is that **no public New York grid case exists
at a resolution comparable to ACTIVSg2000.** Every available option is either ~12× too large and
covers the wrong geography, or ~14× too coarse and needs MATLAB. A shed-MW number computed on a
2,000-bus Texas case and a shed-MW number computed on a ~140-bus reduced New York case are not
comparable quantities, and putting them on the same screen would invite exactly the question the
project's honesty rules exist to survive.

**The contrast the team actually wants is still available — without a second grid.** See §6.

---

## 1. Topology availability — the decisive comparison

| Option | Buses | Actually New York? | Format | License / terms |
|---|---|---|---|---|
| **ACTIVSg2000** (current Texas case) | 2,000 | n/a — Texas | MATPOWER, PSS/E, PowerWorld | Synthetic, free, cite |
| **ACTIVSg25k** | 25,000 | **No** — northeast + mid-Atlantic, 16 areas | MATPOWER, PSS/E, PowerWorld PWB/aux, PSLF epc | Free commercial + non-commercial; registration form; cite |
| **NYgrid** (Cornell Anderson Energy Lab) | Reduced — order ~10² | **Yes** | **MATLAB** + MATPOWER | **MIT** |
| NPCC 140-bus | 140 | Northeast backbone | Power System Toolbox | Research test case |

### Why ACTIVSg25k fails here

- It is a **northeast + mid-Atlantic** footprint across sixteen areas, not New York. Extracting
  "New York" means choosing a subset of a synthetic network that, by the repository's own
  statement, "bears no relation to the actual grid in this location." Slicing a fictional
  network along real state lines produces a boundary with no meaning.
- **25,000 buses is 12.5× ACTIVSg2000.** Task [S09] already exists to measure baseline runtime
  and pick a fallback at 2,000 buses. Adding a case an order of magnitude larger, against a
  48-hour clock, on the eve of a demo, inverts that risk decision.

### Why NYgrid fails here

- It **is** genuinely New York, MIT-licensed, validated against real power flow and LMP data
  using 2019 hourly inputs, and enforces the 11 NYISO zonal interface constraints. On the merits
  it is a good model.
- It is **reduced from the NPCC 140-bus system**. Against a 2,000-bus Texas case that is roughly
  an order of magnitude coarser. Per-site siting comparison — our entire demo — needs enough
  buses to place two candidates in meaningfully different electrical positions. A reduced zonal
  model does not offer that.
- It ships as **MATLAB** code. We have no MATLAB and no budget to acquire one. The MATPOWER case
  file could in principle be read without running their code, but that discards the validated
  pipeline and leaves only the coarse network.

> Exact NYgrid bus/generator/line counts were **not verified** — the source papers are published
> as PDFs that did not extract cleanly in this pass. "Reduced from NPCC 140-bus" and the 11
> interface constraints are confirmed; the precise counts are not. This does not change the
> conclusion, since a reduced model is coarse by construction, but it should be verified before
> anyone cites a number.

---

## 2. Demand availability — **PENDING on 2WKG-140**

Whether county-level demand actually exists for either state is the open question in **2WKG-140**
(Mira, still in Backlog). That issue's own acceptance explicitly warns: *do not infer county
granularity from aggregate data.*

Recording the dependency rather than pre-empting it. One structural point that stands regardless:
ERCOT is a single interconnection covering most of Texas, while New York sits inside the Eastern
Interconnection with heavy inter-state flows. **Any New York demand or shedding figure is
sensitive to imports across boundaries our model would not represent.** Texas is unusually
well-suited to a self-contained study precisely because ERCOT is electrically isolated. That is a
genuine argument *for* Texas-only, not merely a fallback.

---

## 3. Weather and overlays — **PENDING on 2WKG-137**

Weather, seasonal and geographic overlay candidates are **2WKG-137** (Mira, still in Backlog).
The climate-contrast half of the Texas + New York argument — winter peaking versus summer
peaking, ice versus heat — cannot be settled here without it.

Noting only that the contrast is real and interesting, and that it does **not** require a second
grid model to state (§6).

---

## 4. Context inputs — **RESOLVED via 2WKG-139**

`docs/data/industry-urban-rural-population-inputs.md` establishes that Census PEP Vintage 2025,
USDA ERS RUCC 2023, and BLS QCEW are all **national** files joining on 5-digit county FIPS.

**Extending these three from Texas to New York costs nothing.** The same downloads already
contain New York's counties.

**But the resolution asymmetry is severe:** Texas has **254 counties**; New York has **62**.
County-level analysis in New York is roughly four times coarser. Combined with the topology gap
in §1, the two states are not comparable at any layer of this stack.

---

## 5. Economic-disruption and energy-source-shift inputs

The issue asks these be consolidated as **bounded, source-labeled** inputs with units, time
bounds, evidence and availability, and that **projections never be presented as observed
history**. Handling each honestly:

### 5a. Energy-source shift — **AVAILABLE as measured history**

| Field | Value |
|---|---|
| Source | US EIA — Electricity data, state level, via Open Data API and bulk download |
| Content | Generation by plant and prime mover for each fuel consumed; capacity; sales; prices |
| Units | Generation in MWh; capacity in MW |
| Time bounds | Monthly and annual historical series |
| Geography | State (and plant); **not county** |
| Status | **Measured**, reported by operators |
| License | US federal government work — public domain |

Access caveats: the API returns a maximum of **5,000 rows per request** (300 for XML), and the
bulk download refreshes twice daily (05:00 and 15:00 Eastern, available 30–45 min after start).
Plan for pagination or bulk files, not a single large query.

**The line that must not be crossed:** EIA also publishes *projections* (Annual Energy Outlook
scenarios). Those are modelled futures. They may inform a scenario assumption; they may never
appear beside historical generation without an explicit label. This is the issue's own "never
present projections as observed history" clause, and EIA is the exact source where the two sit
side by side under one brand.

### 5b. Economic disruption — **NO DATASET. This is an assumption register, not data.**

No bounded, source-labeled dataset of "economic disruption" was identified, and it is unlikely
one exists in the form implied — "disruption" is a scenario the team chooses, not a quantity
someone measures and publishes.

The closest **measured** proxies:

- **BLS QCEW** (per 2WKG-139): county × NAICS employment and wages, quarterly. Measures industrial
  activity, **not** electricity consumption and **not** disruption. Carries disclosure suppression
  in low-population counties, which must stay suppressed.
- **Census PEP**: population change. An estimate, not a count.

**Recommendation: treat economic disruption as a declared scenario assumption with a stated
magnitude, duration and rationale — never as an input dataset.** Record it the way the demo
already records its stress preset: one preset, stated on screen, with its assumed duration.
Anything else fabricates a measurement.

---

## 6. The Texas-only fallback — and how to keep the contrast

The fallback is not a retreat. It is stronger under hostile questioning than the alternative.

**Keep:** one grid (ACTIVSg2000), one stress preset, two candidate sites, signed comparison.
Exactly the frozen scope in the 48-hour build plan.

**Make the New York contrast as a stated argument, not a simulated result:**

1. **Scalability.** ACTIVSg25k exists, in the same repository, in the same MATPOWER format our
   pipeline already reads. That is concrete evidence the approach scales beyond Texas —
   citable without running it. "The method is case-agnostic; here is the next case, in the
   format we already ingest" is a defensible claim. "We ran it and got a number" would not be,
   at that scale, in this timebox.
2. **Energy-mix contrast.** EIA state-level generation by fuel is measured, public-domain, and
   needs no grid model. A single sourced comparison chart of Texas versus New York generation
   mix supports the climate/energy-mix story honestly.
3. **Electrical isolation as a feature.** ERCOT's separation is *why* Texas is the right first
   case: a self-contained study with no unmodelled imports. New York's Eastern Interconnection
   position is a modelling liability, not just a scope increase. Saying this out loud converts
   the limitation into evidence of judgement.

Each of the three is defensible to a judge who distrusts dashboards. A second grid at mismatched
resolution is not.

---

## 7. What would change this verdict

- A public New York case at 1,000–5,000 buses appearing in MATPOWER format. None found.
- 2WKG-140 establishing genuine county-level demand for New York **and** the team accepting the
  interconnection-boundary caveat in §2.
- The timebox changing from 48 hours to weeks. At that point ACTIVSg25k becomes reasonable and
  the scalability claim can be demonstrated rather than argued.

---

## Sources

- [Texas A&M Electric Grid Test Case Repository](https://electricgrids.engr.tamu.edu/electric-grid-test-cases/)
- [ACTIVSg2000 (Texas, 2000-bus)](https://electricgrids.engr.tamu.edu/electric-grid-test-cases/activsg2000)
- [ACTIVSg25k (northeast + mid-Atlantic, 25,000-bus)](https://electricgrids.engr.tamu.edu/electric-grid-test-cases/activsg25k/)
- [A Description of the Texas A&M University Electric Grid Test Case Repository (PDF)](https://electricgrids.engr.tamu.edu/wp-content/uploads/sites/129/2024/04/Electric_Grids_Repository_for_Power_System_Analysis_TPEC.pdf)
- [NYgrid — AndersonEnergyLab-Cornell (GitHub, MIT)](https://github.com/AndersonEnergyLab-Cornell/NYgrid)
- [An Open Source Representation for the NYS Electric Grid (arXiv 2112.06756)](https://arxiv.org/pdf/2112.06756)
- [EIA Open Data](https://www.eia.gov/opendata/)
- [EIA API technical documentation](https://www.eia.gov/opendata/documentation.php)
- [EIA Electricity data](https://www.eia.gov/electricity/data.php)
