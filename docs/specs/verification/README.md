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

Cross-spec view (per-spec counts, load-bearing corrections, every open `[UNVERIFIED]` tag,
wrong pitch claims): [`../VERIFICATION.md`](../VERIFICATION.md).

## Cross-document contradictions still open (2026-09-05)

- `docs/plans/data-collection-and-curation-plan.md` (Mira's spec-01 lane plan) uses the
  June-2016 `Texas2000_June2016.xlsx` as the ACTIVSg2000 source of record and expects
  "2000 / 3206 / 254" rows from it. Ledger `01-02.md` shows that xlsx is a previous case
  version (2,007 buses, 49,776 MW; 98 of 2,000 bus ids match the pip case). The plan's Step 1
  should load the CURRENT zip's `ACTIVSg2000.aux` (see `01-data-ingest.md` S1 and
  `DEPENDENCIES.md`). Owner: Mira; not edited here.
- Same plan leaves DuckDB vs Postgres/PostGIS as a `[DECISION]`; every spec and every gate in
  `docs/build/converging-swarm-target.md` assumes DuckDB. Decide before U0.
