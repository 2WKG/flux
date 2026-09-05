---
title: "Ingestion operations — refresh, backfill, lineage, freshness"
issue: 2WKG-284
parent: 2WKG-277
created: 2026-09-05
owner: Ghadi Khoury
---

# Ingestion operations

Operational layer on top of the existing design. **This does not restate**
`data/sources/ingest/README.md` — that file already fixes the four layers, the raw/staging
split, and the invariants (idempotence, revisions, missingness, units, county key, time).
Read it first; this file adds only what it does not cover: **ownership, refresh, retry,
backfill, and freshness.**

Per-source values live in `datasets/operations.json`, joined to `datasets/catalog.json` on `id`.

- `catalog.json` — what a source *is* and how to obtain it (69 sources, inventory)
- `operations.json` — who owns it, how often it changes, how it refreshes, when it is stale (10 P0 sources, operated)

**Absent from `operations.json` means not yet operated, not exempt.** A source may not back a
displayed number until it has an entry.

---

## 1. Refresh

Two modes, chosen by the publisher's behaviour, not by preference.

| Mode | When | Rule |
|---|---|---|
| `full` | Publisher reissues a whole artifact per release (TIGER, NRI, ACTIVSg2000) | Fetch the release, write a new `data/raw/<source>/<release>/`. Never overwrite a prior release. |
| `incremental` | Publisher appends time partitions (EIA-930, HRRR, ERCOT, Storm Events) | Fetch only partitions not already landed, plus any inside the publisher's revision window. |

**All triggers are `manual`.** There is no scheduler. This is recorded explicitly so nobody
assumes data refreshes itself — a stale dashboard with no scheduler is a silent failure, and
naming it makes it loud.

### Revision windows are not corruption

EIA-930 revises roughly 30 days; NOAA Storm Events adds events retroactively. A partition
re-fetched later can legitimately differ from the one already landed. Keep both under distinct
`source_release` values, per the ingest README's Revisions rule. **A changed value inside a
declared revision window is expected. A changed value outside one is a defect** — that is the
only version of this check that is worth running.

---

## 2. Retry

Applies to fetches, not to parsing. A parse failure is a defect and must surface, never retry.

- Retry only transient network conditions: timeouts, connection resets, HTTP 429, 5xx.
- Never retry 4xx other than 429. A 403 or 404 means the access route changed — fix the
  catalog entry, do not hammer the publisher.
- Exponential backoff, capped. Three attempts is sufficient for the sources here.
- Honour `Retry-After` when present.
- A source that exhausts its retries is **failed, not empty**. It must not land a zero-row
  artifact that a downstream job reads as "no outages."

That last point is the ingest README's missingness rule at the fetch layer: null is unknown,
never zero.

---

## 3. Backfill

`operations.json` records a `backfill` value per source because the three cases behave differently.

| Value | Meaning | Consequence |
|---|---|---|
| `safe` | Any prior window is re-fetchable and idempotent | Re-run freely. Row counts and checksums must match on an identical re-run. |
| `bounded` | Only a stated window is re-fetchable (HRRR archive cost, ERCOT report retention) | Backfill within the window; outside it, the data is whatever we already captured. |
| `none` | Publisher serves current state only | History cannot be reconstructed. Capture is one-shot. |

**Procedure:** name the window, land into a new `source_release`, verify counts against the
prior release, then repoint the curated table. Never delete the prior raw artifact — the
rollback path is repointing, not re-fetching.

**A gap is a gap.** If a `bounded` or `none` source has a hole, it stays a hole and is reported.
Interpolating across it manufactures data, which the project's honesty rules forbid outright.

---

## 4. Lineage

The ingest README already requires SHA-256, publisher release, retrieval time, source URL,
licence reference, and loader version per ingest. The operational addition is one line:

**Every landed artifact appends one record to an append-only ingest log** carrying `source_id`,
`source_release`, `retrieved_at_utc`, `source_url`, `sha256`, `bytes`, `row_count`, `loader_version`,
and `status` (`ok` | `failed` | `partial`).

Append-only, because the questions this has to answer are historical: *when did this number last
change, and which artifact produced it?* A log that is overwritten cannot answer either.
`status: failed` rows are kept — a failure that leaves no trace is indistinguishable from a
source nobody tried.

---

## 5. Freshness and alerting

`freshness_sla_hours` is the age past which a source is stale. `null` means static — a source
that cannot go stale, not one exempt from checking.

| Source class | SLA | Rationale |
|---|---|---|
| Hourly operational (EIA-930, ERCOT, HRRR) | 24–48 h | Tolerates a publisher lag without being useless |
| Monthly with late arrivals (Storm Events) | 60 days | Retroactive additions make anything tighter noise |
| Annual (EIA-860 via PUDL) | 365 days | Annual publication |
| Static (ACTIVSg2000, TIGER, NRI, DoD) | `null` | Version-pinned; staleness is not the failure mode, version drift is |

**A stale source must not silently back a displayed number.** Required behaviour, in order of
preference: show the value with its age and staleness stated, or withhold it. Never show it
unlabelled.

### What alerting must cover

Stated as requirements, not implemented — there is no scheduler to hang them on yet.

1. **Staleness** — any source past its SLA.
2. **Failed ingest** — a `status: failed` row appended.
3. **Silent success** — a run that completes with zero rows where the previous release had many.
   This is the dangerous one: it looks like success everywhere except the row count.
4. **Out-of-window change** — a value differing from a prior release outside a declared revision
   window.

Alert to a person, and name that person in `operations.json`. Every `owner` currently reads
`unassigned`, which is accurate for this team and is itself the finding: **no source has an
accountable owner yet.** That is the first thing to fix when this leaves hackathon scope.

---

## 6. Acceptance walkthrough — `eia-930`

The issue's criterion is that a documented source can be ingested reproducibly, backfilled
safely, and monitored for freshness. Worked end to end:

- **Reproducible** — `catalog.json` gives the access route; `operations.json` gives
  `refresh_mode: incremental`. Landing writes `data/raw/eia-930/<release>/` plus an ingest-log
  row with SHA-256 and row count. A second identical run produces identical counts and checksums
  (ingest README, Idempotence).
- **Backfilled safely** — `backfill: safe`. Re-fetch a named window into a new `source_release`,
  verify against the prior release, repoint. The prior artifact stays.
- **Monitored** — `freshness_sla_hours: 48`. Past 48 h the source is stale and its numbers are
  labelled or withheld. Its ~30-day revision window means an in-window change is expected and an
  out-of-window change alerts.

## References

- `data/sources/ingest/README.md` — four layers, invariants, contract tables
- `datasets/catalog.json` — source inventory (69)
- `datasets/operations.json` — operational metadata (10 P0)
