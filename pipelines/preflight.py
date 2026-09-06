"""Read-only intake receipt for a safe, reproducible data rebuild.

This module deliberately does not call :func:`pipelines.db.connect`: that
helper initializes a schema on writable connections.  A preflight must be
able to inspect an old DuckDB file without changing even its access time at
the SQL layer, and must make a fresh output path the only rebuild target.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from pipelines.checks import run_checks
from pipelines.common import sha256_file
from pipelines.data_quality import (
    _curated_source_mappings,
    _operation_ids_for_curated_source,
)
from pipelines.db import SCHEMA_VERSION, TABLE_COLUMNS
from pipelines.state_scope import StateScope, StateScopeError, scope

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
P0_RAW_INPUTS_CATALOG = REPOSITORY_ROOT / "datasets" / "catalog.json"
SOURCE_RECEIPTS_DIR = REPOSITORY_ROOT / "data" / "sources"
OPERATIONS_PATH = REPOSITORY_ROOT / "datasets" / "operations.json"
DEFAULT_TEXAS_SCENARIOS = ("uri_2021", "beryl_2024")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _catalog_inputs(catalog: Path) -> tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]:
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
        return tuple(
            (item["label"], tuple(tuple(path) for path in item["paths"]))
            for item in data["p0_raw_inputs"]
        )
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid P0 raw-input catalog: {catalog}") from error


def _schema_fingerprint(path: Path) -> str | None:
    """Return a cheap, deterministic schema fingerprint when the format exposes one."""
    suffixes = path.suffixes
    try:
        if suffixes[-2:] == [".csv", ".gz"]:
            with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as source:
                header = next(csv.reader(source), [])
            return _sha256_text(json.dumps(header, separators=(",", ":")))
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                header = next(csv.reader(source), [])
            return _sha256_text(json.dumps(header, separators=(",", ":")))
        if path.suffix.lower() == ".parquet":
            # DuckDB can inspect Parquet metadata without scanning the data rows.
            con = duckdb.connect(":memory:")
            try:
                rows = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
            finally:
                con.close()
            return _sha256_text(json.dumps([(row[0], row[1]) for row in rows], separators=(",", ":")))
    except (OSError, StopIteration, UnicodeDecodeError, duckdb.Error):
        return None
    return None


def _receipt_index(receipts_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Index tracked publisher receipts by filename.

    Receipt metadata is intentionally only trusted when a file entry carries a
    SHA-256.  A catalog URL or a file's location alone is not provenance.
    """
    index: dict[str, list[dict[str, Any]]] = {}
    for receipt_path in sorted(receipts_dir.glob("*.json")):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        retrieved_at = receipt.get("retrieved_at")
        for filename, expected in receipt.get("files", {}).items():
            digest = expected.get("sha256") if isinstance(expected, dict) else None
            if not isinstance(digest, str):
                continue
            index.setdefault(filename, []).append(
                {
                    "receipt": str(receipt_path),
                    "sha256": digest.lower(),
                    "bytes": expected.get("bytes"),
                    "retrieved_at": retrieved_at,
                }
            )
    return index


def inspect_raw_inputs(
    raw_dir: str | Path,
    *,
    catalog: Path = P0_RAW_INPUTS_CATALOG,
    receipts_dir: Path = SOURCE_RECEIPTS_DIR,
) -> dict[str, Any]:
    """Return a machine-readable receipt without changing raw files.

    The receipt includes observed hashes for every P0 input.  It reports a
    verified lock only where a tracked publisher receipt supplied an expected
    digest; absence is explicit rather than silently accepted as verification.
    """
    raw = Path(raw_dir)
    receipt_index = _receipt_index(receipts_dir)
    artifacts: list[dict[str, Any]] = []
    for label, alternatives in _catalog_inputs(catalog):
        selected = next((raw.joinpath(*parts) for parts in alternatives if raw.joinpath(*parts).is_file()), None)
        if selected is None:
            artifacts.append(
                {
                    "label": label,
                    "status": "missing",
                    "acceptable_paths": [str(Path(*parts)) for parts in alternatives],
                    "observed": None,
                    "lock": {"status": "not_checked", "reason": "artifact is missing"},
                }
            )
            continue
        observed = {
            "path": str(selected),
            "bytes": selected.stat().st_size,
            "sha256": sha256_file(selected),
            "schema_fingerprint": _schema_fingerprint(selected),
        }
        expected = receipt_index.get(selected.name, [])
        matching = [
            item for item in expected
            if item["sha256"] == observed["sha256"]
            and (item["bytes"] is None or item["bytes"] == observed["bytes"])
        ]
        if not expected:
            lock = {
                "status": "unrecorded",
                "reason": "no tracked receipt supplies an expected SHA-256 for this artifact",
                "expected": [],
            }
            status = "present_unverified"
        elif matching:
            lock = {"status": "verified", "expected": matching}
            status = "ready"
        else:
            lock = {"status": "mismatch", "expected": expected}
            status = "checksum_mismatch"
        artifacts.append({"label": label, "status": status, "observed": observed, "lock": lock})

    return {
        "raw_dir": str(raw),
        "artifacts": artifacts,
        "all_present": all(item["status"] != "missing" for item in artifacts),
        "no_checksum_mismatch": not any(item["status"] == "checksum_mismatch" for item in artifacts),
        "all_locked_with_provenance": bool(artifacts) and all(item["lock"]["status"] == "verified" for item in artifacts),
    }


