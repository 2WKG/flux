"""Dependency-ordered P0 builder. Missing raw artifacts are reported, never hidden."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import duckdb

from pipelines.activsg import load_activsg
from pipelines.checks import run_checks
from pipelines.common import sha256_file
from pipelines.counties import load_counties
from pipelines.critical_loads import load_dod
from pipelines.db import connect, export_parquet, validate_schema
from pipelines.eaglei import load_county_customers, load_coverage_history, load_eaglei
from pipelines.eia860 import load_eia860_plants, seed_site_candidates
from pipelines.eia930 import load_eia930
from pipelines.joins import join_bus_county, join_critical_loads_to_bus
from pipelines.manifest import build_manifest, store_manifest, write_manifest
from pipelines.nri import load_nri
from pipelines.state_scope import scope
from pipelines.storm_events import load_storm_events

P0_RAW_INPUTS_CATALOG = (
    Path(__file__).resolve().parents[1] / "datasets" / "catalog.json"
)


class PublicationRecoveryError(RuntimeError):
    """Publication rollback failed; the recovery directory must be retained."""


class IncompleteP0BuildError(RuntimeError):
    """Raised before a partial P0 build can mutate or export the curated release."""


def _required(root: Path, *parts: str) -> Path | None:
    path = root.joinpath(*parts)
    return path if path.exists() else None


def _dod_filename(states=None) -> str:
    """Name the scoped DoD extract without pinning the Texas fixture."""
    return f"{scope(states).slug}.geojson"


def _p0_raw_inputs() -> tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]:
    """Read the P0 raw-file contract from the shared dataset catalog."""
    try:
        inputs = json.loads(P0_RAW_INPUTS_CATALOG.read_text())["p0_raw_inputs"]
        return tuple(
            (item["label"], tuple(tuple(path) for path in item["paths"]))
            for item in inputs
        )
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"invalid P0 raw-input catalog: {P0_RAW_INPUTS_CATALOG}"
        ) from error


def _missing_p0_inputs(raw: Path, eaglei_source_tz: str | None) -> list[str]:
    """Return P0 inputs handled by this builder that are absent or not promotable."""
    missing = [
        label
        for label, alternatives in _p0_raw_inputs()
        if not any(raw.joinpath(*parts).exists() for parts in alternatives)
    ]
    if not eaglei_source_tz:
        missing.append("--eaglei-source-tz (required to promote EAGLE-I)")
    return missing


def _verified_activsg_retrieval(aux: Path, case: Path) -> datetime | None:
    """Use the checked-in receipt only when it matches the exact raw inputs."""
    receipt = Path("data/sources/activsg2000.json")
    if not receipt.exists():
        return None
    metadata = json.loads(receipt.read_text())
    files = metadata.get("files", {})
    if files.get(aux.name, {}).get("sha256") != sha256_file(aux) or files.get(
        case.name, {}
    ).get("sha256") != sha256_file(case):
        return None
    value = metadata.get("retrieved_at")
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else None


def _build_mutating(
    raw_dir: str,
    db_path: str,
    eaglei_source_tz: str | None,
    parquet_dir: str,
    states=None,
) -> dict[str, int]:
    raw = Path(raw_dir)
    selected_scope = scope(states)
    if missing := _missing_p0_inputs(raw, eaglei_source_tz):
        formatted = "\n  - ".join(missing)
        raise IncompleteP0BuildError(
            "P0 build was not promoted; missing required inputs:\n  - " + formatted
        )

    con, counts = connect(db_path), {}
    try:
        aux = _required(raw, "activsg2000_current", "ACTIVSg2000.aux")
        case = _required(raw, "activsg2000_current", "case_ACTIVSg2000.m")
        assert aux and case
        nri = (
            _required(raw, "nri", "v1.20", "NRI_Counties_TX.json")
            or _required(raw, "nri", "v1.20", "NRI_Table_Counties.zip")
            or _required(raw, "nri", "NRI_Table_Counties.zip")
        )
        tiger = _required(raw, "tiger", "2024", "tl_2024_us_county.zip") or _required(
            raw, "tiger", "tl_2024_us_county.zip"
        )
        assert tiger and nri
        counts["counties"] = load_counties(con, str(tiger), str(nri))
        counts.update(
            load_activsg(
                con,
                str(aux),
                str(case),
                source_retrieved_at=_verified_activsg_retrieval(aux, case),
            )
        )
        counts["bus_county"] = join_bus_county(con)
        counts["nri"] = load_nri(con, str(nri))
        plants = _required(raw, "pudl", "v2026.2.0", "out_eia__yearly_plants.parquet")
        generators = _required(
            raw, "pudl", "v2026.2.0", "out_eia__yearly_generators.parquet"
        )
        assert plants and generators
        counts["eia_plants"] = load_eia860_plants(
            con, str(plants), str(generators), states=selected_scope
        )
        counts["site_candidates"] = seed_site_candidates(con, selected_scope)
        eia_files = [
            _required(raw, "eia930", "2021_h1", "EIA930_BALANCE_2021_Jan_Jun.csv"),
            _required(raw, "eia930", "2024_h2", "EIA930_BALANCE_2024_Jul_Dec.csv"),
        ]
        assert all(eia_files)
        counts["ba_load_hourly"] = load_eia930(con, [str(path) for path in eia_files])
        crosswalk = _required(raw, "nws_zone_county", "bp16ap26", "bp16ap26.dbx")
        assert crosswalk
        for year, file_name in (
            (2021, "StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz"),
            (2024, "StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz"),
        ):
            details = _required(raw, "storm_events", str(year), file_name)
            assert details
            counts[f"storm_events_{year}"] = load_storm_events(
                con, str(details), str(crosswalk), year, selected_scope
            )
        mcc = _required(raw, "eaglei", "support", "MCC.csv")
        coverage = _required(raw, "eaglei", "support", "coverage_history.csv")
        assert mcc and coverage
        counts["county_customers"] = load_county_customers(con, str(mcc))
        counts["eaglei_coverage"] = load_coverage_history(con, str(coverage))
        for year in (2021, 2024):
            outage = _required(raw, "eaglei", str(year), f"eaglei_outages_{year}.csv")
            assert outage and eaglei_source_tz
            counts[f"eaglei_{year}"] = load_eaglei(
                con, str(outage), year, eaglei_source_tz
            )
        dod = _required(
            raw, "ntad_military_bases", "fy2024", _dod_filename(selected_scope)
        )
        assert dod
        counts["critical_loads_dod"] = load_dod(con, str(dod))
        counts["critical_load_bus"] = join_critical_loads_to_bus(con)
        validate_schema(con)
        export_parquet(con, parquet_dir)
        manifest = build_manifest(con, state_scope=str(selected_scope.slug))
        store_manifest(con, manifest)
        write_manifest(manifest, Path(parquet_dir) / "manifest.json")
    finally:
        con.close()
    return counts


def _copy_database(source: Path, stage: Path) -> None:
    if not source.exists():
        connect(stage).close()
        return
    con = duckdb.connect()
    try:
        quote = lambda path: "'" + str(path).replace("'", "''") + "'"
        con.execute(f"ATTACH {quote(source)} AS live (READ_ONLY)")
        con.execute(f"ATTACH {quote(stage)} AS staged")
        # Native schema copying retains namespaces, views, and constraints.
        # Native full copying inserts tables in catalog order, which can put
        # populated children before their referenced parents.
        con.execute("COPY FROM DATABASE live TO staged (SCHEMA)")
        tables = set(
            con.execute(
                "SELECT schema_name, table_name FROM duckdb_tables() WHERE database_name = 'live'"
            ).fetchall()
        )
        dependencies = {table: set() for table in tables}
        for schema, child, parent in con.execute(
            "SELECT schema_name, table_name, referenced_table FROM duckdb_constraints() "
            "WHERE database_name = 'live' AND constraint_type = 'FOREIGN KEY'"
        ).fetchall():
            dependencies[(schema, child)].add((schema, parent))
        identifier = lambda value: '"' + value.replace('"', '""') + '"'
        while tables:
            ready = sorted(
                table for table in tables if not (dependencies[table] & tables)
            )
            if not ready:
                raise RuntimeError(
                    f"cannot stage cyclic foreign-key dependencies: {sorted(tables)}"
                )
            for schema, table in ready:
                qualified = f"{identifier(schema)}.{identifier(table)}"
                con.execute(
                    f"INSERT INTO staged.{qualified} BY NAME SELECT * FROM live.{qualified}"
                )
                tables.remove((schema, table))
    finally:
        con.close()


def _promote(
    stage_db: Path, live_db: Path, stage_parquet: Path, live_parquet: Path, root: Path
) -> None:
    old_db, old_parquet = root / "previous.duckdb", root / "previous-parquet"
    moved_db = moved_parquet = False
    try:
        if live_db.exists():
            os.replace(live_db, old_db)
        os.replace(stage_db, live_db)
        moved_db = True
        if live_parquet.exists():
            os.replace(live_parquet, old_parquet)
        os.replace(stage_parquet, live_parquet)
        moved_parquet = True
    except Exception as publish_error:
        recovery_errors = []
        # Try both restorations even if one fails. Never discard the only old
        # copy when filesystem errors prevent completing rollback.
        for old, live, moved in (
            (old_parquet, live_parquet, moved_parquet),
            (old_db, live_db, moved_db),
        ):
            try:
                if moved and live.exists():
                    if live.is_dir():
                        shutil.rmtree(live)
                    else:
                        live.unlink()
                if old.exists():
                    os.replace(old, live)
            except OSError as error:
                recovery_errors.append(f"{live}: {error}")
        if recovery_errors:
            raise PublicationRecoveryError(
                f"publication failed ({publish_error}); rollback incomplete; "
                f"recovery files retained at {root}: " + "; ".join(recovery_errors)
            ) from publish_error
        raise
    else:
        if old_db.exists():
            old_db.unlink()
        if old_parquet.exists():
            shutil.rmtree(old_parquet)


def build(
    raw_dir: str = "data/raw",
    db_path: str = "data/duck/grid.duckdb",
    eaglei_source_tz: str | None = None,
    states=None,
) -> dict[str, int]:
    raw, live_db = Path(raw_dir), Path(db_path)
    if missing := _missing_p0_inputs(raw, eaglei_source_tz):
        formatted = "\n  - ".join(missing)
        raise IncompleteP0BuildError(
            "P0 build was not promoted; missing required inputs:\n  - " + formatted
        )
    live_db.parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f".{live_db.stem}-stage-", dir=live_db.parent))
    stage_db, live_parquet, stage_parquet = (
        root / live_db.name,
        Path("data/parquet"),
        root / "parquet",
    )
    retain_recovery = False
    try:
        _copy_database(live_db, stage_db)
        if live_parquet.exists():
            shutil.copytree(live_parquet, stage_parquet)
        else:
            stage_parquet.mkdir()
        args = (str(raw), str(stage_db), eaglei_source_tz, str(stage_parquet))
        counts = (
            _build_mutating(*args) if states is None else _build_mutating(*args, states)
        )
        checks = run_checks(str(stage_db), states)
        if not all(check.passed for check in checks):
            raise RuntimeError(
                "staged P0 quality checks failed: "
                + "; ".join(check.name for check in checks if not check.passed)
            )
        _promote(stage_db, live_db, stage_parquet, live_parquet, root)
        return counts
    except PublicationRecoveryError:
        retain_recovery = True
        raise
    finally:
        if not retain_recovery:
            shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--db", default="data/duck/grid.duckdb")
    parser.add_argument("--eaglei-source-tz", choices=("UTC", "America/Chicago"))
    parser.add_argument(
        "--states",
        action="append",
        help="USPS names/codes or comma-separated state scope",
    )
    args = parser.parse_args()
    counts = build(args.raw_dir, args.db, args.eaglei_source_tz, args.states)
    for name, rows in sorted(counts.items()):
        print(f"{name}: {rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
