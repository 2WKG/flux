from __future__ import annotations

import ast
import copy
import inspect
import json
from collections.abc import Callable
from pathlib import Path

import pytest

import scripts.validate_asset_archetypes as validator
from scripts.validate_asset_archetypes import (
    ALLOWED_LABELS,
    DEFAULT_CATALOG,
    EXPECTED_ARCHETYPES,
    build_report,
    find_model_files,
    validate_catalog,
)


def _catalog() -> dict:
    return json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))


def test_committed_catalog_conforms_and_covers_every_asset_work_item():
    catalog = _catalog()

    report = build_report(catalog)

    assert report["validation"] == {"passed": True, "errors": []}
    assert report["archetypeCount"] == EXPECTED_ARCHETYPES
    # One Texas and one Minnesota work item per archetype, none claimed twice.
    texas = [entry["texas_issue"] for entry in catalog["archetypes"]]
    minnesota = [entry["minnesota_issue"] for entry in catalog["archetypes"]]
    assert len(set(texas)) == len(set(minnesota)) == EXPECTED_ARCHETYPES
    assert set(texas).isdisjoint(minnesota)
    # No binary is committed; the contract governs shape, not hosting. Both
    # sides of this are derived from the tree, not declared: find_model_files
    # walks data/ and web/ recursively, so a model in data/3d/models/ or
    # web/public/ turns modelFilesPresent true and turns this red.
    assert find_model_files() == []
    assert report["modelFilesPresent"] is False
    assert report["modelFiles"] == []


def test_import_invariants_are_pinned_not_merely_described():
    catalog = _catalog()
    transform = catalog["transform"]

    assert transform["lengthUnit"] == "meter" and transform["unitScale"] == 1.0
    assert transform["upAxis"] == "Y" and transform["forwardAxis"] == "-Z"
    assert transform["pivot"] == "ground_center"
    for field, value in (
        ("lengthUnit", "centimeter"),
        ("upAxis", "Z"),
        ("pivot", "bounding_box_center"),
    ):
        drifted = copy.deepcopy(catalog)
        drifted["transform"][field] = value
        assert validate_catalog(drifted), f"{field}={value} must be rejected"


def test_status_materials_bind_only_labels_the_server_asserts():
    catalog = _catalog()

    assert set(catalog["statusMaterials"]["allowedLabels"]) == ALLOWED_LABELS
    # "illustrative" was deliberately removed from the narrative-IA contract: no
    # server field asserts it, so a model may not carry it either.
    invented = copy.deepcopy(catalog)
    invented["statusMaterials"]["allowedLabels"].append("illustrative")

    assert any("server-asserted" in error for error in validate_catalog(invented))


def test_lod_chain_must_actually_reduce_and_respect_the_budget():
    catalog = _catalog()

    flat = copy.deepcopy(catalog)
    flat["archetypes"][0]["lod_triangles"]["lod1"] = flat["archetypes"][0][
        "lod_triangles"
    ]["lod0"]
    assert any("lod1" in error for error in validate_catalog(flat))

    over = copy.deepcopy(catalog)
    over["archetypes"][0]["lod_triangles"]["lod0"] = (
        catalog["budgets"]["perArchetypeTrianglesLod0"] + 1
    )
    assert any("exceeds budget" in error for error in validate_catalog(over))


def test_connector_roles_and_limits_are_constrained():
    catalog = _catalog()

    unknown = copy.deepcopy(catalog)
    unknown["archetypes"][0]["connectors"] = ["HV_MAGIC"]
    assert any("unknown connector" in error for error in validate_catalog(unknown))

    mixed = copy.deepcopy(catalog)
    mixed["archetypes"][0]["connectors"] = ["NONE", "HV_IN"]
    assert any("NONE cannot be combined" in error for error in validate_catalog(mixed))

    # Every archetype must say what it does not assert.
    assert all(entry["limit"].strip() for entry in catalog["archetypes"])
    silent = copy.deepcopy(catalog)
    silent["archetypes"][0]["limit"] = "   "
    assert any("limit must state" in error for error in validate_catalog(silent))


def test_duplicate_identity_is_rejected():
    catalog = _catalog()
    duplicated = copy.deepcopy(catalog)
    duplicated["archetypes"][1]["id"] = duplicated["archetypes"][0]["id"]
    duplicated["archetypes"][1]["texas_issue"] = duplicated["archetypes"][0][
        "texas_issue"
    ]

    errors = validate_catalog(duplicated)

    assert any("duplicate archetype id" in error for error in errors)
    assert any("claimed twice" in error for error in errors)