def inspect_database(path: str | Path | None) -> dict[str, Any]:
    """Inspect a DuckDB contract through a read-only connection only."""
    if path is None:
        return {"status": "not_requested", "write_performed": False}
    database = Path(path)
    if not database.is_file():
        return {
            "path": str(database), "status": "missing", "compatibility": "no_existing_release",
            "write_performed": False,
            "next_step": "Use a new output path for the staged rebuild; do not create a database here during preflight.",
        }
    before = sha256_file(database)
    try:
        con = duckdb.connect(str(database), read_only=True)
        try:
            tables = {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()}
            version = None
            if "schema_meta" in tables:
                row = con.execute("SELECT value FROM schema_meta WHERE key = 'contract_version'").fetchone()
                version = None if row is None else row[0]
            required = set(TABLE_COLUMNS) | {"schema_meta"}
            missing = sorted(required - tables)
        finally:
            con.close()
    except duckdb.Error as error:
        return {
            "path": str(database), "status": "unreadable", "compatibility": "incompatible",
            "write_performed": False, "error": str(error),
            "next_step": "Keep this file untouched and rebuild to a fresh output path.",
        }
    after = sha256_file(database)
    compatible = version == SCHEMA_VERSION and not missing
    return {
        "path": str(database),
        "status": "compatible" if compatible else "legacy_or_incompatible",
        "compatibility": "compatible" if compatible else "incompatible",
        "contract_version": version,
        "expected_contract_version": SCHEMA_VERSION,
        "missing_contract_tables": missing,
        "write_performed": False,
        "file_sha256_before": before,
        "file_sha256_after": after,
        "file_unchanged": before == after,
        "next_step": (
            "This file may be used only as a read-only comparison input; rebuild to a fresh output path."
            if not compatible else "Run read-only quality checks before any release decision."
        ),
    }


