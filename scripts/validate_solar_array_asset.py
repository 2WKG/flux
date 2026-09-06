"""Validate solar-array export metadata against the shared 3D catalog."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.asset_contract_lib import (
    CATALOG_PATH,
    ROOT,
    AssetContractError,
    load_catalog,
    load_json,
    validate_export_meta,
)

ARCHETYPE_ID = "solar_array"
META_PATH = ROOT / f"data/3d/assets/{ARCHETYPE_ID}.meta.json"


def validate(meta: Any, catalog: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Every rule lives in the shared, catalog-reading validator."""
    return validate_export_meta(meta, catalog, ARCHETYPE_ID, root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta", type=Path, default=META_PATH)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args(argv)
    try:
        meta = load_json(args.meta, "meta")
        catalog = load_catalog(args.catalog)
    except AssetContractError as exc:
        print(f"{ARCHETYPE_ID} metadata could not be read: {exc}", file=sys.stderr)
        return 2
    errors = validate(meta, catalog)
    if errors:
        print("\n".join(errors))
        return 1
    print(f"{ARCHETYPE_ID} metadata matches {catalog['contractId']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