@pytest.mark.parametrize("count", [EXPECTED_ARCHETYPES - 1, EXPECTED_ARCHETYPES + 1])
def test_catalog_must_hold_exactly_the_eighteen_assets(count: int):
    catalog = _catalog()
    resized = copy.deepcopy(catalog)
    entries = resized["archetypes"]
    resized["archetypes"] = (
        entries[:count] if count < len(entries) else entries + [entries[0]]
    )

    assert any("exactly 18 archetypes" in error for error in validate_catalog(resized))


# --- Per-rule negative coverage -------------------------------------------
#
# One case per `errors.append` in validate_catalog. Each mutates a copy of the
# committed catalog to violate exactly one rule and asserts the validator names
# THAT rule, so deleting the rule turns its own case red. This is what
# test_committed_catalog_conforms_... cannot do: a whole-catalog "passed: True"
# assertion goes red for any mutation, so it cannot distinguish "the rule fired"
# from "the catalog moved".


def _set_entry(field: str, value: object, index: int = 0) -> Callable[[dict], None]:
    def mutate(catalog: dict) -> None:
        catalog["archetypes"][index][field] = value

    return mutate


def _copy_from_first(field: str, index: int = 1) -> Callable[[dict], None]:
    def mutate(catalog: dict) -> None:
        catalog["archetypes"][index][field] = catalog["archetypes"][0][field]

    return mutate


RULE_CASES: list[tuple[str, Callable[[dict], None], str]] = [
    # Rules the original suite already covered, restated per-rule.
    (
        "transform-unit",
        lambda c: c["transform"].__setitem__("lengthUnit", "centimeter"),
        "transform must declare metres",
    ),
    (
        "transform-axes",
        lambda c: c["transform"].__setitem__("upAxis", "Z"),
        "must declare Y up and -Z forward",
    ),
    (
        "transform-pivot",
        lambda c: c["transform"].__setitem__("pivot", "bounding_box_center"),
        "pivot must be ground_center",
    ),
    (
        "status-label-allow-set",
        lambda c: c["statusMaterials"]["allowedLabels"].append("illustrative"),
        "server-asserted labels",
    ),
    (
        "archetype-count",
        lambda c: c["archetypes"].pop(),
        f"exactly {EXPECTED_ARCHETYPES} archetypes",
    ),
    ("duplicate-archetype-id", _copy_from_first("id"), "duplicate archetype id"),
    ("issue-claimed-twice", _copy_from_first("texas_issue"), "is claimed twice"),
    (
        "unknown-connector-role",
        _set_entry("connectors", ["HV_MAGIC"]),
        "unknown connector role",
    ),
    (
        "none-mixed-with-real-connector",
        _set_entry("connectors", ["NONE", "HV_IN"]),
        "NONE cannot be combined",
    ),
    (
        "lod0-over-budget",
        lambda c: c["archetypes"][0]["lod_triangles"].__setitem__(
            "lod0", c["budgets"]["perArchetypeTrianglesLod0"] + 1
        ),
        "exceeds budget",
    ),
    (
        "lod1-share",
        lambda c: c["archetypes"][0]["lod_triangles"].__setitem__(
            "lod1", c["archetypes"][0]["lod_triangles"]["lod0"]
        ),
        "lod1 must be <=",
    ),
    ("limit-non-empty", _set_entry("limit", "   "), "limit must state"),
    # Rules that had no negative case: each of these could be deleted from the
    # validator with the suite staying green before this file changed.
    (
        "catalog-identity",
        lambda c: c.__setitem__("contractId", "flux:3d-asset-archetypes:v2"),
        "catalog identity must be",
    ),
    (
        "material-slot-name",
        lambda c: c["statusMaterials"].__setitem__("slotName", ""),
        "shared material slot",
    ),
    (
        "budgets-positive-int",
        lambda c: c["budgets"].__setitem__("perArchetypeFileBytes", -1),
        "budgets.perArchetypeFileBytes must be a positive integer",
    ),
    (
        "archetype-field-set",
        lambda c: c["archetypes"][0].pop("limit"),
        "fields must be exactly",
    ),
    (
        "duplicate-semantic-name",
        _copy_from_first("semantic_name"),
        "duplicate semantic name",
    ),
    (
        "category-allow-set",
        _set_entry("category", "make_believe"),
        "category must be one of",
    ),
    (
        "issue-key-format",
        _set_entry("texas_issue", "LINEAR-1"),
        "must be a 2WKG-NNN key",
    ),
    (
        "footprint-positive",
        lambda c: c["archetypes"][0]["footprint_m"].__setitem__("width", 0),
        "footprint_m needs positive length and width",
    ),
    (
        "connectors-non-empty",
        _set_entry("connectors", []),
        "connectors must be a non-empty list",
    ),
    (
        "duplicate-connector-role",
        _set_entry("connectors", ["HV_IN", "HV_IN"]),
        "duplicate connector role",
    ),
    (
        "lod-shape-positive",
        lambda c: c["archetypes"][0]["lod_triangles"].__setitem__("lod2", 0),
        "lod_triangles needs positive lod0, lod1, lod2",
    ),
    (
        "lod2-share",
        lambda c: c["archetypes"][0]["lod_triangles"].__setitem__(
            "lod2", c["archetypes"][0]["lod_triangles"]["lod0"]
        ),
        "lod2 must be <=",
    ),
]


