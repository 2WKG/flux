---
title: "Generalizable multi-energy scenario demonstration — roadmap"
status: roadmap (non-blocking)
issue: 2WKG-276
created: 2026-09-05
owner: Ghadi Khoury
---

# Generalizable multi-energy scenario demonstration

**This does not replace the frozen demo.** The Texas one-screen comparison ships as scoped.
This roadmap describes how that demo becomes reusable across energy types and operating
conditions afterwards, and what evidence would be required to say so honestly.

**Texas is the first and only committed case. New York and Minnesota stay candidates** — both
are verified available (`docs/data/texas-new-york-feasibility.md`), neither is committed scope.

---

## 1. What "generalizable" has to mean here

The current bundle hardcodes the two things that would have to vary:

| Hardcoded today (`model/generate_demo.py`) | What generalization requires |
|---|---|
| Two 300 MW additions, energy type implicit | Intervention parameterized by **energy type** — capacity, availability factor, dispatchability |
| One stress preset (×1.17 demand, 0.79 availability, fixed duration) | **Operating condition** as a named, swappable input |
| One five-bus synthetic fixture | Grid case as a swappable input |

Generalizability is demonstrated by **running the same code path over a second energy type and
a second operating condition and getting defensible results** — not by adding data.

> **Anti-claim, load-bearing:** more sources in the registry is not evidence of generalizability.
> Neither is a second state. The only evidence is the same pipeline producing a correct,
> reproducible comparison under inputs it was not tuned for.

---

## 2. Observed inputs vs. hypothetical assumptions

Every number on screen must sit in exactly one column, and the boundary must be stated.

### Source-backed observed

| Input | Source | Status |
|---|---|---|
| Network topology, impedances, ratings | ACTIVSg2000 (TAMU) / GridSFM (MIT) | Synthetic-but-published. **Say "synthetic" out loud.** |
| Demand allocation | GridSFM `per_ba_census`, EIA-930 | Measured at BA level; **allocated to buses by population, not metered** |
| Generation fleet, fuel type | EIA-860 / EIA-923 | Measured |
| Historical event outcomes | FERC/NERC Uri final report | Measured, cited |

### Hypothetical — declared, not measured

| Assumption | Why it is an assumption |
|---|---|
| Stress preset (demand multiplier, generation derate) | Chosen by us. No source publishes "the" cold-snap multiplier. |
| Assumed duration for MWh | A stated constant; not an hourly reconstruction |
| Candidate site placement | Illustrative bus mapping, not a validated interconnection |
| Energy-type availability factors | Nameplate-derived; not a measured capacity credit |

**Boundaries on any claim we make:**

1. Results are **comparative**, not absolute. "A beats B under this stress" — never "Texas would
   have lost X MW."
2. Synthetic topology means **no real-facility protection claim**, ever.
3. GridSFM ships a **2024-07-15 July snapshot**; a winter scenario is our scaling of it, stated.
4. Texas BA coverage is **84%**; absolute shed MW is not comparable across states.
5. A tie is a result. Do not manufacture a winner.

---

## 3. The four work packages

Scoped as child issues 2WKG-279, 2WKG-280, 2WKG-283 and 2WKG-285. Sequential; each is
independently useful.

**A · Research — energy types and operating conditions** (2WKG-279)
Determine which energy types can be represented honestly in a DC dispatch model (firm thermal,
nuclear, wind, solar, storage) and what each requires: availability factor, dispatchability,
whether storage needs state-of-charge the model cannot carry. Output: a table of
representable / not-representable with reasons. Deciding *not* to model storage is a valid
result.

**B · Reusable configuration** (2WKG-280)
One scenario config schema — grid case, operating condition, intervention set — replacing the
hardcoded constants. The existing bundle becomes the first config, not a special case.
Keep it a single declarative file. No plugin system, no registry, no abstraction layer.

**C · Selected-scenario execution and comparison** (2WKG-283)
Run the config path over **two** scenarios: the frozen Texas cold-weather case, and one
alternative energy type or operating condition from A. Emit both through the same exporter.
This is the actual demonstration; A and B only make it possible.

**D · Robustness and scalability validation** (2WKG-285)
Confirm the path holds under inputs it was not tuned for: infeasible solve reports as failure
rather than zero impact, a tie stays a tie, determinism holds on re-run, and runtime is recorded
at the larger case size. Names the point at which the approach stops being defensible.

---

## 4. Sequencing

```
A research ──▶ B config ──▶ C execution ──▶ D validation
                  │
                  └── frozen Texas demo re-expressed as config #1 (no behaviour change)
```

Nothing here starts before the Texas demo is frozen and rehearsed — the build plan's own rule
on stretch work.

## 5. Where NY and MN sit

Both verified, neither committed. If a second state is ever entered, the decision inputs are
already recorded: New York needs L3/L5 relaxation and 253–322 s per solve; Minnesota solves at
L0 Strict in 21 s and sits in the grid that shed 2 hours to ERCOT's 3 days under Uri. A second
state is a **C-stage scenario**, not a new project.

## References

- `docs/data/texas-new-york-feasibility.md` — verified topology inventory, both candidates
- `docs/data/industry-urban-rural-population-inputs.md` — county-FIPS context sources
- `STACK-LOCK.md` — demo boundary this roadmap must not cross
- `model/generate_demo.py` — the constants B replaces
