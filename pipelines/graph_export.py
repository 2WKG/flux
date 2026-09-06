"""Export the synthetic Texas topology from DuckDB as a deterministic graph dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any

import duckdb

DATASET_SCHEMA_VERSION = "1.0.0"
TOPOLOGY_LABEL = "synthetic (ACTIVSg2000)"
NODE_FEATURES = (
    "base_kv",
    "lon",
    "lat",
    "pd_mw",
    "qd_mvar",
    "gs_mw",
    "bs_mvar",
    "vm_pu",
    "va_deg",
    "vmax_pu",
    "vmin_pu",
)
EDGE_FEATURES = (
    "base_kv",
    "r_pu",
    "x_pu",
    "b_pu",
    "tap_ratio",
    "shift_deg",
    "rate_a_mw",
    "length_km",
    "status",
)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: object) -> str:
    payload = _canonical_bytes(value)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _validate_output_target(source: Path, target: Path) -> None:
    if target == source or source.is_relative_to(target):
        raise ValueError("output directory must not contain the source database")
    if not target.exists():
        return
    if not target.is_dir():
        raise ValueError(f"output path is not a directory: {target}")

    expected_files = {
        "edges.json",
        "manifest.json",
        "nodes.json",
        "normalization.json",
    }
    if {entry.name for entry in target.iterdir()} != expected_files:
        raise ValueError(f"refusing to replace a non-export directory: {target}")
    try:
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"refusing to replace an invalid export directory: {target}"
        ) from error
    if (
        manifest.get("schema_version") != DATASET_SCHEMA_VERSION
        or manifest.get("topology_label") != TOPOLOGY_LABEL
    ):
        raise ValueError(f"refusing to replace a non-export directory: {target}")


def _required_tables(con: duckdb.DuckDBPyConnection) -> None:
    expected = {
        "buses",
        "lines",
        "synthetic_bus_electrical",
        "synthetic_branch_electrical",
    }
    found = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    missing = sorted(expected - found)
    if missing:
        raise RuntimeError(f"graph export requires tables: {', '.join(missing)}")


def _number(value: object, *, field: str, record_id: int) -> float | None:
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} for {record_id} must be finite or NULL")
    return result


def _normalization(
    rows: list[dict[str, Any]], feature_names: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for feature in feature_names:
        values = [
            row["features"][feature]
            for row in rows
            if row["features"][feature] is not None
        ]
        if not values:
            stats[feature] = {
                "count": 0,
                "missing_count": len(rows),
                "mean": None,
                "std": None,
                "zero_variance": None,
            }
            continue
        mean = fmean(values)
        std = pstdev(values, mu=mean)
        stats[feature] = {
            "count": len(values),
            "missing_count": len(rows) - len(values),
            "mean": mean,
            "std": std,
            "zero_variance": std == 0,
        }
    return stats


def _apply_normalization(
    rows: list[dict[str, Any]], stats: dict[str, dict[str, Any]]
) -> None:
    for row in rows:
        normalized: dict[str, float | None] = {}
        for feature, value in row["features"].items():
            stat = stats[feature]
            if value is None or stat["std"] is None:
                normalized[feature] = None
            elif stat["zero_variance"]:
                normalized[feature] = 0.0
            else:
                normalized[feature] = (value - stat["mean"]) / stat["std"]
        row["normalized_features"] = normalized


def _nodes(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT b.bus_id, b.base_kv, b.lon, b.lat, e.pd_mw, e.qd_mvar, e.gs_mw,
               e.bs_mvar, e.vm_pu, e.va_deg, e.vmax_pu, e.vmin_pu
        FROM buses AS b
        LEFT JOIN synthetic_bus_electrical AS e USING (bus_id)
        ORDER BY b.bus_id
        """
    ).fetchall()
    return [
        {
            "node_id": int(row[0]),
            "features": {
                feature: _number(value, field=feature, record_id=int(row[0]))
                for feature, value in zip(NODE_FEATURES, row[1:], strict=True)
            },
        }
        for row in rows
    ]


def _edges(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT l.line_id, l.from_bus, l.to_bus, l.is_transformer, l.base_kv, l.r_pu,
               l.x_pu, e.b_pu, e.tap_ratio, e.shift_deg, l.rate_a_mw, l.length_km, e.status
        FROM lines AS l
        LEFT JOIN synthetic_branch_electrical AS e USING (line_id)
        ORDER BY l.line_id
        """
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        line_id, from_bus, to_bus, is_transformer, *values = row
        source_edge_type = "transformer" if is_transformer else "line"
        result.append(
            {
                "edge_id": int(line_id),
                "source": int(from_bus),
                "target": int(to_bus),
                # Pandapower imports these voltage-transition branches as net.impedance.
                "source_edge_type": source_edge_type,
                "solver_edge_type": "impedance_branch" if is_transformer else "line",
                "features": {
                    feature: _number(value, field=feature, record_id=int(line_id))
                    for feature, value in zip(EDGE_FEATURES, values, strict=True)
                },
            }
        )
    return result


def export_texas_graph_dataset(
    db_path: str | Path, out_dir: str | Path
) -> dict[str, Any]:
    """Write a content-addressed graph dataset without changing the source database."""
    source = Path(db_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"DuckDB database not found: {source}")
    target = Path(out_dir).resolve()
    _validate_output_target(source, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        with duckdb.connect(str(source), read_only=True) as con:
            _required_tables(con)
            nodes = _nodes(con)
            edges = _edges(con)
        if not nodes or not edges:
            raise RuntimeError("graph export requires at least one bus and one branch")
        node_stats = _normalization(nodes, NODE_FEATURES)
        edge_stats = _normalization(edges, EDGE_FEATURES)
        _apply_normalization(nodes, node_stats)
        _apply_normalization(edges, edge_stats)
        normalization = {"node_features": node_stats, "edge_features": edge_stats}
        file_hashes = {
            "nodes.json": _write_json(temporary / "nodes.json", nodes),
            "edges.json": _write_json(temporary / "edges.json", edges),
            "normalization.json": _write_json(
                temporary / "normalization.json", normalization
            ),
        }
        source_types = Counter(edge["source_edge_type"] for edge in edges)
        solver_types = Counter(edge["solver_edge_type"] for edge in edges)
        dataset_identity = {
            "schema_version": DATASET_SCHEMA_VERSION,
            "topology_label": TOPOLOGY_LABEL,
            "files": file_hashes,
        }
        manifest = {
            "dataset_sha256": hashlib.sha256(
                _canonical_bytes(dataset_identity)
            ).hexdigest(),
            "edge_counts": {
                "source_edge_type": dict(sorted(source_types.items())),
                "solver_edge_type": dict(sorted(solver_types.items())),
            },
            "files": file_hashes,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "schema_version": DATASET_SCHEMA_VERSION,
            "topology_label": TOPOLOGY_LABEL,
        }
        _write_json(temporary / "manifest.json", manifest)
        if target.exists():
            shutil.rmtree(target)
        temporary.replace(target)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", default="data/duck/grid.duckdb", help="source DuckDB path"
    )
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args()
    print(json.dumps(export_texas_graph_dataset(args.db, args.out), sort_keys=True))


if __name__ == "__main__":
    main()
