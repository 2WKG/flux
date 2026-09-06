"""Build the local Flux runtime store from explicitly supplied verified artifacts.

This is an operator materializer, not a downloader.  It refuses a stale or
misidentified input before copying it, and it never infers topology from the
physical-inventory releases.  The output database is deliberately ignored by
Git; its adjacent JSON receipt is the reproducible handoff.

Every input receipt defaults to a path that is checked into this repository, so
a second operator only has to supply the two ignored bulk artifacts (the HRRR
DuckDB and the ACTIVSg2000 AUX/case pair).  A missing receipt is refused by
name rather than reported as malformed JSON.

The receipt records a *content* digest of the published tables, not a SHA-256 of
the database file: DuckDB rewrites its file on every read-write open, so a
file hash cannot survive the store's first use.  ``--verify`` re-derives that
content digest from the published store and refuses a drifted one.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

# ``python scripts/materialize_runtime_store.py`` puts ``scripts/`` rather
# than the repository root on sys.path. Keep the documented operator command
# usable without requiring an editable install.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipelines.activsg import load_activsg
from pipelines.physical_inventory import write_artifact

DEFAULT_HRRR_RECEIPT = REPO_ROOT / "data/sources/texas-hrrr-2021-2024-run.json"
DEFAULT_ACTIVSG_RECEIPT = REPO_ROOT / "data/sources/activsg2000.json"
DEFAULT_INVENTORY_ROOT = REPO_ROOT / "data/artifacts/physical_inventory"
DEFAULT_OUTPUT = REPO_ROOT / "data/duck/grid.duckdb"
DEFAULT_RECEIPT_OUTPUT = REPO_ROOT / "data/duck/runtime-store-receipt.json"

# The published ACTIVSg2000 branch counts are not carried by any checked-in
# receipt, so they stay named here.  Everything else in the expectation set is
# read back out of the input receipts.
ACTIVS_LINE_COUNT = 3206
ACTIVS_TRANSFORMER_BRANCH_COUNT = 847

CONTENT_DIGEST_ALGORITHM = "sha256-over-md5-row-digests-v1"

CAPTURE_METHOD = (
    "scripts/materialize_runtime_store.py: every input path was SHA-256 verified "
    "against its checked-in source receipt before any byte was copied; the store "
    "was assembled in a temporary directory beside the output and published with "
    "os.replace; the content digest was re-derived from the staged store."
)


class MaterializationError(RuntimeError):
    """An explicitly supplied input cannot support a truthful runtime store."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MaterializationError(
            f"required receipt does not exist: {path} "
            "(pass an explicit path, or use the checked-in receipt under data/sources/)"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterializationError(f"invalid JSON receipt: {path}") from exc
    if not isinstance(value, dict):
        raise MaterializationError(f"receipt must be an object: {path}")
    return value


def _require_hash(path: Path, expected: object, label: str) -> str:
    if not path.is_file() or not isinstance(expected, str) or len(expected) != 64:
        raise MaterializationError(f"{label} is missing a readable file or SHA-256")
    actual = sha256_file(path)
    if actual != expected:
        raise MaterializationError(
            f"{label} SHA-256 mismatch: expected {expected}, got {actual}"
        )
    return actual


def _receipt_hash(receipt: dict[str, Any], filename: str) -> str:
    try:
        return receipt["files"][filename]["sha256"]
    except (KeyError, TypeError) as exc:
        raise MaterializationError(f"receipt has no SHA-256 for {filename}") from exc


