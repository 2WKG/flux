"""Offline behaviour tests for the Texas distribution acquisition lane.

Every test here runs against a fake ArcGIS session.  None of them reaches a
provider, and none of them asserts a live count.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from pipelines import texas_distribution as lane
from pipelines.physical_inventory import PhysicalInventoryError, validate_artifact

ROOT = Path(__file__).resolve().parents[2]
LEDGER = (
    ROOT / "data" / "sources" / "texas-distribution-source-authority-ledger-v1.json"
)

AUSTIN = lane.SERVICE_AREA_LAYERS[0]


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = json.dumps(payload).encode()

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return json.loads(self.content)


class _Session:
    """Answers the count query and then the feature query, in that order."""

    def __init__(
        self, count: int, features: list[dict[str, Any]], wkid: int, **extra: Any
    ) -> None:
        self._count = count
        self._features = features
        self._wkid = wkid
        self._extra = extra
        self.requests: list[dict[str, str]] = []

    def get(self, url: str, params: dict[str, str], timeout: int) -> _Response:
        self.requests.append({"url": url, **params})
        if params.get("returnCountOnly") == "true":
            return _Response({"count": self._count})
        return _Response(
            {
                "spatialReference": {"wkid": 102739, "latestWkid": self._wkid},
                "features": self._features,
                **self._extra,
            }
        )


def _polygon(object_id: int) -> dict[str, Any]:
    return {
        "attributes": {"OBJECTID": object_id},
        "geometry": {
            "rings": [
                [
                    [3000000.0, 10000000.0],
                    [3000010.0, 10000000.0],
                    [3000010.0, 10000010.0],
                    [3000000.0, 10000000.0],
                ]
            ]
        },
    }


def _session(**kwargs: Any) -> _Session:
    return _Session(1, [_polygon(1)], AUSTIN.native_wkid, **kwargs)


def test_a_service_area_polygon_never_becomes_a_physical_asset() -> None:
    session = _session()
    source, capture = lane.fetch_service_area_layer(AUSTIN, session=session)

    artifact, _ = lane.build_artifact([source], "2026-09-06T13:44:02+00:00")

    assert capture["returned_features"] == 1
    assert capture["assets_created"] == 0
    assert artifact["assets"] == []
    assert artifact["terminals"] == []
    assert artifact["connectivity_edges"] == []


def test_the_artifact_validates_against_the_shared_contract() -> None:
    session = _session()
    source, _ = lane.fetch_service_area_layer(AUSTIN, session=session)

    artifact, _ = lane.build_artifact([source], "2026-09-06T13:44:02+00:00")

    assert validate_artifact(artifact) is artifact
    assert artifact["artifact_id"] == "us-tx-distribution:physical-inventory:1.0.0"
    assert artifact["inventory_mode"] == "physical_observed"
    assert artifact["electrical_model_mode"] == "none"


def test_every_distribution_class_is_unavailable_with_an_unknown_denominator() -> None:
    session = _session()
    source, _ = lane.fetch_service_area_layer(AUSTIN, session=session)

    coverage = lane.build_artifact([source], "2026-09-06T13:44:02+00:00")[0]["coverage"]

    classes = {row["asset_class"] for row in coverage}
    assert classes == {name for name, _ in lane.DISTRIBUTION_COVERAGE_CLASSES}
    assert {
        "distribution_feeder",
        "cable",
        "substation",
        "transformer",
        "pole",
        "support",
    } <= classes
    for row in coverage:
        assert row["status"] == "unavailable"
        assert row["observed_count"] == 0
        # An unknown count is null, never zero-for-unknown.
        assert row["denominator_count"] is None
        assert row["unknown_count"] is None
        assert row["unavailable_count"] is None
        assert "unknown, not zero" in row["reason"]
        assert lane.LEDGER_PATH in row["reason"]


def test_the_source_retains_identity_native_crs_and_a_digest_of_the_real_payload() -> (
    None
):
    session = _session()

    source, capture = lane.fetch_service_area_layer(AUSTIN, session=session)

    assert source["source_id"] == AUSTIN.source_id
    assert source["authority"] == AUSTIN.authority
    assert source["source_ref"] == AUSTIN.layer_url
    assert capture["native_crs"] == "EPSG:2277"
    assert capture["observed_wkid"] == 2277
    # The digest is of the bytes the service actually returned.
    body = next(
        request
        for request in session.requests
        if request.get("returnCountOnly") != "true"
    )
    assert body["outFields"] == "*"
    assert "outSR" not in body, (
        "outSR must be omitted so the service answers in its native CRS"
    )
    assert (
        source["content_sha256"]
        == hashlib.sha256(
            json.dumps(
                {
                    "spatialReference": {"wkid": 102739, "latestWkid": 2277},
                    "features": [_polygon(1)],
                }
            ).encode()
        ).hexdigest()
    )


def test_a_truncated_page_fails_the_acquisition() -> None:
    session = _session(exceededTransferLimit=True)

    with pytest.raises(lane.TexasDistributionError, match="truncated"):
        lane.fetch_service_area_layer(AUSTIN, session=session)


def test_a_count_mismatch_fails_the_acquisition() -> None:
    session = _Session(7, [_polygon(1)], AUSTIN.native_wkid)

    with pytest.raises(lane.TexasDistributionError, match="declared count"):
        lane.fetch_service_area_layer(AUSTIN, session=session)


def test_a_reprojected_response_fails_the_acquisition() -> None:
    session = _Session(1, [_polygon(1)], 4326)

    with pytest.raises(lane.TexasDistributionError, match="ledger declares"):
        lane.fetch_service_area_layer(AUSTIN, session=session)


def test_customer_level_attributes_are_refused_rather_than_published() -> None:
    feature = _polygon(1)
    feature["attributes"]["CUSTOMERS"] = 22276
    session = _Session(1, [feature], AUSTIN.native_wkid)

    with pytest.raises(lane.TexasDistributionError, match="customer-level attributes"):
        lane.fetch_service_area_layer(AUSTIN, session=session)


def test_the_receipt_reports_the_numbers_the_capture_actually_produced(
    tmp_path: Path,
) -> None:
    session = _session()
    source, capture = lane.fetch_service_area_layer(AUSTIN, session=session)
    artifact, verification = lane.build_artifact([source], "2026-09-06T13:44:02+00:00")

    receipt = lane.build_receipt(
        [capture], artifact, tmp_path / "out.json", 8194, "a" * 64, verification
    )

    assert receipt["sources"][0]["declared_count"] == 1
    assert receipt["sources"][0]["returned_features"] == 1
    assert receipt["sources"][0]["features_reconciled_to_declared_count"] is True
    assert receipt["sources"][0]["assets_created"] == 0
    assert receipt["verification"]["observed_assets"] == 0
    assert receipt["verification"]["unavailable_coverage_rows"] == len(
        artifact["coverage"]
    )
    assert receipt["files"]["out.json"]["tracked"] is False


def _ledger() -> dict[str, Any]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_the_ledger_names_an_owner_and_a_next_step_for_every_restricted_owner() -> None:
    owners = [
        record
        for record in _ledger()["source_records"]
        if record["acquisition_state"] == "restricted"
    ]

    assert len(owners) >= 10
    for record in owners:
        owner = record["owner"]
        assert owner["legal_name"]
        assert owner["role"]
        assert owner["request_route"].startswith("Direct written data request")
        assert owner["next_step"]
        assert record["restriction_reason"]


def test_the_ledger_keeps_every_unavailable_distribution_class_free_of_a_denominator() -> (
    None
):
    rows = {row["class_id"]: row for row in _ledger()["physical_class_coverage"]}

    for class_id in (
        "distribution_feeder",
        "distribution_cable",
        "distribution_substation",
        "distribution_transformer",
        "distribution_support_pole",
        "distribution_device",
        "distribution_service_connection",
        "distribution_terminal_connectivity",
    ):
        row = rows[class_id]
        assert row["status"] == "unavailable"
        assert row["denominator"] is None
        assert row["known_count"] is None
        assert row["accepted_source_ids"] == []
        assert "unknown, not zero" in row["reason"]


def test_the_ledger_records_the_rejected_signal_pole_layer_as_out_of_class() -> None:
    record = next(
        item
        for item in _ledger()["source_records"]
        if item["source_id"] == "austin-transportation-pole-attachments"
    )

    assert record["acquisition_state"] == "rejected_out_of_class"
    assert "Signal Pole" in record["coverage_limit"]
    assert record["supports_classes"] == []
    assert (
        "support" in record["does_not_support"] and "pole" in record["does_not_support"]
    )


RUN_RECEIPT = ROOT / "data" / "sources" / "texas-distribution-2026-09-06.json"


def test_build_artifact_actually_calls_the_shared_contract_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The call site is wired, not merely re-invoked by the test itself.

    Asserting ``validate_artifact(artifact) is artifact`` proves the validator
    works; it says nothing about whether ``build_artifact`` calls it. This
    records the call.
    """
    session = _session()
    source, _ = lane.fetch_service_area_layer(AUSTIN, session=session)
    calls: list[dict[str, Any]] = []

    def recorder(artifact: dict[str, Any]) -> dict[str, Any]:
        calls.append(artifact)
        return artifact

    monkeypatch.setattr(lane, "validate_artifact", recorder)
    artifact, verification = lane.build_artifact([source], "2026-09-06T13:44:02+00:00")

    assert len(calls) == 1
    assert calls[0] is artifact
    assert verification == {
        "artifact_validated_by": lane.VALIDATOR_NAME,
        "result": "passed",
    }


