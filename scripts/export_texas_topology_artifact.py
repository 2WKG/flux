"""Export the deployable ACTIVSg2000 renderer artifact from a validated grid DB."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from copilot.routes.model_geometry import _read_model_geometry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duckdb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = _read_model_geometry(args.duckdb, None)
    data = payload["data"]
    if data["counts"] != {"buses": 2000, "branches": 3206, "lines": 2359, "impedance_branches": 847}:
        raise SystemExit(f"unexpected validated topology counts: {data['counts']}")
    artifact = {
        "artifact_id": "tx:synthetic-topology:activsg2000-current-v1",
        "artifact_version": "1.0.0",
        "source": {
            "case": "ACTIVSg2000 current MATPOWER case",
            "coordinates": "ACTIVSg2000.aux current-version tamu_aux mapping",
            "topology": "synthetic (ACTIVSg2000)",
            "physical_inventory_equivalence": False,
        },
        "payload": payload,
    }
    raw = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as zipped:
            zipped.write(raw)
    manifest = {
        "artifact_id": artifact["artifact_id"],
        "artifact_version": artifact["artifact_version"],
        "path": args.output.name,
        "compressed_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "counts": data["counts"],
        "source": artifact["source"],
    }
    args.output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
