---
title: "Data quality gate and offline observability"
issue: 2WKG-288
created: 2026-09-05
---

# Data quality gate

`scripts/validate_data_quality.py` is the release gate for a curated DuckDB
artifact. It produces a JSON report, returns exit code `1` for an error, and
must run before a dashboard presents the artifact as current. It is deliberately
an offline check: Flux has no scheduler, monitoring service, alert delivery, or
runtime API health endpoint in this checkout.

```powershell
uv run --extra dev python scripts/validate_data_quality.py data/duck/grid.duckdb `
  --ingest-log data/ingest-log.jsonl `
  --previous-counts data/previous-row-counts.json `
  --api-health-url http://127.0.0.1:8000/health `
  --report data/quality-report.json
```

The optional ingest log is JSONL. Each append-only record needs `source_id`,
`status` (`ok`, `failed`, or `partial`), `row_count`, and `retrieved_at_utc`.
Successful records for sources used by the artifact also carry
`curated_row_count`: the transformed count written after the raw source count,
which the gate independently compares with the current curated rows for that
`source_name`. `datasets/operations.json` does not emit this log yet; the
ingestion owner must add this required audit field before any dashboard release.
It is the source/release evidence described in the ingestion operations guide.
`--previous-counts` is a reviewed JSON object such as `{ "weather_hourly": 6100 }`.
It is required for dashboard promotion and supplies a minimum expected count;
the first reviewed release establishes it outside the gate.

## What blocks dashboard reliance

The report checks the versioned schema, required-value nulls, primary-key
duplicates, foreign keys, contract enums, row-count regressions, failed and
zero-row ingests, source-to-curated reconciliation, and source freshness from
`datasets/operations.json`. Every alert names an owner and next action. An
unassigned owner stays visible; it is not silently routed.

`dashboard_eligible: false` is the actionable alert: the script exits nonzero
and the artifact must not be promoted. Missing ingest lineage or an expected
row-count baseline fails closed. Notification delivery is intentionally not claimed; a release workflow
or future monitoring service can consume the report.

## Triage

1. **Schema, null, key, enum, or foreign-key error:** stop promotion; repair the
   loader or run an explicit migration, then rebuild the curated artifact.
2. **Volume regression or zero-row success:** compare the release against the
   prior raw artifact. A publisher revision is only acceptable inside the source's
   declared revision window; otherwise treat it as a defect.
3. **Failed or stale source:** the named source owner refreshes or repairs it;
   dependent values are labelled stale or withheld as required by
   [ingestion operations](ingestion-operations.md).
4. **Reconciliation mismatch:** restore the append-only ingest record or rebuild
   the curated data from a logged release. Do not infer lineage from a dashboard.

`--api-health-url` performs a five-second HTTP probe when a real endpoint is
available. Without it, `api_health.status` is explicitly **`unavailable`**, not
healthy. The gate never presents artifact health as API or notification health.