def _scenario_windows(
    con: duckdb.DuckDBPyConnection,
) -> list[tuple[str, datetime, datetime]]:
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    required = {"counties", "weather_hourly", "weather_source_runs"}
    if missing := required - tables:
        raise MaterializationError(
            f"weather input lacks required tables: {sorted(missing)}"
        )
    windows = con.execute(
        """SELECT r.scenario_id, min(w.ts), max(w.ts), count(DISTINCT w.county_fips)
        FROM weather_source_runs AS r JOIN weather_hourly AS w ON w.ts = r.valid_ts
        GROUP BY r.scenario_id ORDER BY r.scenario_id"""
    ).fetchall()
    expected = {"uri_2021", "beryl_2024"}
    present = {row[0] for row in windows}
    if present != expected:
        raise MaterializationError(
            f"weather scenarios must be {sorted(expected)}, got {sorted(present)}"
        )
    if any(row[3] != 254 or row[1] is None or row[2] is None for row in windows):
        raise MaterializationError(
            "weather windows do not cover 254 counties at each retained scenario"
        )
    return [(row[0], row[1], row[2]) for row in windows]


def _load_release(path: Path) -> dict[str, Any]:
    try:
        return json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterializationError(
            f"unreadable published inventory release: {path}"
        ) from exc


def _published_releases(
    inventory_root: Path, version: str
) -> dict[str, dict[str, Any]]:
    """Load only the state releases pinned by the checked-in publication manifest."""
    manifest = _json(inventory_root / f"manifest-{version}.json")
    if manifest.get("release_version") != version:
        raise MaterializationError(
            "published inventory manifest version does not match requested version"
        )
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        raise MaterializationError(
            "published inventory manifest has no artifact entries"
        )
    expected_paths = {
        state: f"data/artifacts/physical_inventory/{state}/physical-inventory-{version}.json.gz"
        for state in ("tx", "mn")
    }
    releases: dict[str, dict[str, Any]] = {}
    for state, published_path in expected_paths.items():
        matches = [
            entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("state") == state
        ]
        if len(matches) != 1:
            raise MaterializationError(
                f"published inventory manifest must contain exactly one {state} release"
            )
        entry = matches[0]
        required = {
            "artifact_id": f"{state}:physical-inventory:{version}",
            "published_path": published_path,
        }
        if any(entry.get(field) != value for field, value in required.items()):
            raise MaterializationError(
                f"published inventory manifest identity mismatch for {state}"
            )
        path = inventory_root / state / f"physical-inventory-{version}.json.gz"
        compressed = entry.get("compressed_sha256")
        if (
            _require_hash(path, compressed, f"published {state} inventory")
            != compressed
        ):
            raise MaterializationError(f"published {state} inventory hash mismatch")
        artifact = _load_release(path)
        if (
            artifact.get("artifact_id") != entry["artifact_id"]
            or artifact.get("artifact_version") != version
            or artifact.get("content_sha256") != entry.get("canonical_content_sha256")
        ):
            raise MaterializationError(
                f"published {state} inventory content does not match its manifest"
            )
        releases[state] = {"path": path, "artifact": artifact, "manifest": entry}
    return releases


def _derived_rows(path: Path) -> dict[str, int]:
    """Report persisted products that a source rebuild would otherwise erase."""
    if not path.exists():
        return {}
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error as exc:
        raise MaterializationError(
            f"existing output is not a readable DuckDB store: {path}"
        ) from exc
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        counted = {
            table: con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            for table in (
                "cascade_runs",
                "outage_predictions",
                "site_scores",
                "line_upgrade_scores",
            )
            if table in tables
        }
        return {table: rows for table, rows in counted.items() if rows}
    finally:
        con.close()


