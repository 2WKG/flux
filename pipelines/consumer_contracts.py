"""Offline fixture compatibility checks for Flux's data consumers.

The fixture database is the hand-off boundary between the ingest pipeline and
the product units.  This module deliberately checks that boundary through a
small, named read path for each consumer rather than relying on schema creation
alone.  A future consumer can extend ``CONSUMER_READ_PATHS`` with its own
minimal read without changing the report format.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb

from pipelines.db import SCHEMA_VERSION


@dataclass(frozen=True)
class ContractElement:
    """One table and its columns required by a consumer's fixture read."""

    table: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class ConsumerResult:
    """The available or documented-unavailable result of one read path."""

    consumer: str
    status: str
    unavailable_code: str | None = None
    reason: str | None = None
    diagnostic_kind: Literal["artifact_unavailable", "contract_violation"] | None = None

    @property
    def available(self) -> bool:
        return self.status == "available"


@dataclass(frozen=True)
class ContractReport:
    """Stable, machine-readable result returned by the offline harness."""

    fixture_path: Path
    results: tuple[ConsumerResult, ...]

    @property
    def available(self) -> bool:
        return all(result.available for result in self.results)

    def result_for(self, consumer: str) -> ConsumerResult:
        for result in self.results:
            if result.consumer == consumer:
                return result
        raise KeyError(f"unknown consumer: {consumer}")


ReadPath = Callable[[duckdb.DuckDBPyConnection], None]


# These values deliberately stay separate from ``unavailable_code``.  The
# latter is the stable consumer-envelope code, while this category lets a UI
# or runbook tell a missing/unreadable hand-off artifact from a fixture that
# exists but violates the data contract.
ARTIFACT_UNAVAILABLE = "artifact_unavailable"
CONTRACT_VIOLATION = "contract_violation"

# The DDL permits the optional source version and retrieval timestamp to be
# NULL when an upstream record did not publish them.  These identifiers are
# not optional: without them a fixture row cannot be traced or reproduced.
REQUIRED_PROVENANCE_FIELDS = ("source_name", "source_ref", "fixture_batch_id")


def _read_elements(elements: Sequence[ContractElement]) -> ReadPath:
    """Build a real, bounded DuckDB read for a consumer's required elements."""

    def read(con: duckdb.DuckDBPyConnection) -> None:
        for element in elements:
            columns = ", ".join(f'"{column}"' for column in element.columns)
            # ``LIMIT 0`` reads the relation through DuckDB's normal binder and
            # planner without requiring a populated fixture or external data.
            con.execute(f'SELECT {columns} FROM "{element.table}" LIMIT 0')

    return read


# These are product-facing data boundaries, not a duplicate of the full ingest
# schema.  Each list contains only the columns the named consumer needs to
# begin its documented fixture read.  Later issues may add consumer-specific
# read functions while preserving this report contract.
CONSUMER_REQUIREMENTS: dict[str, tuple[ContractElement, ...]] = {
    "twin": (
        ContractElement("buses", ("bus_id", "base_kv", "lon", "lat")),
        ContractElement("lines", ("line_id", "from_bus", "to_bus", "r_pu", "x_pu", "rate_a_mw")),
        ContractElement("gens", ("gen_id", "bus_id", "pmax_mw")),
        ContractElement("loads", ("load_id", "bus_id", "p_mw_nominal")),
    ),
    "outage": (
        ContractElement("counties", ("county_fips", "name", "pop")),
        ContractElement("weather_hourly", ("county_fips", "ts", "wind_ms", "gust_ms", "temp_c", "ice_mm")),
        ContractElement("hazard_static", ("county_fips", "nri_score", "wildfire_hazard", "seismic_pga")),
        ContractElement("scenarios", ("scenario_id", "kind", "ts_start", "ts_end")),
    ),
    "siting": (
        ContractElement("site_candidates", ("site_id", "county_fips", "bus_id", "capacity_slot_mw")),
        ContractElement("hazard_static", ("county_fips", "nri_score", "wildfire_hazard", "seismic_pga")),
        ContractElement("cascade_runs", ("run_id", "scenario_id", "lost_load_mw", "counterfactual_site_id")),
    ),
    "api": (
        ContractElement("outage_predictions", ("scenario_id", "county_fips", "ts", "p_out", "customers_at_risk")),
        ContractElement("cascade_runs", ("run_id", "scenario_id", "hour", "lost_load_mw")),
        ContractElement("site_scores", ("site_id", "scenario_id", "unit_mw", "safety_score", "grid_value_score")),
        ContractElement("line_upgrade_scores", ("line_id", "mw_per_musd", "ferc_screen_pass")),
    ),
    "retrieval": (
        ContractElement("corpus_chunks", ("chunk_id", "doc", "title", "page", "text", "embedding")),
    ),
}

CONSUMER_READ_PATHS: dict[str, ReadPath] = {
    consumer: _read_elements(elements) for consumer, elements in CONSUMER_REQUIREMENTS.items()
}


