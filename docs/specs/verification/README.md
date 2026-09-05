# Verification ledgers — how to read them

Every spec in `docs/specs/` was fact-checked by an independent agent that was NOT its author,
on 2026-09-05, against primary sources (live URLs, sample downloads, statutes, agency PDFs) or
live library introspection in this repo's `uv` environment. Each ledger lists every load-bearing
claim with a verdict: **VERIFIED** (source + how), **CORRECTED** (spec text changed in place,
old → new recorded), or **UNVERIFIABLE** (left tagged `[UNVERIFIED]` in the spec, with what
would verify it). Nothing was softened or deleted because it could not be checked.

| Ledger | Specs | Verified | Corrected | Unverifiable |
|---|---|---|---|---|
| `01-02.md` | data ingest, outage model | 56 | 31 | 9 |
| `03-04.md` | cascade sim, siting engine | 32 | 31 | 10 |
| `05-06.md` | copilot, frontend | 54 | 18 | 2 |
| `00-07-08-09.md` | overview, causal, line upgrades, Speed-to-Power backup, pitch | 54 | 26 | 14 |
| **Total** | | **196** | **106** | **35** |

## Corrections that change the build (read these first)

1. **ACTIVSg2000 coordinates.** The June-2016 xlsx is a previous case version (2,007 buses,
   49,776 MW); only 98 of its bus numbers match the pip `case_ACTIVSg2000.m`. Coordinates come
   from the current-version zip's `ACTIVSg2000.aux` (all 2,000 ids map, 0 kV mismatches).
2. **Solver.** lightsim2grid cannot load this case (847 branches import as `net.impedance`);
   pandapower `rundcpp` is the only solver, 9–14 ms warm, ~6–12 s per 168-h Uri replay.
   Transformer overloads must be computed by the cascade loop (no `loading_percent` for them).
3. **Regulatory.** FERC's DLR ANOPR (RM24-6) proposes no $/yr or wind threshold; 10 CFR 53.530
   is final (91 FR 15696); the July 2026 proposed rule (91 FR 44560) revises Part 100; ADVANCE
   Act has no "55 %" fee cut in statute (NRC's rule is ≈53 %); DOE-site EO is 14299.
4. **Texas candidates.** ~12 retired/retiring coal plants, 4 outside ERCOT (SPP/WECC →
   `bus_id NULL`); Fort Hood name restored July 2025; Fort Bliss and Red River AD are not ERCOT.
5. **APIs.** pgmpy 1.1.2 `DiscreteBayesianNetwork`; gridstatus 0.36 `ErcotAPI` import path;
   LightGBM 4.7 `early_stopping` callback (no `scale_pos_weight='auto'`); Anthropic SDK 1.4
   `TextEvent`; deck.gl 9.3 `_onMetrics`; DuckDB read-only still executes `COPY … TO`, so a
   denylist is load-bearing.
6. **Data.** ERCO load at Uri 07Z was 65,255 MW (AC rewritten); PUDL `scd_plants` has no
   lat/lon; HRRR accumulations live in `f01`; `coverage_history.csv` ends 2022.

## Pitch claims found wrong or stale (say them differently on stage)

- "$500k/yr" FERC screen — the threshold is ours, not FERC's.
- "sixteen states" require GETs consideration — 23 by July 2026.
- "$1.9B awarded this fall" — SPARK selections not announced as of 2026-09-05.
- "~20 % conversion" — LBNL Queued Up 2026 reports 13 %.
- "55 % fee reduction" — not in the ADVANCE Act text.

Remaining `[UNVERIFIED]` tags (35) are enumerated per ledger with what would verify each.