def _record_path(path: Path) -> str:
    """Record a repository-relative path when the input lives in the repo.

    A receipt that names an ephemeral absolute temp directory is not a handoff a
    second operator can act on.
    """
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def content_digest(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Digest the rows the store exports, not the bytes of its file.

    DuckDB rewrites the database file on every read-write open, so a SHA-256 of
    the file is stale the first time the API serves the store.  Hashing each
    table's rows -- order-independently, so storage layout cannot change the
    answer -- gives a digest that survives re-opening and still moves when any
    row moves.
    """
    tables = sorted(row[0] for row in con.execute("SHOW TABLES").fetchall())
    per_table: dict[str, dict[str, Any]] = {}
    for table in tables:
        rows, digest = con.execute(
            f"""SELECT count(*), md5(coalesce(string_agg(d, chr(10) ORDER BY d), ''))
            FROM (SELECT md5(CAST(t AS VARCHAR)) AS d FROM "{table}" AS t)"""
        ).fetchone()
        per_table[table] = {"rows": rows, "md5": digest}
    return {
        "algorithm": CONTENT_DIGEST_ALGORITHM,
        "tables": per_table,
        "sha256": hashlib.sha256(
            json.dumps(per_table, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def store_content_digest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MaterializationError(f"runtime store does not exist: {path}")
    con = duckdb.connect(str(path), read_only=True)
    try:
        return content_digest(con)
    finally:
        con.close()


def verify(*, output: Path, receipt_output: Path) -> dict[str, Any]:
    """Re-derive the published store's content digest and refuse a drifted store."""
    receipt = _json(receipt_output)
    recorded = receipt.get("content_digest")
    if not isinstance(recorded, dict) or "sha256" not in recorded:
        raise MaterializationError(
            f"receipt records no content digest to verify against: {receipt_output}"
        )
    if recorded.get("algorithm") != CONTENT_DIGEST_ALGORITHM:
        raise MaterializationError(
            f"receipt content digest algorithm is {recorded.get('algorithm')!r}, "
            f"this build verifies {CONTENT_DIGEST_ALGORITHM!r}"
        )
    actual = store_content_digest(output)
    if actual["sha256"] != recorded["sha256"]:
        drifted = sorted(
            table
            for table in set(actual["tables"]) | set(recorded.get("tables") or {})
            if actual["tables"].get(table) != (recorded.get("tables") or {}).get(table)
        )
        raise MaterializationError(
            f"runtime store no longer matches its receipt: expected "
            f"{recorded['sha256']}, got {actual['sha256']}; drifted tables {drifted}"
        )
    return {
        "verified": True,
        "output": _record_path(output),
        "receipt": _record_path(receipt_output),
        "content_sha256": actual["sha256"],
    }


def _expected_counts(
    hrrr_metadata: dict[str, Any],
    activsg_metadata: dict[str, Any],
    expected_assets: int,
) -> dict[str, int]:
    """Read the expected store shape out of the input receipts where they carry it."""
    validation = hrrr_metadata.get("validation")
    aux_check = activsg_metadata.get("aux_check")
    if not isinstance(validation, dict) or not isinstance(aux_check, dict):
        raise MaterializationError(
            "input receipts do not declare the validation/aux_check blocks the "
            "expected output counts are read from"
        )
    beryl = validation.get("beryl_2024")
    try:
        expected = {
            "buses": int(aux_check["bus_records"]),
            "lines": ACTIVS_LINE_COUNT,
            "transformer_branches": ACTIVS_TRANSFORMER_BRANCH_COUNT,
            "weather_hourly": int(validation["total_weather_rows"]),
            "weather_source_runs": int(beryl["source_runs_total"]),
            "scenarios": 2,
            "physical_releases": 2,
            "physical_assets": int(expected_assets),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise MaterializationError(
            f"input receipts do not declare an expected output count: {exc}"
        ) from exc
    return expected


def _validate_output(
    con: duckdb.DuckDBPyConnection, expected: dict[str, int]
) -> dict[str, int]:
    counts = dict(
        zip(
            (
                "buses",
                "lines",
                "transformer_branches",
                "weather_hourly",
                "weather_source_runs",
                "scenarios",
                "physical_releases",
                "physical_assets",
            ),
            con.execute("""SELECT
              (SELECT count(*) FROM buses),
              (SELECT count(*) FROM lines),
              (SELECT count(*) FROM lines WHERE is_transformer),
              (SELECT count(*) FROM weather_hourly),
              (SELECT count(*) FROM weather_source_runs),
              (SELECT count(*) FROM scenarios),
              (SELECT count(*) FROM physical_inventory_manifests),
              (SELECT count(*) FROM physical_assets)""").fetchone(),
        )
    )
    if missing := set(expected) - set(counts):
        raise MaterializationError(f"no count was read for {sorted(missing)}")
    mismatched = {
        name: {"expected": expected[name], "actual": counts[name]}
        for name in expected
        if counts[name] != expected[name]
    }
    if mismatched:
        raise MaterializationError(
            f"runtime store does not match the counts its inputs declare: {mismatched}"
        )
    return counts


def materialize(
    *,
    hrrr_db: Path,
    aux: Path,
    case: Path,
    hrrr_receipt: Path = DEFAULT_HRRR_RECEIPT,
    activsg_receipt: Path = DEFAULT_ACTIVSG_RECEIPT,
    inventory_root: Path = DEFAULT_INVENTORY_ROOT,
    version: str = "1.1.0",
    output: Path = DEFAULT_OUTPUT,
    receipt_output: Path = DEFAULT_RECEIPT_OUTPUT,
    replace: bool = False,
    discard_derived: bool = False,
) -> dict[str, Any]:
    """Atomically publish one verified runtime DB and its operator receipt."""
    hrrr_metadata, activsg_metadata = _json(hrrr_receipt), _json(activsg_receipt)
    hrrr_hash = _require_hash(
        hrrr_db, _receipt_hash(hrrr_metadata, "grid.duckdb"), "HRRR DB"
    )
    aux_hash = _require_hash(
        aux, _receipt_hash(activsg_metadata, aux.name), "ACTIVS AUX"
    )
    case_hash = _require_hash(
        case, _receipt_hash(activsg_metadata, case.name), "ACTIVS MATPOWER case"
    )
    retrieved_at = datetime.fromisoformat(str(activsg_metadata["retrieved_at"]))
    if retrieved_at.tzinfo is None:
        raise MaterializationError("ACTIVS receipt retrieved_at must have an offset")
    published = _published_releases(inventory_root, version)
    releases = {state: item["path"] for state, item in published.items()}
    artifacts = {state: item["artifact"] for state, item in published.items()}
    if any(
        artifact.get("geography_id") != state for state, artifact in artifacts.items()
    ):
        raise MaterializationError(
            "published inventory release geography does not match its state path"
        )
    output_existed = output.exists()
    if output_existed and not replace:
        raise MaterializationError(
            f"output exists; use --replace only after serializing downstream writers: {output}"
        )
    derived = _derived_rows(output)
    if derived and not discard_derived:
        raise MaterializationError(
            f"output holds derived products {derived}; preserve it for cold start or pass --discard-derived with --replace"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(tempfile.mkdtemp(prefix=f".{output.stem}-", dir=output.parent))
    stage_db, stage_receipt = stage_dir / output.name, stage_dir / receipt_output.name
    try:
        shutil.copy2(hrrr_db, stage_db)
        con = duckdb.connect(str(stage_db))
        try:
            windows = _scenario_windows(con)
            load_activsg(con, str(aux), str(case), source_retrieved_at=retrieved_at)
            labels = {
                "uri_2021": "Winter Storm Uri weather window",
                "beryl_2024": "Hurricane Beryl weather window",
            }
            for scenario_id, start, end in windows:
                con.execute(
                    "INSERT INTO scenarios VALUES (?, ?, 'historical', ?, ?, 'noaa_hrrr', ?, 'hrrr-sfc-3km', ?, ?)",
                    [
                        scenario_id,
                        labels[scenario_id],
                        start,
                        end,
                        str(hrrr_receipt),
                        hrrr_metadata["retrieved_at"],
                        f"runtime-{scenario_id}",
                    ],
                )
            for artifact in artifacts.values():
                write_artifact(con, artifact)
            counts = _validate_output(
                con,
                _expected_counts(
                    hrrr_metadata,
                    activsg_metadata,
                    sum(len(artifact["assets"]) for artifact in artifacts.values()),
                ),
            )
            digest = content_digest(con)
        finally:
            con.close()
        receipt = {
            "receipt_kind": "flux_runtime_store",
            "receipt_version": 2,
            "output": _record_path(output),
            "capture_method": CAPTURE_METHOD,
            "content_digest": digest,
            "inputs": {
                "hrrr_db": {
                    "path": _record_path(hrrr_db),
                    "sha256": hrrr_hash,
                    "receipt": _record_path(hrrr_receipt),
                },
                "activsg_aux": {
                    "path": _record_path(aux),
                    "sha256": aux_hash,
                    "receipt": _record_path(activsg_receipt),
                },
                "activsg_case": {
                    "path": _record_path(case),
                    "sha256": case_hash,
                    "receipt": _record_path(activsg_receipt),
                },
                "physical_releases": {
                    state: {
                        "path": _record_path(path),
                        "compressed_sha256": sha256_file(path),
                        "content_sha256": artifacts[state]["content_sha256"],
                        "manifest": _record_path(
                            inventory_root / f"manifest-{version}.json"
                        ),
                    }
                    for state, path in releases.items()
                },
            },
            "scenario_windows": [
                {
                    "scenario_id": sid,
                    "ts_start": start.isoformat(),
                    "ts_end": end.isoformat(),
                }
                for sid, start, end in windows
            ],
            "counts": counts,
            "verification": {
                "inputs_verified_against_checked_in_receipts": True,
                "content_digest_rederived_from": "the staged store, before publication",
                "reverify_with": (
                    "uv run python scripts/materialize_runtime_store.py --verify "
                    f"--output {_record_path(output)} --receipt {_record_path(receipt_output)}"
                ),
                "not_verified": (
                    "The published DuckDB file's byte hash is deliberately not recorded: "
                    "DuckDB rewrites the file on every read-write open, so a file hash "
                    "cannot survive the store's first use. Only content_digest is "
                    "re-derivable. Nothing re-checks the ignored bulk inputs against "
                    "their upstream sources on a schedule."
                ),
            },
            "limitations": [
                "ACTIVSg2000 is synthetic Texas topology; no physical-inventory asset is joined to it.",
                "Minnesota physical inventory is source-backed map inventory only; no Minnesota topology or cascade claim is created.",
                "Weather is persisted only for its observed Uri and Beryl windows; no prediction or cascade result is created.",
            ],
        }
        stage_receipt.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if output.exists() != output_existed or _derived_rows(output) != derived:
            raise MaterializationError(
                f"output changed during staging; refusing to clobber a concurrent publish: {output}"
            )
        os.replace(stage_db, output)
        receipt_output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage_receipt, receipt_output)
        return receipt
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hrrr-db", type=Path)
    parser.add_argument("--hrrr-receipt", type=Path, default=DEFAULT_HRRR_RECEIPT)
    parser.add_argument("--aux", type=Path)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--activsg-receipt", type=Path, default=DEFAULT_ACTIVSG_RECEIPT)
    parser.add_argument("--inventory-root", type=Path, default=DEFAULT_INVENTORY_ROOT)
    parser.add_argument("--version", default="1.1.0")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT_OUTPUT)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--discard-derived",
        action="store_true",
        help="allow --replace to discard persisted cascade/prediction/siting/line-score products",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="re-derive the published store's content digest and refuse a drifted store; "
        "reads --output and --receipt only",
    )
    args = parser.parse_args()
    options = vars(args)
    do_verify = options.pop("verify")
    options["receipt_output"] = options.pop("receipt")
    try:
        if do_verify:
            result = verify(
                output=options["output"], receipt_output=options["receipt_output"]
            )
        else:
            missing = [
                flag
                for flag, value in (
                    ("--hrrr-db", options["hrrr_db"]),
                    ("--aux", options["aux"]),
                    ("--case", options["case"]),
                )
                if value is None
            ]
            if missing:
                parser.error(
                    f"{', '.join(missing)} are required when not running --verify "
                    "(they name the ignored bulk artifacts; every receipt defaults to "
                    "a checked-in path)"
                )
            result = materialize(**options)
        print(json.dumps(result, indent=2, sort_keys=True))
    except MaterializationError as exc:
        parser.exit(2, f"runtime materialization refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
