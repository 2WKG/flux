import json

import pytest

from pipelines.physical_connectivity import (
    READINESS_PATH,
    ConnectivityEvidenceError,
    blocked_readiness_receipt,
    build_readiness_document,
    normalized_receipt,
)

SOURCE = {
    "source_id": "mn-authorized-release-2026-09",
    "authority": "Authorized test release authority",
    "source_ref": "https://example.test/release",
    "source_version": "2026-09",
    "retrieved_at": "2026-09-06T12:00:00Z",
    "license_or_terms": "Authorized redistribution under the release terms",
    "content_sha256": "b" * 64,
}


def _asset(asset_id):
    return {
        "asset_id": asset_id,
        "asset_class": "substation",
        "asset_kind": "substation",
        "source_id": SOURCE["source_id"],
        "source_record_id": f"record-{asset_id}",
        "geometry": None,
        "geometry_crs": None,
        "geometry_precision_m": None,
        "geometry_accuracy_basis": None,
        "geometry_derivation_method": None,
        "geometry_status": "unavailable",
    }


def _assets():
    return [_asset("substation-a"), _asset("substation-b")]


def _coverage():
    return [
        {
            "asset_class": "substation",
            "scope_id": "MN",
            "status": "partial",
            "observed_count": 2,
            "denominator_count": None,
            "unknown_count": None,
            "unavailable_count": 2,
            "denominator_basis": "no published statewide substation denominator",
            "source_scope": "one authorized test release",
            "reason": "test release covers two substations only",
        }
    ]


def _terminals():
    return [
        {
            "terminal_id": "SUB-A:BUS-1",
            "asset_id": "substation-a",
            "source_record_id": "terminal-1",
        },
        {
            "terminal_id": "SUB-B:BUS-2",
            "asset_id": "substation-b",
            "source_record_id": "terminal-2",
        },
    ]


def _edge():
    return {
        "edge_id": "line-7",
        "from_terminal_id": "SUB-A:BUS-1",
        "to_terminal_id": "SUB-B:BUS-2",
        "source_record_id": "line-record-7",
    }


def _receipt(**overrides):
    kwargs = {
        "state": "MN",
        "source": SOURCE,
        "assessed_at": "2026-09-06T12:00:00Z",
        "assets": _assets(),
        "coverage": _coverage(),
        "terminals": _terminals(),
        "edges": [_edge()],
    }
    kwargs.update(overrides)
    return normalized_receipt(**kwargs)


def test_authoritative_native_terminal_references_are_normalized_deterministically():
    receipt = _receipt(terminals=reversed(_terminals()))

    assert receipt["status"] == "ready_for_contract_integration"
    assert receipt["accepted_terminal_count"] == 2
    assert receipt["terminals"][0]["asset_id"] == "substation-a"
    assert receipt["edges"] == [
        {
            "edge_id": "line-7",
            "from_terminal_id": "SUB-A:BUS-1",
            "to_terminal_id": "SUB-B:BUS-2",
            "source_id": SOURCE["source_id"],
            "source_record_id": "line-record-7",
        }
    ]


def test_rows_are_accepted_by_the_physical_inventory_contract():
    """The rows this module emits must survive 2WKG-441's own validator."""
    from pipelines.physical_inventory import artifact_sha256, validate_artifact

    receipt = _receipt()
    artifact = {
        "artifact_id": "MN:physical-inventory:1.0.0",
        "contract_version": "1.0.0",
        "geography_id": "MN",
        "artifact_version": "1.0.0",
        "inventory_mode": "physical_observed",
        "electrical_model_mode": "source_backed",
        "created_at": "2026-09-06T12:00:00Z",
        "sources": [SOURCE],
        "assets": _assets(),
        "terminals": receipt["terminals"],
        "connectivity_edges": receipt["edges"],
        "coverage": _coverage(),
    }
    artifact["content_sha256"] = artifact_sha256(artifact)

    assert validate_artifact(artifact) is artifact


def test_source_id_must_resolve_inside_the_release():
    """A placeholder source_id can never satisfy the contract's sources[] check."""
    with pytest.raises(ConnectivityEvidenceError, match="rejected by the physical"):
        _receipt(
            assets=[
                dict(_asset("substation-a"), source_id="source-native-release"),
                _asset("substation-b"),
            ]
        )


def test_terminal_asset_id_must_exist_in_the_release():
    with pytest.raises(ConnectivityEvidenceError, match="rejected by the physical"):
        _receipt(assets=[_asset("substation-a")])


@pytest.mark.parametrize(
    "edge, message",
    [
        (
            {
                "edge_id": "shape-only",
                "source_record_id": "line-1",
                "geometry": "LINESTRING(...)",
            },
            "from_terminal_id",
        ),
        (
            {
                "edge_id": "unknown-endpoint",
                "from_terminal_id": "SUB-A:BUS-1",
                "to_terminal_id": "nearby-plant",
                "source_record_id": "line-2",
            },
            "rejected by the physical",
        ),
        (
            {
                "edge_id": "self-loop",
                "from_terminal_id": "SUB-A:BUS-1",
                "to_terminal_id": "SUB-A:BUS-1",
                "source_record_id": "line-3",
            },
            "rejected by the physical",
        ),
    ],
)
def test_geometry_or_nearby_context_cannot_reconstruct_connectivity(edge, message):
    with pytest.raises(ConnectivityEvidenceError, match=message):
        _receipt(state="TX", edges=[edge])


