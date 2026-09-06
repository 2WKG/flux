from copy import deepcopy

import pytest

from pipelines.assemble_physical_inventory import AssemblyError, assemble_artifacts
from pipelines.physical_inventory import artifact_sha256
from pipelines.tests.test_physical_inventory import _artifact


def _component(asset_id: str, scope: str, geography: str = "tx") -> dict:
    artifact = _artifact()
    artifact["artifact_id"] = f"{geography}:physical-inventory:1.0.0"
    artifact["geography_id"] = geography
    artifact["assets"][0]["asset_id"] = asset_id
    artifact["coverage"][0]["scope_id"] = scope
    artifact["content_sha256"] = artifact_sha256(artifact)
    return artifact


def test_composes_disjoint_inputs_with_digest_lineage_and_state_alias() -> None:
    route = _component("hifld:line:1", "tx:routes", "us-tx")
    eia = _component("eia860:plant:1", "tx:generation")
    combined = assemble_artifacts([route, eia], release_version="1.1.0")
    assert combined["artifact_id"] == "tx:physical-inventory:1.1.0"
    assert combined["input_artifact_sha256s"] == sorted([route["content_sha256"], eia["content_sha256"]])
    assert {item["asset_id"] for item in combined["assets"]} == {"hifld:line:1", "eia860:plant:1"}
    assert all(item["status"] != "complete" for item in combined["coverage"])


def test_composes_state_qualified_county_artifact_into_its_state_release() -> None:
    county = _component("county:line:1", "mn:county", "mn:mille-lacs-county")
    eia = _component("eia:plant:1", "mn:generation", "mn")
    combined = assemble_artifacts([county, eia], release_version="1.1.0")
    assert combined["geography_id"] == "mn"


def test_rejects_conflicting_source_and_duplicate_asset() -> None:
    first = _component("a", "tx:a")
    second = _component("b", "tx:b")
    second["sources"][0]["source_ref"] = "https://different.example.test"
    second["content_sha256"] = artifact_sha256(second)
    with pytest.raises(AssemblyError, match="conflicting source"):
        assemble_artifacts([first, second], release_version="1.1.0")
    second = deepcopy(first)
    second["artifact_version"] = "1.0.1"
    second["artifact_id"] = "tx:physical-inventory:1.0.1"
    second["content_sha256"] = artifact_sha256(second)
    with pytest.raises(AssemblyError, match="duplicate asset"):
        assemble_artifacts([first, second], release_version="1.1.0")