def test_an_artifact_that_fails_the_contract_is_never_published(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failing validation stops the run and can be recorded as ``failed``."""
    session = _session()
    source, capture = lane.fetch_service_area_layer(AUSTIN, session=session)

    def rejecting(artifact: dict[str, Any]) -> dict[str, Any]:
        raise PhysicalInventoryError("unsupported physical inventory contract_version")

    monkeypatch.setattr(lane, "validate_artifact", rejecting)
    with pytest.raises(lane.TexasDistributionError, match="failed the shared"):
        lane.build_artifact([source], "2026-09-06T13:44:02+00:00")

    rejected, verification = lane.validate_against_contract({"contract_version": "9"})
    assert rejected is None
    assert verification["result"] == "failed"
    assert "contract_version" in verification["detail"]

    # A receipt built from a failed validation says so; ``passed`` is not a
    # literal the receipt can only ever print.
    monkeypatch.undo()
    artifact, _ = lane.build_artifact([source], "2026-09-06T13:44:02+00:00")
    receipt = lane.build_receipt(
        [capture], artifact, tmp_path / "out.json", 8194, "a" * 64, verification
    )
    assert receipt["verification"]["result"] == "failed"


def test_the_committed_run_receipt_rebuilds_from_its_own_record() -> None:
    """The checked-in receipt must reproduce, not merely be plausible.

    Everything the receipt claims about the artifact — its content digest, the
    gitignored payload's byte count and digest, its coverage rows and its
    verification counts — is recomputed here from the receipt's own recorded
    per-source facts plus the committed layer constants. No network is used;
    the wire digests the sources carry are the acquisition's evidence and are
    taken as given.
    """
    committed = json.loads(RUN_RECEIPT.read_text(encoding="utf-8"))
    layers = {layer.source_id: layer for layer in lane.SERVICE_AREA_LAYERS}
    assert [entry["source_id"] for entry in committed["sources"]] == list(layers)

    sources = []
    captures = []
    for entry in committed["sources"]:
        layer = layers[entry["source_id"]]
        assert entry["layer_url"] == layer.layer_url
        assert entry["native_crs"] == layer.native_crs
        sources.append(
            {
                "source_id": layer.source_id,
                "authority": layer.authority,
                "source_ref": layer.layer_url,
                "source_version": layer.source_version,
                "retrieved_at": entry["retrieved_at"],
                "license_or_terms": layer.license_or_terms,
                "content_sha256": entry["content_sha256"],
            }
        )
        captures.append(
            {
                "source_id": entry["source_id"],
                "layer_url": entry["layer_url"],
                "retrieved_at": entry["retrieved_at"],
                "declared_count": entry["declared_count"],
                "returned_features": entry["returned_features"],
                "native_crs": entry["native_crs"],
                "response_bytes": entry["response_bytes"],
                "content_sha256": entry["content_sha256"],
                "assets_created": entry["assets_created"],
            }
        )

    artifact, verification = lane.build_artifact(sources, committed["retrieved_at"])
    payload = json.dumps(artifact, indent=2) + "\n"
    published = next(iter(committed["files"].values()))
    rebuilt = lane.build_receipt(
        captures,
        artifact,
        Path(published["path"]),
        len(payload.encode()),
        hashlib.sha256(payload.encode()).hexdigest(),
        verification,
    )
    assert rebuilt == committed


def test_the_ledger_forbids_deriving_distribution_from_transmission_or_hifld() -> None:
    """The temptation this state has data for must be named, not just avoided.

    ``data/sources/receipts/`` already carries ``texas-hifld-transmission-*``
    captures. The code does not derive distribution from them; the ledger has
    to say so, because the ledger is what the next acquisition reads.
    """
    forbidden = " ".join(
        _ledger()["implementation_handoff"]["forbidden_derivations"]
    ).lower()
    assert "transmission" in forbidden
    assert "hifld" in forbidden
    assert "substation" in forbidden
    named = next(
        line
        for line in _ledger()["implementation_handoff"]["forbidden_derivations"]
        if "HIFLD" in line
    )
    assert "transmission" in named.lower()