@pytest.mark.parametrize(
    ("rule_id", "mutate", "expected"),
    RULE_CASES,
    ids=[case[0] for case in RULE_CASES],
)
def test_each_validator_rule_rejects_its_own_violation(
    rule_id: str, mutate: Callable[[dict], None], expected: str
):
    mutated = copy.deepcopy(_catalog())

    mutate(mutated)
    errors = validate_catalog(mutated)

    assert any(expected in error for error in errors), (
        f"rule {rule_id!r} did not fire; validator said: {errors}"
    )


def test_every_validator_rule_has_a_negative_case():
    """A rule added without a RULE_CASES row turns this red.

    Counts `errors.append(...)` sites in validate_catalog. Before this change
    the validator had 24 rules and 12 of them could be deleted outright with
    the suite staying green.
    """
    tree = ast.parse(inspect.getsource(validator))
    (function,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "validate_catalog"
    ]
    appends = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "append"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "errors"
    ]

    assert len(appends) == len(RULE_CASES), (
        f"{len(appends)} validator rules but {len(RULE_CASES)} negative cases: "
        "every rule needs one, or it can be deleted without a test noticing"
    )


# --- Derived model-file reporting -----------------------------------------


def _write_tree(root: Path, *relative_paths: str) -> None:
    for relative in relative_paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"glTF\x02\x00\x00\x00")


def test_model_files_present_is_derived_from_the_tree(tmp_path: Path):
    catalog = _catalog()

    (tmp_path / "data/3d").mkdir(parents=True)
    assert find_model_files(tmp_path) == []
    assert build_report(catalog, tmp_path)["modelFilesPresent"] is False

    _write_tree(tmp_path, "data/3d/models/hospital.glb", "web/public/tower.gltf")
    report = build_report(catalog, tmp_path)

    assert find_model_files(tmp_path) == [
        "data/3d/models/hospital.glb",
        "web/public/tower.gltf",
    ]
    assert report["modelFilesPresent"] is True
    assert report["modelFiles"] == [
        "data/3d/models/hospital.glb",
        "web/public/tower.gltf",
    ]


def test_model_file_scan_ignores_vendored_and_built_trees(tmp_path: Path):
    _write_tree(
        tmp_path,
        "web/node_modules/some-pkg/duck.glb",
        "web/dist/bundle.glb",
        "data/3d/real.glb",
    )

    assert find_model_files(tmp_path) == ["data/3d/real.glb"]


# --- Dependency claims are checked against the lockfile --------------------


def test_runtime_container_claim_matches_the_web_lockfile():
    """The catalog's runtime.reason is an assertion about the browser bundle.

    deck.gl's glTF loaders really are present transitively; three.js is not a
    dependency at all. A contract file may not assert a dependency posture the
    lockfile contradicts.
    """
    catalog = _catalog()
    root = Path(DEFAULT_CATALOG).resolve().parents[2]
    manifest = (root / "web/package.json").read_text(encoding="utf-8")
    lockfile = (root / "web/package-lock.json").read_text(encoding="utf-8")
    reason = catalog["runtime"]["reason"]

    assert '"node_modules/@deck.gl/mesh-layers"' in lockfile
    assert '"node_modules/@loaders.gl/gltf"' in lockfile
    assert "@deck.gl/mesh-layers" in reason and "@loaders.gl/gltf" in reason

    three_is_a_dependency = '"node_modules/three"' in lockfile or '"three":' in manifest
    assert not three_is_a_dependency, (
        "three.js is now a dependency; update runtime.reason"
    )
    assert "new dependency" in reason, (
        "runtime.reason must not present three.js as already permitted"
    )
