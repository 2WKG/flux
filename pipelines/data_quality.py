"""Offline data-quality gate for curated Flux DuckDB artifacts.

The gate is deliberately local: it writes a reviewable JSON report and returns a
non-zero status for material findings.  Delivery of notifications and a live
dashboard belong to future platform work; this module makes their inputs
explicit without pretending either exists.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import duckdb

from pipelines.db import SCHEMA_VERSION, TABLE_COLUMNS, ensure_schema, validate_schema


# Relations and domains are checked even though a freshly-created v1 database
# enforces them.  This catches imported or legacy artifacts before promotion.
FOREIGN_KEYS = (
    ("buses", "county_fips", "counties", "county_fips"),
    ("lines", "from_bus", "buses", "bus_id"),
    ("lines", "to_bus", "buses", "bus_id"),
    ("gens", "bus_id", "buses", "bus_id"),
    ("loads", "bus_id", "buses", "bus_id"),
    ("critical_loads", "county_fips", "counties", "county_fips"),
    ("critical_loads", "bus_id", "buses", "bus_id"),
    ("eaglei_outages", "county_fips", "counties", "county_fips"),
    ("weather_hourly", "county_fips", "counties", "county_fips"),
    ("storm_events", "county_fips", "counties", "county_fips"),
    ("hazard_static", "county_fips", "counties", "county_fips"),
    ("site_candidates", "county_fips", "counties", "county_fips"),
    ("site_candidates", "bus_id", "buses", "bus_id"),
    ("outage_predictions", "scenario_id", "scenarios", "scenario_id"),
    ("outage_predictions", "county_fips", "counties", "county_fips"),
    ("cascade_runs", "scenario_id", "scenarios", "scenario_id"),
    ("cascade_runs", "counterfactual_site_id", "site_candidates", "site_id"),
    ("site_scores", "site_id", "site_candidates", "site_id"),
    ("site_scores", "scenario_id", "scenarios", "scenario_id"),
    ("line_upgrade_scores", "line_id", "lines", "line_id"),
    ("line_upgrade_detail", "line_id", "lines", "line_id"),
)

ACCEPTED_VALUES = {
    ("critical_loads", "kind"): {"dod", "hospital", "water"},
    ("scenarios", "kind"): {"historical", "forecast", "synthetic"},
    ("outage_predictions", "driver"): {"ice", "wind", "heat", "wildfire", "flood", "other"},
    ("site_candidates", "kind"): {"coal_retired", "coal_retiring", "nuclear_existing", "doe_federal", "dod"},
    ("line_upgrade_detail", "best_tech"): {"dlr", "reconductor"},
    ("line_upgrade_detail", "congestion_method"): {"exact", "fuzzy", "twin_proxy", "unmapped"},
}


def _alert(code: str, message: str, *, owner: str = "unassigned", severity: str = "error", next_step: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message, "owner": owner, "next_step": next_step}


def _table_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[Any, ...]]:
    return con.execute(f"PRAGMA table_info('{table}')").fetchall()


def _database_checks(con: duckdb.DuckDBPyConnection) -> tuple[dict[str, int], list[dict[str, str]]]:
    alerts: list[dict[str, str]] = []
    counts: dict[str, int] = {}
    try:
        validate_schema(con)
        version = con.execute("SELECT value FROM schema_meta WHERE key = 'contract_version'").fetchone()
        if version != (SCHEMA_VERSION,):
            raise RuntimeError(f"schema_meta contract_version is {version!r}, expected {(SCHEMA_VERSION,)!r}.")
        expected = duckdb.connect(":memory:")
        try:
            ensure_schema(expected)
            expected_constraints = {
                (row[0], row[1], tuple(row[2] or []))
                for row in expected.execute("SELECT table_name, constraint_type, constraint_column_names FROM duckdb_constraints()").fetchall()
            }
        finally:
            expected.close()
        actual_constraints = {
            (row[0], row[1], tuple(row[2] or []))
            for row in con.execute("SELECT table_name, constraint_type, constraint_column_names FROM duckdb_constraints()").fetchall()
        }
        missing_constraints = expected_constraints - actual_constraints
        if missing_constraints:
            raise RuntimeError(f"schema is missing {len(missing_constraints)} v1 constraint(s).")
    except RuntimeError as exc:
        alerts.append(_alert("schema_contract", str(exc), next_step="Rebuild or migrate the artifact before publishing it."))
        return counts, alerts

    for table in TABLE_COLUMNS:
        counts[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        columns = _table_columns(con, table)
        required = [row[1] for row in columns if row[3]]
        if required:
            where = " OR ".join(f'"{column}" IS NULL' for column in required)
            missing = con.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0]
            if missing:
                alerts.append(_alert("null_required", f"{table} has {missing} row(s) with a required value missing.", next_step="Repair the loader output and rebuild the curated artifact."))
        primary_key = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
        if primary_key:
            keys = ", ".join(f'"{column}"' for column in primary_key)
            duplicates = con.execute(f"SELECT count(*) FROM (SELECT {keys} FROM {table} GROUP BY {keys} HAVING count(*) > 1)").fetchone()[0]
            if duplicates:
                alerts.append(_alert("duplicate_key", f"{table} has {duplicates} duplicate primary-key group(s).", next_step="Deduplicate the source release and rerun the loader."))

    for child, child_col, parent, parent_col in FOREIGN_KEYS:
        missing = con.execute(
            f"SELECT count(*) FROM {child} c LEFT JOIN {parent} p ON c.{child_col} = p.{parent_col} "
            f"WHERE c.{child_col} IS NOT NULL AND p.{parent_col} IS NULL"
        ).fetchone()[0]
        if missing:
            alerts.append(_alert("referential_integrity", f"{child}.{child_col} has {missing} orphaned reference(s) to {parent}.{parent_col}.", next_step="Load the parent artifact or correct the foreign key before promotion."))

    for (table, column), values in ACCEPTED_VALUES.items():
        allowed = ", ".join("?" for _ in values)
        invalid = con.execute(
            f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL AND {column} NOT IN ({allowed})", list(values)
        ).fetchone()[0]
        if invalid:
            alerts.append(_alert("accepted_values", f"{table}.{column} has {invalid} value(s) outside its contract.", next_step="Map source values to the contract enum or reject the release."))
    return counts, alerts


def _load_json_lines(path: Path) -> list[dict[str, Any]]:
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            records.append({"_malformed": f"line {number}: {exc.msg}"})
    return records


def _operations_checks(
    con: duckdb.DuckDBPyConnection,
    operations: dict[str, Any],
    ingest_log: Iterable[dict[str, Any]] | None,
    now: datetime,
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    records = list(ingest_log or [])
    by_source: dict[str, list[tuple[datetime, dict[str, Any]]]] = defaultdict(list)
    for record in records:
        if "_malformed" in record:
            alerts.append(_alert("malformed_ingest_log", f"Ingest log is malformed: {record['_malformed']}", next_step="Repair the append-only log record and rerun the gate."))
            continue
        source_id = record.get("source_id")
        try:
            retrieved_at = datetime.fromisoformat(str(record["retrieved_at_utc"]).replace("Z", "+00:00"))
            if retrieved_at.tzinfo is None or retrieved_at.utcoffset() != timedelta(0):
                raise ValueError("timestamp must be UTC-aware")
            if retrieved_at > now + timedelta(minutes=5):
                raise ValueError("timestamp is in the future")
        except (KeyError, ValueError, TypeError):
            alerts.append(_alert("malformed_ingest_log", f"{source_id or 'unknown source'} has an invalid retrieved_at_utc timestamp.", next_step="Repair the append-only log record and rerun the gate."))
            continue
        if source_id:
            by_source[str(source_id)].append((retrieved_at, record))

    source_names_sql = " UNION ALL ".join(f"SELECT source_name FROM {table}" for table in TABLE_COLUMNS)
    curated_counts = dict(con.execute(
        f"SELECT source_name, count(*) FROM ({source_names_sql}) GROUP BY source_name"
    ).fetchall())
    source_names = set(curated_counts)
    operated_ids = {source["id"] for source in operations["sources"]}
    for source_id in sorted(source_names - operated_ids):
        alerts.append(_alert("unoperated_source", f"Curated rows cite {source_id}, which has no operations record.", next_step="Add ownership, refresh, and freshness metadata before dashboard promotion."))
    if source_names and not records:
        alerts.append(_alert("reconciliation_unavailable", "Curated rows have provenance but no append-only ingest log was supplied.", severity="warning", next_step="Run with --ingest-log before relying on a dashboard."))

    for source in operations["sources"]:
        source_id = source["id"]
        owner = source["owner"]
        timestamped_rows = by_source.get(source_id, [])
        rows = [row for _, row in timestamped_rows]
        failed = [row for row in rows if row.get("status") == "failed"]
        if failed:
            alerts.append(_alert("failed_ingest", f"{source_id} has {len(failed)} failed ingest record(s).", owner=owner, next_step="Investigate the latest failed source release; do not treat it as empty."))
        ok = [row for row in rows if row.get("status") == "ok"]
        if timestamped_rows and max(timestamped_rows, key=lambda item: item[0])[1].get("status") == "partial":
            alerts.append(_alert("partial_ingest", f"{source_id}'s latest ingest record is partial.", owner=owner, next_step="Complete or explicitly reject the source release before promotion."))
        if ok and all(int(row.get("row_count", 0)) == 0 for row in ok):
            alerts.append(_alert("zero_row_success", f"{source_id} reported success with zero rows.", owner=owner, next_step="Compare the release with its prior row count and repair the fetch or parser."))
        if source["freshness_sla_hours"] is not None and ok:
            latest = max(timestamp for timestamp, row in timestamped_rows if row.get("status") == "ok")
            age_hours = (now - latest).total_seconds() / 3600
            if age_hours > source["freshness_sla_hours"]:
                alerts.append(_alert("stale_source", f"{source_id} is {age_hours:.1f} hours old; SLA is {source['freshness_sla_hours']} hours.", owner=owner, next_step="Refresh the source or label/withhold dependent values."))
        if source_id in source_names and not ok:
            alerts.append(_alert("source_curated_mismatch", f"Curated rows cite {source_id}, but no successful ingest-log record exists.", owner=owner, next_step="Restore the matching ingest record or rebuild from a logged source release."))
        if ok and source_id in source_names:
            expected = ok[-1].get("curated_row_count")
            if expected is None:
                alerts.append(_alert("reconciliation_unavailable", f"{source_id} has no curated_row_count in its latest successful ingest record.", owner=owner, severity="warning", next_step="Record the transformed row count at ingest, then rerun the gate."))
            elif int(expected) != curated_counts[source_id]:
                alerts.append(_alert("source_curated_mismatch", f"{source_id} logged {expected} curated rows but the artifact contains {curated_counts[source_id]}.", owner=owner, next_step="Rebuild from the logged release or correct the append-only ingest record."))
    return alerts


def _api_health(url: str | None) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Probe an explicitly supplied health URL; never invent a service endpoint."""
    if not url:
        return {"status": "unavailable", "message": "No API health URL was supplied."}, []
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "flux-quality-gate/1.0"}), timeout=5) as response:
            if 200 <= response.status < 300:
                return {"status": "healthy", "url": url, "message": f"HTTP {response.status}"}, []
            raise urllib.error.HTTPError(url, response.status, "non-success status", response.headers, None)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        alert = _alert("api_health", f"API health probe failed for {url}: {exc}", next_step="Restore the configured API health endpoint before an API-backed release.")
        return {"status": "unhealthy", "url": url, "message": str(exc)}, [alert]