def _contract_version_error(con: duckdb.DuckDBPyConnection) -> str | None:
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    if "schema_meta" not in tables:
        return 'missing table "schema_meta" required for contract version'
    columns = {row[1] for row in con.execute("PRAGMA table_info('schema_meta')").fetchall()}
    for column in ("key", "value"):
        if column not in columns:
            return f'missing field "schema_meta.{column}" required for contract version'
    row = con.execute("SELECT value FROM schema_meta WHERE key = 'contract_version'").fetchone()
    if row is None:
        return 'missing contract element "schema_meta.contract_version"'
    if row[0] != SCHEMA_VERSION:
        return f'invalid contract element "schema_meta.contract_version": expected {SCHEMA_VERSION}, found {row[0]!r}'
    return None


def _artifact_unavailable(consumer: str, reason: str) -> ConsumerResult:
    return ConsumerResult(
        consumer=consumer,
        status="unavailable",
        unavailable_code="invalid_prerequisite",
        reason=reason,
        diagnostic_kind=ARTIFACT_UNAVAILABLE,
    )


def _contract_violation(consumer: str, reason: str) -> ConsumerResult:
    return ConsumerResult(
        consumer=consumer,
        status="unavailable",
        unavailable_code="invalid_prerequisite",
        reason=f"contract violation: {reason}",
        diagnostic_kind=CONTRACT_VIOLATION,
    )


def _columns_for_table(con: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()}


def _require_contract_elements(
    con: duckdb.DuckDBPyConnection,
    elements: Sequence[ContractElement],
) -> str | None:
    """Return the first missing named element before a consumer read runs."""

    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    for element in elements:
        if element.table not in tables:
            return f'missing table "{element.table}"'
        columns = _columns_for_table(con, element.table)
        for column in element.columns:
            if column not in columns:
                return f'missing field "{element.table}.{column}"'
    for element in elements:
        columns = _columns_for_table(con, element.table)
        for column in REQUIRED_PROVENANCE_FIELDS:
            if column not in columns:
                return f'missing field "{element.table}.{column}"'
    return None


def _coordinate_contract_error(
    con: duckdb.DuckDBPyConnection,
    elements: Sequence[ContractElement],
) -> str | None:
    """Detect decimal-degree coordinates that cannot be EPSG:4326.

    WKB has no SRID in the shared DDL, so this deliberately validates only the
    named longitude/latitude fields that a consumer actually reads.  A row
    outside these bounds is not a missing artifact; it is a contract breach.
    """

    for element in elements:
        columns = set(element.columns)
        if not {"lon", "lat"}.issubset(columns):
            continue
        for field, lower, upper, axis in (
            ("lon", -180, 180, "longitude"),
            ("lat", -90, 90, "latitude"),
        ):
            row = con.execute(
                f'''SELECT 1 FROM "{element.table}"
                    WHERE "{field}" IS NULL
                       OR "{field}" < ?
                       OR "{field}" > ?
                    LIMIT 1''',
                [lower, upper],
            ).fetchone()
            if row is not None:
                return (
                    f'field "{element.table}.{field}" is not a valid '
                    f'EPSG:4326 {axis} in [{lower}, {upper}]'
                )
    return None


def _provenance_contract_error(
    con: duckdb.DuckDBPyConnection,
    elements: Sequence[ContractElement],
) -> str | None:
    """Ensure populated fixture rows retain the required lineage fields."""

    for element in elements:
        for field in REQUIRED_PROVENANCE_FIELDS:
            row = con.execute(
                f'''SELECT 1 FROM "{element.table}"
                    WHERE "{field}" IS NULL OR trim("{field}") = ''
                    LIMIT 1'''
            ).fetchone()
            if row is not None:
                return f'field "{element.table}.{field}" is blank or unavailable'
    return None


def check_consumer_contracts(path: str | Path) -> ContractReport:
    """Open ``path`` separately through twin, outage, siting, API and retrieval.

    The function is intentionally offline: it does not build a model, call a
    provider, or require fixture rows.  A missing database, schema version,
    table, or column returns the same explicit unavailable shape every product
    consumer is required to surface later.
    """

    fixture_path = Path(path)
    if not fixture_path.is_file():
        reason = f'fixture database unavailable: {fixture_path} does not exist'
        return ContractReport(
            fixture_path=fixture_path,
            results=tuple(_artifact_unavailable(consumer, reason) for consumer in CONSUMER_READ_PATHS),
        )

    results: list[ConsumerResult] = []
    for consumer, read_path in CONSUMER_READ_PATHS.items():
        try:
            with duckdb.connect(str(fixture_path), read_only=True) as con:
                version_error = _contract_version_error(con)
                if version_error is not None:
                    results.append(_contract_violation(consumer, version_error))
                    continue
                requirements_error = _require_contract_elements(con, CONSUMER_REQUIREMENTS[consumer])
                if requirements_error is not None:
                    results.append(_contract_violation(consumer, requirements_error))
                    continue
                coordinate_error = _coordinate_contract_error(con, CONSUMER_REQUIREMENTS[consumer])
                if coordinate_error is not None:
                    results.append(_contract_violation(consumer, coordinate_error))
                    continue
                provenance_error = _provenance_contract_error(con, CONSUMER_REQUIREMENTS[consumer])
                if provenance_error is not None:
                    results.append(_contract_violation(consumer, provenance_error))
                    continue
                read_path(con)
        except duckdb.Error as error:
            results.append(
                _artifact_unavailable(
                    consumer,
                    f"fixture database unavailable while reading {consumer}: {error}",
                )
            )
        else:
            results.append(ConsumerResult(consumer=consumer, status="available"))
    return ContractReport(fixture_path=fixture_path, results=tuple(results))
