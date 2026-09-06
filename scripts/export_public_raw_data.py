"""Materialize the approved Flux source-data snapshot as safe static files.

This deliberately has no arbitrary table, path, SQL, or network input.  It
opens one supplied DuckDB database read-only and exports only the named source
tables below; it copies only named EIA receipts/downloads and checked-in
Minnesota evidence.  Model outputs stay out of the download set and are listed
as such in the index.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import duckdb

ROOT: Final = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class TableExport:
    table: str
    filename: str
    order_by: str
    classification: str
    detail: str


TABLE_EXPORTS: Final = (
    TableExport(
        "buses",
        "texas_buses.csv",
        "bus_id",
        "source input",
        "ACTIVSg2000 synthetic topology buses; coordinates are labelled tamu_aux.",
    ),
    TableExport(
        "lines",
        "texas_lines.csv",
        "line_id",
        "source input",
        "ACTIVSg2000 synthetic topology branches; includes endpoint bus IDs and source electrical fields.",
    ),
    TableExport(
        "gens",
        "texas_generators.csv",
        "gen_id",
        "source input",
        "ACTIVSg2000 synthetic topology generator records.",
    ),
    TableExport(
        "loads",
        "texas_loads.csv",
        "load_id",
        "source input",
        "ACTIVSg2000 synthetic topology load records.",
    ),
    TableExport(
        "counties",
        "texas_counties.csv",
        "county_fips",
        "source context",
        "Texas county source/context rows.",
    ),
    TableExport(
        "county_geo_meta",
        "texas_county_geo_meta.csv",
        "county_fips",
        "source context",
        "County geographic metadata.",
    ),
    TableExport(
        "ba_load_hourly",
        "eia930_ba_load_hourly.csv",
        "ba_code, ts",
        "recovered source table",
        "Recovered EIA-930 balancing-authority hourly demand; noncontiguous source windows remain visible in the rows.",
    ),
    TableExport(
        "ba_operations_hourly",
        "eia930_ba_operations_hourly.csv",
        "ba_code, ts",
        "recovered source table",
        "Recovered EIA-930 balancing-authority operations rows.",
    ),
    TableExport(
        "weather_hourly",
        "hrrr_weather_hourly.csv",
        "county_fips, ts",
        "recovered source table",
        "County-hour weather values with source receipts; this is not a solved grid output.",
    ),
    TableExport(
        "weather_source_runs",
        "hrrr_weather_source_runs.csv",
        "scenario_id, valid_ts",
        "source receipt table",
        "HRRR source URLs, hashes, and receipt references for the recovered weather rows.",
    ),
    TableExport(
        "physical_assets",
        "physical_assets.csv",
        "asset_id",
        "source inventory",
        "Source-backed physical inventory records; inventory does not establish electrical connectivity.",
    ),
    TableExport(
        "physical_coverage",
        "physical_coverage.csv",
        "artifact_id, asset_class, scope_id",
        "source inventory metadata",
        "Physical inventory coverage records.",
    ),
    TableExport(
        "physical_inventory_sources",
        "physical_inventory_sources.csv",
        "source_id",
        "source inventory metadata",
        "Physical inventory provenance records.",
    ),
    TableExport(
        "physical_inventory_manifests",
        "physical_inventory_manifests.csv",
        "artifact_id",
        "source inventory metadata",
        "Physical inventory manifest records.",
    ),
)

DERIVED_OR_MODEL_TABLES: Final = (
    "cascade_runs",
    "synthetic_branch_electrical",
    "synthetic_bus_electrical",
    "synthetic_generator_electrical",
    "synthetic_substations",
    "mn_artifact_manifests",
    "mn_model_results",
    "mn_score_results",
)

EIA_FILES: Final = (
    "README.md",
    "RECEIPT.json",
    "raw/EIA930_BALANCE_2021_Jan_Jun.csv",
    "raw/EIA930_BALANCE_2024_Jul_Dec.csv",
    "raw/EIA930_Reference_Tables.xlsx",
)

MN_EVIDENCE: Final = (
    "pipelines/fixtures/inputs/minnesota_aggregate_manifest_v1.json",
    "pipelines/fixtures/inputs/miso_ba_context_2024_h1.csv",
    "pipelines/fixtures/inputs/mn_county_plant_capacity_2024.csv",
    "pipelines/fixtures/inputs/mn_unassigned_plant_capacity_2024.csv",
    "data/sources/minnesota-accepted-artifact-inventory.json",
    "data/sources/minnesota-source-authority-ledger-v1.json",
    "data/artifacts/minnesota/readiness-receipt-v1.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy(
    source: Path, destination: Path, *, label: str, detail: str
) -> dict[str, object]:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return _file_entry(destination, label=label, detail=detail)


def _file_entry(
    path: Path, *, label: str, detail: str, rows: int | None = None
) -> dict[str, object]:
    return {
        "path": path.as_posix(),
        "label": label,
        "detail": detail,
        "rows": rows,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _copy_table(
    connection: duckdb.DuckDBPyConnection, item: TableExport, output: Path
) -> dict[str, object]:
    table = '"' + item.table.replace('"', '""') + '"'
    exists = connection.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'main' AND table_name = ?",
        [item.table],
    ).fetchone()
    if exists is None:
        raise RuntimeError(f"approved source table is missing: {item.table}")
    count = int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    path = output / "tables" / item.filename
    path.parent.mkdir(parents=True, exist_ok=True)
    escaped = path.as_posix().replace("'", "''")
    connection.execute(
        f"COPY (SELECT * FROM {table} ORDER BY {item.order_by}) TO '{escaped}' "
        "(HEADER, DELIMITER ',')"
    )
    entry = _file_entry(path, label=item.classification, detail=item.detail, rows=count)
    entry["path"] = path.relative_to(output).as_posix()
    return entry


def _write_index(output: Path, inventory: dict[str, object]) -> None:
    (output / "inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    sections: list[str] = []
    for title, key in (
        ("Approved source-table exports", "table_exports"),
        ("Authoritative EIA-930 downloads and receipt", "eia_downloads"),
        ("Verified Minnesota source evidence and manifests", "minnesota_evidence"),
    ):
        rows = []
        for entry in inventory[key]:  # type: ignore[index]
            value = entry  # type: ignore[assignment]
            rows.append(
                '<tr><td><a download href="{path}">{path}</a></td><td>{label}</td>'
                "<td>{rows}</td><td>{bytes:,}</td><td><code>{sha}</code></td><td>{detail}</td></tr>".format(
                    path=html.escape(str(value["path"])),
                    label=html.escape(str(value["label"])),
                    rows="—"
                    if value["rows"] is None
                    else html.escape(str(value["rows"])),
                    bytes=int(value["bytes"]),
                    sha=html.escape(str(value["sha256"])),
                    detail=html.escape(str(value["detail"])),
                )
            )
        sections.append(
            f"<h2>{html.escape(title)}</h2><table><thead><tr><th>File</th><th>Type</th>"
            "<th>Rows</th><th>Bytes</th><th>SHA-256</th><th>Scope</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    unavailable = "".join(
        f"<li>{html.escape(item)}</li>" for item in inventory["unavailable"]
    )
    excluded = "".join(
        f"<li><code>{html.escape(item)}</code></li>"
        for item in inventory["derived_or_model_tables"]
    )
    generated = html.escape(str(inventory["generated_at"]))
    (output / "index.html").write_text(
        f"""<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>Flux approved raw-data snapshot</title><style>body{{font:16px system-ui,sans-serif;margin:2rem;max-width:1200px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd;padding:.55rem;text-align:left;vertical-align:top}}th{{background:#eef3f8}}code{{word-break:break-all}}.notice{{padding:1rem;background:#fff7e0;border-left:4px solid #a66}}</style>
<h1>Flux approved raw-data snapshot</h1><p>Generated {generated}. Downloads are fixed, read-only copies; this directory accepts no SQL, table name, or filesystem path from a browser.</p>
<p class=\"notice\"><strong>Scope:</strong> Texas topology inputs are explicitly synthetic ACTIVSg2000. Physical inventory is source-backed inventory and does not establish electrical connectivity. EIA-930 and HRRR rows retain their source labels. Minnesota evidence is source-backed metadata/aggregate context, not a Minnesota topology.</p>
{"".join(sections)}<h2>Present but excluded derived/model tables</h2><p>These remain visible in the inventory boundary but are not labelled raw downloads.</p><ul>{excluded}</ul><h2>Unavailable upstream raw sources</h2><ul>{unavailable}</ul><p><a href=\"inventory.json\">Machine-readable inventory</a></p></html>""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--eia-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    connection = duckdb.connect(str(args.source_db), read_only=True)
    try:
        table_exports = [
            _copy_table(connection, item, output) for item in TABLE_EXPORTS
        ]
    finally:
        connection.close()
    eia_downloads = []
    for source_name in EIA_FILES:
        source = args.eia_root / source_name
        relative = Path("eia930") / source_name
        eia_downloads.append(
            _copy(
                source,
                output / relative,
                label="authoritative download"
                if source.suffix in {".csv", ".xlsx"}
                else "source receipt",
                detail="Recovered EIA-930 source material and provenance receipt.",
            )
        )
        eia_downloads[-1]["path"] = relative.as_posix()
    minnesota_evidence = []
    for source_name in MN_EVIDENCE:
        source = ROOT / source_name
        relative = Path("minnesota") / Path(source_name).name
        minnesota_evidence.append(
            _copy(
                source,
                output / relative,
                label="verified Minnesota evidence",
                detail="Checked-in source evidence or manifest; see its own limits before reuse.",
            )
        )
        minnesota_evidence[-1]["path"] = relative.as_posix()
    inventory: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_database": "approved local source database (read-only snapshot; absolute operator path omitted)",
        "table_exports": table_exports,
        "eia_downloads": eia_downloads,
        "minnesota_evidence": minnesota_evidence,
        "derived_or_model_tables": list(DERIVED_OR_MODEL_TABLES),
        "unavailable": [
            "Upstream raw TIGER county geometry is declared by the Minnesota manifest but not checked into this repository.",
            "Upstream MnGeo service-area geometry is declared by the Minnesota manifest but not checked into this repository.",
            "Upstream EIA-860 Minnesota source download is not checked in; only the verified aggregate evidence files are present.",
            "No licensed Minnesota network case, bus/branch topology, or flow data is present.",
        ],
    }
    _write_index(output, inventory)


if __name__ == "__main__":
    main()