def run_quality_gate(
    database: str | Path,
    operations_path: str | Path,
    *,
    ingest_log_path: str | Path | None = None,
    previous_counts_path: str | Path | None = None,
    api_health_url: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable report; callers choose how to deliver alerts."""
    now = now or datetime.now(UTC)
    operations = json.loads(Path(operations_path).read_text(encoding="utf-8"))
    con = duckdb.connect(str(database), read_only=True)
    try:
        counts, alerts = _database_checks(con)
        ingest_log = _load_json_lines(Path(ingest_log_path)) if ingest_log_path else None
        alerts.extend(_operations_checks(con, operations, ingest_log, now))
    finally:
        con.close()

    if previous_counts_path:
        previous = json.loads(Path(previous_counts_path).read_text(encoding="utf-8"))
        for table, before in previous.items():
            after = counts.get(table)
            if after is not None and before and after < before:
                alerts.append(_alert("volume_regression", f"{table} fell from {before} to {after} rows.", next_step="Review the release diff before promoting the curated artifact."))
    else:
        alerts.append(_alert("volume_baseline_missing", "No reviewed expected row-count baseline was supplied.", next_step="Provide --previous-counts with declared minimum counts before dashboard promotion."))
    if not ingest_log_path:
        alerts.append(_alert("reconciliation_unavailable", "No append-only ingest log was supplied.", next_step="Provide --ingest-log before dashboard promotion."))
    api_health, api_alerts = _api_health(api_health_url)
    alerts.extend(api_alerts)

    return {
        "checked_at": now.astimezone(UTC).isoformat(),
        "database": str(database),
        "row_counts": counts,
        "alerts": alerts,
        "dashboard_eligible": not any(alert["severity"] == "error" for alert in alerts),
        "api_health": api_health,
        "delivery": "No notification or dashboard is configured; consume this report in the release workflow.",
    }
