"""Keep Minnesota physical-source availability claims mechanically honest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "data/sources/minnesota-source-authority-ledger-v1.json"

EUSA_SERVICE_URL = (
    "https://arcgis.metc.state.mn.us/server/rest/services/GDRS/"
    "MNGEO_util_service_areas/FeatureServer/0"
)
MILLE_LACS_SERVICE_URL = (
    "https://gis.co.mille-lacs.mn.us/arcgis/rest/services/Utilities/MapServer"
)

# Every physical class the ledger declares, pinned to the status the evidence
# supports. Naming only a subset lets an unnamed class be promoted silently.
EXPECTED_CLASS_STATUS = {
    "retail_service_area": "available_limited",
    "transmission_line": "available_limited",
    "subtransmission_line": "unavailable",
    "substation": "available_limited",
    "support_structure": "unavailable",
    "distribution_line_and_device": "unavailable",
    "real_electrical_connectivity": "unavailable",
    "cross_border_interface": "restricted",
}


def _ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _source(ledger: dict, source_id: str) -> dict:
    return next(
        row for row in ledger["source_records"] if row["source_id"] == source_id
    )


def test_ledger_has_explicit_scope_and_known_source_statuses():
    ledger = _ledger()
    assert ledger["state"] == "MN"
    assert "not statewide completeness" in ledger["purpose"]
    statuses = set(ledger["source_status_values"])
    assert statuses == {
        "accepted_limited",
        "candidate",
        "denied",
        "restricted",
        "unavailable",
    }
    for source in ledger["source_records"]:
        assert source["acquisition_state"] in statuses
        assert source["url"].startswith("https://")
        assert source["spatial_extent"]
        assert source["geometry_accuracy_basis"]


def test_every_physical_class_keeps_the_status_its_evidence_supports():
    ledger = _ledger()
    coverage = {row["class_id"]: row for row in ledger["physical_class_coverage"]}
    assert {
        cid: row["status"] for cid, row in coverage.items()
    } == EXPECTED_CLASS_STATUS
    assert coverage["retail_service_area"]["denominator"] == 192
    for class_id in ("transmission_line", "substation"):
        assert coverage[class_id]["denominator"] is None
    for class_id, status in EXPECTED_CLASS_STATUS.items():
        if status != "available_limited":
            assert coverage[class_id]["denominator"] is None
            assert coverage[class_id]["known_count"] is None


def test_ledger_does_not_promote_limited_geometry_to_statewide_or_connectivity_coverage():
    ledger = _ledger()
    mille_lacs = _source(ledger, "mille_lacs_county_utilities_mapserver_2026")
    assert mille_lacs["url"] == MILLE_LACS_SERVICE_URL
    assert mille_lacs["source_crs"] == "WKID 103705"
    layers = mille_lacs["verified_layers"]
    assert [layer["returned_feature_count"] for layer in layers] == [11, 31]
    assert [layer["layer_url"] for layer in layers] == [
        f"{MILLE_LACS_SERVICE_URL}/0",
        f"{MILLE_LACS_SERVICE_URL}/2",
    ]
    assert layers[1]["reported_line_miles"] == 178.68783197
    assert layers[1]["voltage_counts"] == [
        {"voltage_kv": 69, "feature_count": 28},
        {"voltage_kv": 230, "feature_count": 3},
    ]
    assert sum(entry["feature_count"] for entry in layers[1]["voltage_counts"]) == 31
    assert "statewide denominator" in layers[1]["denominator_scope"]


def test_eusa_source_cites_the_order_that_makes_it_official():
    ledger = _ledger()
    eusa = _source(ledger, "mngeo_eusa_featureserver_2026")
    assert eusa["url"] == EUSA_SERVICE_URL
    assert eusa["source_crs"] == "EPSG:26915"
    assert "April 9, 2014 Order in Docket 12-957" in eusa["authority"]
    assert "April 9, 2014 Order in Docket 12-957" in eusa["authority_quote"]
    assert eusa["authority_url"] == "https://mn.gov/puc/activities/maps/"
    assert eusa["authority_archive_url"].startswith("https://web.archive.org/web/2026")
    assert eusa["authority_archive_date"] == "2026-04-20"


def test_withdrawn_statewide_source_is_cited_where_it_can_still_be_read():
    ledger = _ledger()
    notice = _source(ledger, "mngeo_retired_transmission_substation_dataset_notice")
    assert notice["acquisition_state"] == "unavailable"
    assert notice["archive_url"] == (
        "https://web.archive.org/web/20260421111929/"
        "https://www.mngeo.state.mn.us/chouse/utilities.html"
    )
    assert notice["archive_date"] == "2026-04-21"
    assert "301" in notice["canonical_url_status"]
    assert notice["notice_quote"] == (
        "7/20/2022: Given existing accuracy problems with the dataset and insufficient "
        "current information, the Minnesota Department of Commerce cannot continue to "
        "support the distribution and use of this dataset."
    )
    assert (
        "Publisher withdrawal for accuracy and currency"
        in notice["unavailability_reason"]
    )
    assert notice["supports_classes"] == []


def test_every_query_receipt_replays_against_its_own_captured_bytes():
    ledger = _ledger()
    receipts = []
    for source in ledger["source_records"]:
        if "verified_query" in source:
            receipts.append((source["url"], source["verified_query"]))
        for layer in source.get("verified_layers", []):
            receipts.append((layer["layer_url"], layer["verified_query"]))
    assert len(receipts) == 3

    for parent_url, query in receipts:
        # The receipt must name the endpoint it came from, not just its parameters:
        # repointing the host or path has to fail here.
        assert query["url"].startswith(parent_url + "/query?")
        verification = query["verification"]
        raw = (ROOT / verification["response_file"]).read_bytes()
        assert len(raw) == verification["response_bytes"]
        assert hashlib.sha256(raw).hexdigest() == verification["response_sha256"]
        assert json.loads(raw)["count"] == query["returned_feature_count"]
        assert verification["retrieved_at"].startswith("2026-09-06")
        assert verification["capture_method"].startswith("curl ")

    eusa_query = _source(ledger, "mngeo_eusa_featureserver_2026")["verified_query"]
    assert eusa_query["returned_feature_count"] == 192
