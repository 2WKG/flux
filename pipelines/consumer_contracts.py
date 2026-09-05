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
    row = con.execute("SELECT value FROM schema_meta WHERE key = 'contract_version'").fetchone()
    if row is None:
        return 'missing contract element "schema_meta.contract_version"'
    if row[0] != SCHEMA_VERSION:
        return f'invalid contract element "schema_meta.contract_version": expected {SCHEMA_VERSION}, found {row[0]!r}'
    return None


def _unavailable(consumer: str, reason: str) -> ConsumerResult:
    return ConsumerResult(
        consumer=consumer,
        status="unavailable",
        unavailable_code="invalid_prerequisite",
        reason=reason,
    )


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
            results=tuple(_unavailable(consumer, reason) for consumer in CONSUMER_READ_PATHS),
        )

    results: list[ConsumerResult] = []
    for consumer, read_path in CONSUMER_READ_PATHS.items():
        try:
            with duckdb.connect(str(fixture_path), read_only=True) as con:
                version_error = _contract_version_error(con)
                if version_error is not None:
                    results.append(_unavailable(consumer, version_error))
                    continue
                read_path(con)
        except duckdb.Error as error:
            results.append(_unavailable(consumer, f"{consumer} fixture contract read failed: {error}"))
        else:
            results.append(ConsumerResult(consumer=consumer, status="available"))
    return ContractReport(fixture_path=fixture_path, results=tuple(results))
