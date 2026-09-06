import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from pipelines import minnesota_mille_lacs_physical_inventory as mille_lacs
from pipelines.minnesota_mille_lacs_physical_inventory import (
    build_artifact,
    layer_query_url,
)
from pipelines.physical_inventory import (
    PhysicalInventoryError,
    artifact_sha256,
    validate_artifact,
)


def test_mille_lacs_inventory_keeps_native_crs_and_never_creates_connectivity(
    tmp_path: Path,
):
    lines = {
        "geometryType": "esriGeometryPolyline",
        "spatialReference": {"wkid": 103705},
        "features": [
            {
                "attributes": {"OBJECTID": 7, "COMPANY": "Example", "VOLTAGE": 69},
                "geometry": {"paths": [[[500000, 200000], [500100, 200100]]]},
            }
        ],
    }
    substations = {
        "geometryType": "esriGeometryPoint",
        "spatialReference": {"wkid": 103705},
        "features": [
            {
                "attributes": {"OBJECTID": 9, "COMPANY": "Example"},
                "geometry": {"x": 500000, "y": 200000},
            }
        ],
    }
    lines_path, substations_path = (
        tmp_path / "lines.json",
        tmp_path / "substations.json",
    )
    lines_path.write_text(json.dumps(lines))
    substations_path.write_text(json.dumps(substations))
    artifact = build_artifact(
        lines_path=lines_path,
        substations_path=substations_path,
        retrieved_at="2026-09-06T00:00:00+00:00",
    )
    validate_artifact(artifact)
    assert len(artifact["assets"]) == 2
    assert {row["geometry_crs"] for row in artifact["assets"]} == {"ESRI:103705"}
    assert {row["geometry_precision_m"] for row in artifact["assets"]} == {None}
    assert artifact["terminals"] == []
    assert artifact["connectivity_edges"] == []
    assert [row["observed_count"] for row in artifact["coverage"]] == [1, 1]
    assert [row["denominator_count"] for row in artifact["coverage"]] == [None, None]
    assert all(
        "not countywide or statewide" in row["source_scope"]
        for row in artifact["coverage"]
    )


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED = REPO_ROOT / "data/physical-inventory/minnesota/mille-lacs-county/v1"
RECEIPT = REPO_ROOT / "data/sources/minnesota-mille-lacs-utilities-2026-09-06.json"
RETRIEVED_AT = "2026-09-06T07:05:03Z"


def _rebuild_committed() -> dict:
    return build_artifact(
        lines_path=COMMITTED / "lines.arcgis.json",
        substations_path=COMMITTED / "substations.arcgis.json",
        retrieved_at=RETRIEVED_AT,
    )


