from copy import deepcopy

import pytest

from pipelines.assemble_physical_inventory import (
    AssemblyError,
    assemble_artifacts,
    canonical_state_id,
)
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
    assert combined["input_artifact_sha256s"] == sorted(
        [route["content_sha256"], eia["content_sha256"]]
    )
    assert {item["asset_id"] for item in combined["assets"]} == {
        "hifld:line:1",
        "eia860:plant:1",
    }
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


def test_keeps_each_component_coverage_count_instead_of_a_statewide_sum() -> None:
    west = _component("hifld:line:west", "tx:west")
    east = _component("hifld:line:east", "tx:east")
    combined = assemble_artifacts([west, east], release_version="1.1.0")
    generation = [
        row for row in combined["coverage"] if row["asset_class"] == "generation"
    ]
    assert {row["scope_id"] for row in generation} == {"tx:west", "tx:east"}
    assert [row["observed_count"] for row in generation] == [1, 1]
    assert all(row["denominator_count"] is None for row in generation)
    assert all(row["status"] == "partial" for row in generation)


def test_rejects_two_components_disagreeing_about_the_same_class_and_scope() -> None:
    first = _component("a", "tx:shared")
    second = _component("b", "tx:shared")
    second["coverage"][0]["reason"] = "A different account of the same class and scope."
    second["content_sha256"] = artifact_sha256(second)
    with pytest.raises(AssemblyError, match="conflicting coverage class/scope"):
        assemble_artifacts([first, second], release_version="1.1.0")


def test_rejects_inputs_from_two_states() -> None:
    texas = _component("a", "tx:a", "us-tx")
    minnesota = _component("b", "mn:b", "us-mn")
    with pytest.raises(AssemblyError, match="do not resolve to one state"):
        assemble_artifacts([texas, minnesota], release_version="1.1.0")


def test_rejects_inputs_that_do_not_share_inventory_and_model_modes() -> None:
    observed = _component("a", "tx:a")
    fixture = _component("b", "tx:b")
    fixture["inventory_mode"] = "fixture"
    fixture["content_sha256"] = artifact_sha256(fixture)
    with pytest.raises(AssemblyError, match="share inventory and electrical model"):
        assemble_artifacts([observed, fixture], release_version="1.1.0")
    modelled = _component("c", "tx:c")
    modelled["electrical_model_mode"] = "source_backed"
    modelled["content_sha256"] = artifact_sha256(modelled)
    with pytest.raises(AssemblyError, match="share inventory and electrical model"):
        assemble_artifacts([observed, modelled], release_version="1.1.0")


def test_refuses_an_unrecognised_producer_geography_instead_of_guessing_a_state() -> (
    None
):
    stray = _component("a", "tx:a", "texas")
    assert canonical_state_id("us-tx") == "tx"
    assert canonical_state_id("mn:mille-lacs-county") == "mn"
    with pytest.raises(AssemblyError, match="texas"):
        canonical_state_id("texas")
    with pytest.raises(AssemblyError, match="do not resolve|texas"):
        assemble_artifacts([stray], release_version="1.1.0")