def test_repeated_terminal_identity_with_a_different_record_is_a_conflict():
    conflicting = _terminals() + [
        {
            "terminal_id": "SUB-A:BUS-1",
            "asset_id": "substation-a",
            "source_record_id": "terminal-99",
        }
    ]
    with pytest.raises(ConnectivityEvidenceError, match="conflicting source records"):
        _receipt(terminals=conflicting)


def test_an_exact_duplicate_terminal_row_collapses_instead_of_failing():
    receipt = _receipt(terminals=_terminals() + [_terminals()[0]])

    assert receipt["accepted_terminal_count"] == 2


def test_repeated_edge_identity_with_a_different_record_is_a_conflict():
    conflicting = [
        _edge(),
        dict(_edge(), to_terminal_id="SUB-A:BUS-1"),
    ]
    with pytest.raises(
        ConnectivityEvidenceError, match="edge_id 'line-7' has conflicting"
    ):
        _receipt(edges=conflicting)


def test_receipts_are_only_issued_for_the_two_states_in_scope():
    with pytest.raises(ConnectivityEvidenceError, match="state must be TX or MN"):
        _receipt(state="CA")
    with pytest.raises(ConnectivityEvidenceError, match="state must be TX or MN"):
        blocked_readiness_receipt(
            state="CA",
            source_name="somewhere else",
            source_url="https://example.test/elsewhere",
            source_version="v1",
            assessed_at="2026-09-06T12:00:00Z",
            reason="out of scope",
            capture_method="HTTPS GET",
            evidence=[_evidence()],
            verification={"authorized_release_obtained": False},
        )


def _evidence(**overrides):
    item = {
        "url": "https://example.test/page",
        "http_status": 200,
        "captured_at": "2026-09-06T12:00:00Z",
        "bytes": 10,
        "sha256": "a" * 64,
        "capture_method": "HTTPS GET",
        "quote": "a sentence that is present in the captured body",
        "quote_status": "verified",
        "note": "captured for this receipt",
    }
    item.update(overrides)
    return item


def test_blocked_receipt_carries_no_topology_or_coverage_claim():
    receipt = blocked_readiness_receipt(
        state="TX",
        source_name="ERCOT network-model access",
        source_url="https://www.ercot.com/gridinfo/modeling",
        source_version="public access check",
        assessed_at="2026-09-06T07:43:54Z",
        reason="Public materials describe the model, but no authorized release with terminals was obtained.",
        capture_method="HTTPS GET",
        evidence=[_evidence()],
        verification={"authorized_release_obtained": False},
    )

    assert receipt["status"] == "blocked"
    assert receipt["accepted_terminal_count"] == receipt["accepted_edge_count"] == 0
    assert "proximity" in receipt["prohibited_inferences"]
    assert receipt["capture_method"] == "HTTPS GET"
    assert receipt["evidence"][0]["sha256"] == "a" * 64


def test_a_quote_claimed_verified_needs_the_hash_of_the_body_it_came_from():
    with pytest.raises(ConnectivityEvidenceError, match="verified quote needs"):
        blocked_readiness_receipt(
            state="MN",
            source_name="catalog",
            source_url="https://example.test/catalog",
            source_version="v1",
            assessed_at="2026-09-06T12:00:00Z",
            reason="blocked",
            capture_method="HTTPS GET",
            evidence=[_evidence(sha256=None)],
            verification={"authorized_release_obtained": False},
        )


def test_a_blocked_receipt_cannot_assert_access_with_no_capture_attempt():
    with pytest.raises(ConnectivityEvidenceError, match="at least one capture attempt"):
        blocked_readiness_receipt(
            state="MN",
            source_name="catalog",
            source_url="https://example.test/catalog",
            source_version="v1",
            assessed_at="2026-09-06T12:00:00Z",
            reason="blocked",
            capture_method="HTTPS GET",
            evidence=[],
            verification={"authorized_release_obtained": False},
        )


def test_committed_readiness_record_is_the_generator_output():
    """`python -m pipelines.physical_connectivity` must reproduce the file byte for byte."""
    expected = (
        json.dumps(build_readiness_document(), indent=2, ensure_ascii=False) + "\n"
    )

    assert READINESS_PATH.read_text() == expected


def test_minnesota_quote_is_carried_with_the_body_it_was_read_from():
    """The MN catalog is captcha-walled live; the quote must cite a hashed capture."""
    receipts = {row["state"]: row for row in build_readiness_document()["receipts"]}
    verified = [
        item
        for item in receipts["MN"]["evidence"]
        if item["quote_status"] == "verified"
    ]

    assert len(verified) == 1
    assert "cannot continue to support" in verified[0]["quote"]
    assert verified[0]["sha256"] == (
        "fb8f8132c45fbde6eb6a09f01c16272736cfd848a4e4a136a4210ce0001032ee"
    )
    live = [
        item
        for item in receipts["MN"]["evidence"]
        if item["url"] == "https://www.mngeo.state.mn.us/chouse/utilities.html"
    ]
    assert live[0]["quote_status"] == "unverified_as_committed"
    assert receipts["MN"]["verification"]["live_catalog_url_readable"] is False