def test_committed_captures_rebuild_the_committed_artifact_byte_for_byte() -> None:
    """The shipped numbers are bound to the shipped capture bytes."""
    rebuilt = json.dumps(
        _rebuild_committed(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    committed_bytes = (COMMITTED / "physical-inventory.json").read_bytes()
    assert rebuilt == committed_bytes
    committed = json.loads(committed_bytes)
    assert committed["content_sha256"] == artifact_sha256(committed)
    by_class = Counter(row["asset_class"] for row in committed["assets"])
    assert by_class == {"line": 31, "substation": 11}
    assert committed["terminals"] == []
    assert committed["connectivity_edges"] == []


def test_source_receipt_matches_the_committed_capture_bytes_and_counts() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    for layer, capture in (
        ("2", "lines.arcgis.json"),
        ("0", "substations.arcgis.json"),
    ):
        entry = receipt["layers"][layer]
        raw = (COMMITTED / capture).read_bytes()
        assert (
            entry["file"]
            == f"data/physical-inventory/minnesota/mille-lacs-county/v1/{capture}"
        )
        assert entry["raw_bytes"] == len(raw)
        assert entry["raw_sha256"] == hashlib.sha256(raw).hexdigest()
        payload = json.loads(raw)
        assert entry["geometry_type"] == payload["geometryType"]
        assert (
            len(payload["features"])
            == receipt["verification"]["captured_feature_counts"][layer]
        )
        assert (
            receipt["verification"]["live_return_count_only"][layer]
            == receipt["verification"]["captured_feature_counts"][layer]
        )
        assert entry["layer_query_url"] == layer_query_url(int(layer))
    artifact_bytes = (COMMITTED / "physical-inventory.json").read_bytes()
    assert receipt["artifact"]["bytes"] == len(artifact_bytes)
    assert (
        receipt["artifact"]["file_sha256"] == hashlib.sha256(artifact_bytes).hexdigest()
    )
    assert (
        receipt["artifact"]["content_sha256"]
        == json.loads(artifact_bytes)["content_sha256"]
    )
    # Every declared source digests exactly one named capture file.
    declared = {
        row["source_id"]: row["content_sha256"]
        for row in json.loads(artifact_bytes)["sources"]
    }
    for layer, capture in (
        ("2", "lines.arcgis.json"),
        ("0", "substations.arcgis.json"),
    ):
        entry = receipt["layers"][layer]
        assert declared[entry["source_id"]] == entry["raw_sha256"]
    assert "Mille Lacs County MN" in receipt["license_access"]


def _payloads() -> tuple[dict, dict]:
    lines = {
        "geometryType": "esriGeometryPolyline",
        "spatialReference": {"wkid": 103705, "latestWkid": 103705},
        "features": [
            {
                "attributes": {"OBJECTID": oid, "COMPANY": "Example", "VOLTAGE": 69},
                "geometry": {
                    "paths": [[[500000 + oid, 200000], [500100 + oid, 200100]]]
                },
            }
            for oid in (3, 1, 2)
        ],
    }
    substations = {
        "geometryType": "esriGeometryPoint",
        "spatialReference": {"wkid": 103705, "latestWkid": 103705},
        "features": [
            {
                "attributes": {"OBJECTID": 9, "COMPANY": "Example"},
                "geometry": {"x": 500000, "y": 200000},
            }
        ],
    }
    return lines, substations


def _write(tmp_path: Path, lines: dict, substations: dict) -> tuple[Path, Path]:
    lines_path, substations_path = tmp_path / "lines.json", tmp_path / "subs.json"
    lines_path.write_text(json.dumps(lines))
    substations_path.write_text(json.dumps(substations))
    return lines_path, substations_path


def test_rejects_a_source_payload_whose_geometry_type_does_not_match(
    tmp_path: Path,
) -> None:
    lines, substations = _payloads()
    lines["geometryType"] = "esriGeometryPoint"
    lines_path, substations_path = _write(tmp_path, lines, substations)
    with pytest.raises(PhysicalInventoryError, match="esriGeometryPolyline"):
        build_artifact(
            lines_path=lines_path,
            substations_path=substations_path,
            retrieved_at=RETRIEVED_AT,
        )


def test_rejects_a_source_crs_that_is_not_the_native_mille_lacs_wkid(
    tmp_path: Path,
) -> None:
    lines, substations = _payloads()
    substations["spatialReference"] = {"wkid": 4326, "latestWkid": 4326}
    lines_path, substations_path = _write(tmp_path, lines, substations)
    with pytest.raises(PhysicalInventoryError, match="103705"):
        build_artifact(
            lines_path=lines_path,
            substations_path=substations_path,
            retrieved_at=RETRIEVED_AT,
        )


def test_build_artifact_validates_the_artifact_it_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict] = []

    def spy(artifact: dict) -> dict:
        seen.append(artifact)
        return validate_artifact(artifact)

    monkeypatch.setattr(mille_lacs, "validate_artifact", spy)
    lines_path, substations_path = _write(tmp_path, *_payloads())
    artifact = build_artifact(
        lines_path=lines_path,
        substations_path=substations_path,
        retrieved_at=RETRIEVED_AT,
    )
    assert seen == [artifact]


def test_asset_order_is_deterministic_in_source_objectid_order(
    tmp_path: Path,
) -> None:
    """Reordering the source response must not change the artifact digest."""
    lines, substations = _payloads()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a_lines, a_subs = _write(tmp_path / "a", lines, substations)
    shuffled = dict(lines, features=list(reversed(lines["features"])))
    b_lines, b_subs = _write(tmp_path / "b", shuffled, substations)
    a = build_artifact(
        lines_path=a_lines, substations_path=a_subs, retrieved_at=RETRIEVED_AT
    )
    b = build_artifact(
        lines_path=b_lines, substations_path=b_subs, retrieved_at=RETRIEVED_AT
    )
    assert [row["source_record_id"] for row in a["assets"]] == ["1", "2", "3", "9"]
    assert [row["asset_id"] for row in a["assets"]] == [
        row["asset_id"] for row in b["assets"]
    ]
    assert [row["geometry"] for row in a["assets"]] == [
        row["geometry"] for row in b["assets"]
    ]


def test_coverage_reports_an_unknown_denominator_with_a_named_reason(
    tmp_path: Path,
) -> None:
    lines_path, substations_path = _write(tmp_path, *_payloads())
    artifact = build_artifact(
        lines_path=lines_path,
        substations_path=substations_path,
        retrieved_at=RETRIEVED_AT,
    )
    for row in artifact["coverage"]:
        assert row["status"] == "partial"
        assert row["denominator_count"] is None
        assert row["denominator_count"] != row["observed_count"]
        assert row["denominator_basis"].startswith("unknown:")
        assert "not a denominator" in row["denominator_basis"]


def test_each_declared_source_digests_exactly_one_named_capture_file(
    tmp_path: Path,
) -> None:
    lines_path, substations_path = _write(tmp_path, *_payloads())
    artifact = build_artifact(
        lines_path=lines_path,
        substations_path=substations_path,
        retrieved_at=RETRIEVED_AT,
    )
    digests = {row["source_id"]: row["content_sha256"] for row in artifact["sources"]}
    assert digests == {
        mille_lacs.LINES_SOURCE_ID: hashlib.sha256(lines_path.read_bytes()).hexdigest(),
        mille_lacs.SUBSTATIONS_SOURCE_ID: hashlib.sha256(
            substations_path.read_bytes()
        ).hexdigest(),
    }
    for row in artifact["sources"]:
        assert row["source_version"].endswith(RETRIEVED_AT)
        assert row["source_ref"].startswith(mille_lacs.SERVICE_ROOT)
        assert "where=1%3D1" in row["source_ref"]
        assert mille_lacs.SOURCE_COPYRIGHT in row["license_or_terms"]