def _scenario_weather_readiness(
    database: Path, scenarios: tuple[str, ...], selected: StateScope
) -> dict[str, Any]:
    """Require complete hourly weather for every requested scenario/state window.

    A non-empty ``weather_hourly`` table is not evidence for a scenario.  Each
    selected state's loaded counties must have one row for every hour from the
    stored scenario start through end.  This prevents out-of-window or
    wrong-state weather from making a strict readiness check pass.
    """
    con = duckdb.connect(str(database), read_only=True)
    try:
        rows = []
        for scenario in scenarios:
            scenario_row = con.execute(
                "SELECT ts_start, ts_end FROM scenarios WHERE scenario_id = ?", [scenario]
            ).fetchone()
            state_rows = []
            if scenario_row is not None:
                ts_start, ts_end = scenario_row
                expected_hours = int((ts_end - ts_start).total_seconds() // 3600) + 1
                for state in selected.states:
                    county_count = con.execute(
                        "SELECT count(*) FROM counties WHERE substr(county_fips, 1, 2) = ?",
                        [state.fips],
                    ).fetchone()[0]
                    weather_rows, weather_counties, weather_hours, first_hour, last_hour = con.execute(
                        """SELECT count(*), count(DISTINCT weather.county_fips),
                                  count(DISTINCT weather.ts), min(weather.ts), max(weather.ts)
                           FROM weather_hourly AS weather
                           JOIN counties USING (county_fips)
                           WHERE substr(counties.county_fips, 1, 2) = ?
                             AND weather.ts >= ? AND weather.ts <= ?""",
                        [state.fips, ts_start, ts_end],
                    ).fetchone()
                    expected_rows = county_count * expected_hours
                    state_rows.append(
                        {
                            "state": {"fips": state.fips, "usps": state.usps, "name": state.name},
                            "county_count": county_count,
                            "weather_counties": weather_counties,
                            "weather_rows": weather_rows,
                            "weather_hours": weather_hours,
                            "expected_weather_rows": expected_rows,
                            "first_hour": first_hour.isoformat() if first_hour else None,
                            "last_hour": last_hour.isoformat() if last_hour else None,
                            "ready": (
                                county_count > 0
                                and weather_counties == county_count
                                and weather_hours == expected_hours
                                and weather_rows == expected_rows
                                and first_hour == ts_start
                                and last_hour == ts_end
                            ),
                        }
                    )
            rows.append(
                {
                    "scenario_id": scenario,
                    "scenario_present": scenario_row is not None,
                    "ts_start": scenario_row[0].isoformat() if scenario_row else None,
                    "ts_end": scenario_row[1].isoformat() if scenario_row else None,
                    "states": state_rows,
                    "ready": scenario_row is not None and bool(state_rows) and all(row["ready"] for row in state_rows),
                }
            )
    except duckdb.Error as error:
        return {"status": "unavailable", "reason": str(error), "scenarios": []}
    finally:
        con.close()
    return {
        "status": "ready" if rows and all(row["ready"] for row in rows) else "unavailable",
        "scenarios": rows,
        "reason": "Each selected state's counties need complete hourly weather across the stored scenario window before claiming outage, cascade, or full-Flux readiness.",
    }


def _operation_id_alignment(database: Path) -> dict[str, Any]:
    """Detect the source-ID mismatch that blocks dashboard-quality promotion."""
    try:
        operations = json.loads(OPERATIONS_PATH.read_text(encoding="utf-8"))
        operation_ids = {str(item["id"]) for item in operations["sources"]}
        mappings = _curated_source_mappings(operations)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return {"status": "unavailable", "reason": f"invalid operations metadata: {error}"}
    con = duckdb.connect(str(database), read_only=True)
    try:
        union = " UNION ALL ".join(
            f"SELECT source_name, source_version FROM {table}" for table in TABLE_COLUMNS
        )
        curated = {
            (row[0], row[1])
            for row in con.execute(f"SELECT DISTINCT source_name, source_version FROM ({union})").fetchall()
        }
    except duckdb.Error as error:
        return {"status": "unavailable", "reason": str(error)}
    finally:
        con.close()
    unoperated, mapped = [], set()
    for source_name, source_version in sorted(curated, key=lambda item: (item[0], item[1] or "")):
        mapping = _operation_ids_for_curated_source(
            source_name, source_version, operated_ids=operation_ids, mappings=mappings
        )
        if mapping is None:
            unoperated.append(
                source_name if source_version is None else f"{source_name}@{source_version}"
            )
        else:
            mapped.update(mapping[0])
    return {
        "status": "ready" if not unoperated else "blocked",
        "curated_source_ids": sorted({source_name for source_name, _ in curated}),
        "mapped_operation_ids": sorted(mapped),
        "unoperated_source_ids": unoperated,
        "reason": (
            "Every curated source/version has a declared operations mapping."
            if not unoperated else "Dashboard release is blocked: curated source_name/source_version values lack matching datasets/operations.json mappings."
        ),
    }


def inspect_built_database(
    path: str | Path | None, scenarios: tuple[str, ...], selected: StateScope
) -> dict[str, Any]:
    if path is None or not Path(path).is_file():
        return {"status": "not_requested"}
    database = Path(path)
    contract = inspect_database(database)
    if contract["compatibility"] != "compatible":
        return {"status": "unavailable", "contract": contract}
    try:
        checks = [check.__dict__ for check in run_checks(str(database))]
    except (duckdb.Error, RuntimeError) as error:
        return {"status": "unavailable", "contract": contract, "reason": str(error)}
    return {
        "status": "ready" if all(check["passed"] for check in checks) else "blocked",
        "contract": contract,
        "p0_quality_checks": checks,
        "scenario_weather": _scenario_weather_readiness(database, scenarios, selected),
        "operations_alignment": _operation_id_alignment(database),
    }


def _present_file(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"status": "not_supplied"}
    artifact = Path(path)
    if not artifact.is_file():
        return {"status": "missing", "path": str(artifact)}
    return {
        "status": "present_unverified",
        "path": str(artifact),
        "bytes": artifact.stat().st_size,
        "sha256": sha256_file(artifact),
        "schema_fingerprint": _schema_fingerprint(artifact),
    }


def inspect_state_context(
    selected: StateScope,
    *,
    tiger: str | Path | None = None,
    nri: str | Path | None = None,
    eaglei: tuple[tuple[int, str], ...] = (),
    eaglei_source_tz: str | None = None,
    texas_p0_ready: bool = False,
) -> dict[str, Any]:
    """Describe only supplied state-scoped public evidence, never implied topology."""
    shared = {"tiger": _present_file(tiger), "nri": _present_file(nri)}
    outage_artifacts = [{"year": year, **_present_file(path)} for year, path in eaglei]
    base_ready = all(item["status"].startswith("present") for item in shared.values())
    outage_ready = not outage_artifacts or (
        eaglei_source_tz in {"UTC", "America/Chicago"}
        and all(item["status"].startswith("present") for item in outage_artifacts)
    )
    contexts = []
    for state in selected.states:
        if state.usps == "TX" and texas_p0_ready:
            topology = {
                "status": "available_synthetic_research_only",
                "reason": "ACTIVSg2000 is synthetic Texas research topology, not a real-grid or Minnesota-demo claim.",
            }
        else:
            topology = {
                "status": "decision_required",
                "reason": "No accepted state-specific topology decision with bus/branch identity, electrical fields, terms, and solver mapping was supplied.",
                "fallback": "Use an explicit aggregate metric or report unavailable; do not reuse Texas topology.",
            }
        contexts.append({
            "state": {"fips": state.fips, "usps": state.usps, "name": state.name},
            "public_context_status": "ready_to_stage" if base_ready and outage_ready else "incomplete",
            "topology": topology,
        })
    return {
        "selected_states": contexts,
        "shared_artifacts": shared,
        "eaglei_artifacts": outage_artifacts,
        "eaglei_source_timezone": eaglei_source_tz,
        "safe_staged_rebuild": {
            "command": "uv run python -m pipelines.build_state_context --state <USPS-or-name-or-FIPS> --db-root <fresh-output>/duck --parquet-dir <fresh-output>/parquet --tiger <path> --nri <path> [--eaglei YEAR=PATH --eaglei-source-tz UTC]",
            "rule": "Supply local artifacts explicitly. State-public-context staging does not acquire sources or imply topology.",
        },
    }


def build_receipt(
    raw_dir: str | Path,
    *,
    database: str | Path | None = None,
    states: StateScope | None = None,
    context_tiger: str | Path | None = None,
    context_nri: str | Path | None = None,
    context_eaglei: tuple[tuple[int, str], ...] = (),
    context_eaglei_source_tz: str | None = None,
    strict_provenance: bool = False,
    require_scenario_weather: bool = False,
    scenarios: tuple[str, ...] = DEFAULT_TEXAS_SCENARIOS,
) -> dict[str, Any]:
    """Assemble the full preflight receipt; this function never writes data."""
    raw = inspect_raw_inputs(raw_dir)
    selected = states or scope(("MN",))
    database_result = inspect_built_database(database, scenarios, selected)
    raw_ready = raw["all_present"] and raw["no_checksum_mismatch"]
    strict_ready = raw_ready and raw["all_locked_with_provenance"]
    scenario_ready = database_result.get("scenario_weather", {}).get("status") == "ready"
    operations_ready = database_result.get("operations_alignment", {}).get("status") == "ready"
    return {
        "receipt_version": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        "write_performed": False,
        "scope": {
            "current_hackathon": "Minnesota only; model mode and source decision remain required.",
            "status": "blocked",
            "reason": "No accepted Minnesota source decision/manifest is supplied by this Texas P0 receipt.",
            "next_step": "Complete MN01: record Minnesota source evidence and select topology only if solver-complete; otherwise select aggregate mode.",
        },
        "state_configurable_public_context": inspect_state_context(
            selected,
            tiger=context_tiger,
            nri=context_nri,
            eaglei=context_eaglei,
            eaglei_source_tz=context_eaglei_source_tz,
            texas_p0_ready=raw_ready,
        ),
        "texas_p0": {
            "status": "research_only",
            "reason": "ACTIVSg2000/Texas P0 must not be presented as the current Minnesota hackathon demo.",
            "raw_inputs": raw,
            "safe_staged_rebuild": {
                "command": "uv run python -m pipelines.build --raw-dir <raw-dir> --db <fresh-output>/grid.duckdb --eaglei-source-tz UTC",
                "rule": "Use a fresh output path. The builder stages and quality-checks before it promotes; never point it at a legacy database.",
            },
        },
        "database": inspect_database(database),
        "built_database": database_result,
        "readiness": {
            "texas_p0_safe_to_stage": raw_ready,
            "strict_provenance_ready": strict_ready,
            "texas_full_flux_ready": (
                database_result.get("status") == "ready" and scenario_ready and operations_ready
            ),
            "dashboard_release_ready": operations_ready,
            "current_hackathon_ready": False,
        },
        "requirements": {
            "strict_provenance_requested": strict_provenance,
            "scenario_weather_required": require_scenario_weather,
        },
    }


def _exit_code(receipt: dict[str, Any]) -> int:
    readiness = receipt["readiness"]
    if not readiness["texas_p0_safe_to_stage"]:
        return 1
    if receipt["requirements"]["strict_provenance_requested"] and not readiness["strict_provenance_ready"]:
        return 1
    if receipt["requirements"]["scenario_weather_required"] and not readiness["texas_full_flux_ready"]:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only P0 raw-data and DuckDB intake receipt")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--database", help="Existing legacy or staged DuckDB to inspect read-only")
    parser.add_argument("--state", action="append", required=True, help="USPS, full state name, or one/two-digit FIPS; repeatable")
    parser.add_argument("--context-tiger", help="Explicit local county-boundary artifact for selected state context")
    parser.add_argument("--context-nri", help="Explicit local NRI artifact for selected state context")
    parser.add_argument("--context-eaglei", action="append", default=[], metavar="YEAR=PATH", help="Explicit local EAGLE-I artifact for selected context (repeatable)")
    parser.add_argument("--context-eaglei-source-tz", choices=("UTC", "America/Chicago"))
    parser.add_argument("--report", type=Path, help="Optional JSON receipt path")
    parser.add_argument("--strict-provenance", action="store_true", help="Fail unless every P0 artifact has a matching tracked checksum receipt")
    parser.add_argument("--require-scenario-weather", action="store_true", help="Fail unless requested Texas scenarios and hourly weather are present in --database")
    parser.add_argument("--scenario", action="append", default=[], help="Scenario required with --require-scenario-weather (repeatable)")
    args = parser.parse_args(argv)
    try:
        selected = scope(args.state)
    except StateScopeError as error:
        parser.error(str(error))
    context_eaglei: list[tuple[int, str]] = []
    for item in args.context_eaglei:
        year, separator, path = item.partition("=")
        if not separator or not year.isdigit() or not path:
            parser.error("--context-eaglei requires YEAR=PATH")
        context_eaglei.append((int(year), path))
    if context_eaglei and not args.context_eaglei_source_tz:
        parser.error("--context-eaglei-source-tz is required with --context-eaglei")
    scenarios = tuple(args.scenario) if args.scenario else DEFAULT_TEXAS_SCENARIOS
    receipt = build_receipt(
        args.raw_dir,
        database=args.database,
        states=selected,
        context_tiger=args.context_tiger,
        context_nri=args.context_nri,
        context_eaglei=tuple(context_eaglei),
        context_eaglei_source_tz=args.context_eaglei_source_tz,
        strict_provenance=args.strict_provenance,
        require_scenario_weather=args.require_scenario_weather,
        scenarios=scenarios,
    )
    rendered = json.dumps(receipt, indent=2, sort_keys=True)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return _exit_code(receipt)


if __name__ == "__main__":
    raise SystemExit(main())
