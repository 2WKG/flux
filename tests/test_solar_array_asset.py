from __future__ import annotations

import json
from pathlib import Path

from scripts.render_solar_array_preview import SIZE, render
from scripts.validate_solar_array_asset import CATALOG_PATH, META_PATH, validate


def test_metadata_matches_shared_archetype():
    assert (
        validate(
            json.loads(META_PATH.read_text()), json.loads(CATALOG_PATH.read_text())
        )
        == []
    )


def test_preview_renderer_creates_contract_png(tmp_path: Path):
    preview = tmp_path / "solar_array.preview.png"
    render(preview)
    payload = preview.read_bytes()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert int.from_bytes(payload[16:20], "big") == SIZE
    assert int.from_bytes(payload[20:24], "big") == SIZE
