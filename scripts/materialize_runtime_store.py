"""Build the local Flux runtime store from explicitly supplied verified artifacts.

This is an operator materializer, not a downloader.  It refuses a stale or
misidentified input before copying it, and it never infers topology from the
physical-inventory releases.  The output database is deliberately ignored by
Git; its adjacent JSON receipt is the reproducible handoff.
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


class MaterializationError(RuntimeError):
    """An explicitly supplied input cannot support a truthful runtime store."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
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
    con = duckdb.connect(str(path), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        return {
            table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "cascade_runs",
                "outage_predictions",
                "site_scores",
                "line_upgrade_scores",
            )
            if table in tables
            and con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        }
    finally:
        con.close()


def _validate_output(
    con: duckdb.DuckDBPyConnection, expected_assets: int
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
    if (
        counts["buses"] != 2000
        or counts["lines"] != 3206
        or counts["transformer_branches"] != 847
    ):
        raise MaterializationError(f"unexpected ACTIVS topology counts: {counts}")
    if counts["weather_hourly"] != 85344 or counts["weather_source_runs"] != 336:
        raise MaterializationError(f"unexpected persisted HRRR counts: {counts}")
    if (
        counts["scenarios"] != 2
        or counts["physical_releases"] != 2
        or counts["physical_assets"] != expected_assets
    ):
        raise MaterializationError(f"runtime store is incomplete: {counts}")
    return counts


def materialize(
    *,
    hrrr_db: Path,
    hrrr_receipt: Path,
    aux: Path,
    case: Path,
    activsg_receipt: Path,
    inventory_root: Path,
    version: str,
    output: Path,
    receipt_output: Path,
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
    derived = _derived_rows(output)
    if output.exists() and not replace:
        raise MaterializationError(
            f"output exists; use --replace only after serializing downstream writers: {output}"
        )
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
                con, sum(len(artifact["assets"]) for artifact in artifacts.values())
            )
        finally:
            con.close()
        receipt = {
            "receipt_kind": "flux_runtime_store",
            "receipt_version": 1,
            "output": str(output),
            "output_sha256": sha256_file(stage_db),
            "inputs": {
                "hrrr_db": {"path": str(hrrr_db), "sha256": hrrr_hash},
                "activsg_aux": {"path": str(aux), "sha256": aux_hash},
                "activsg_case": {"path": str(case), "sha256": case_hash},
                "physical_releases": {
                    state: {
                        "path": str(path),
                        "compressed_sha256": sha256_file(path),
                        "content_sha256": artifacts[state]["content_sha256"],
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
            "limitations": [
                "ACTIVSg2000 is synthetic Texas topology; no physical-inventory asset is joined to it.",
                "Minnesota physical inventory is source-backed map inventory only; no Minnesota topology or cascade claim is created.",
                "Weather is persisted only for its observed Uri and Beryl windows; no prediction or cascade result is created.",
            ],
        }
        stage_receipt.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if output.exists() and not replace:
            raise MaterializationError(f"output appeared during staging: {output}")
        os.replace(stage_db, output)
        receipt_output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage_receipt, receipt_output)
        return receipt
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hrrr-db", type=Path, required=True)
    parser.add_argument("--hrrr-receipt", type=Path, required=True)
    parser.add_argument("--aux", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--activsg-receipt", type=Path, required=True)
    parser.add_argument("--inventory-root", type=Path, required=True)
    parser.add_argument("--version", default="1.1.0")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--discard-derived",
        action="store_true",
        help="allow --replace to discard persisted cascade/prediction/siting/line-score products",
    )
    args = parser.parse_args()
    try:
        options = vars(args)
        options["receipt_output"] = options.pop("receipt")
        print(json.dumps(materialize(**options), indent=2, sort_keys=True))
    except MaterializationError as exc:
        parser.exit(2, f"runtime materialization refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
