from __future__ import annotations

import json

from scripts.validate_hospital_kit import META_PATH, validate_kit


def test_hospital_kit_matches_the_shared_contract():
    assert validate_kit() == []


def test_hospital_kit_has_no_minnesota_identity_claim():
    metadata = json.loads(META_PATH.read_text(encoding="utf-8"))

    assert "Minnesota location" in metadata["limit"]
    assert metadata["material_slots"][0]["default"] == "neutral"
