from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.asset_contract_lib import ROOT, load_catalog
from scripts.render_natural_gas_power_plant_preview import SIZE, render
from scripts.validate_natural_gas_power_plant_asset import (
    ARCHETYPE_ID,
    CATALOG_PATH,
    META_PATH,
    main,
    validate,
)


def _meta() -> dict:
    return json.loads(META_PATH.read_text())


def _catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text())


def _entry(catalog: dict) -> dict:
    return next(item for item in catalog["archetypes"] if item["id"] == ARCHETYPE_ID)


def test_committed_metadata_matches_the_shared_archetype():
    assert validate(_meta(), _catalog()) == []


def test_the_meta_file_is_named_after_the_archetype_id():
    assert META_PATH.name == f"{ARCHETYPE_ID}.meta.json"
    assert _meta()["archetype_id"] == ARCHETYPE_ID


def test_triangle_counts_are_declared_unmeasured_rather_than_fabricated():
    meta = _meta()
    assert meta["triangles_lod0"] is None
    assert meta["triangles_lod1"] is None
    assert meta["triangles_lod2"] is None
    assert meta["lod_triangle_budget"] == _entry(_catalog())["lod_triangles"]
    assert "not measured" in meta["lod_measurement_status"]


def test_an_honest_under_budget_mesh_is_accepted():
    """The budget rule must not reject a real mesh merely for being smaller."""
    meta = _meta()
    meta["triangles_lod0"] = 20000
    meta["triangles_lod1"] = 7000
    meta["triangles_lod2"] = 2000
    assert validate(meta, _catalog()) == []


def test_preview_renderer_creates_the_contract_png(tmp_path: Path):
    preview = tmp_path / f"{ARCHETYPE_ID}.preview.png"
    render(preview)
    payload = preview.read_bytes()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert int.from_bytes(payload[16:20], "big") == 512
    assert int.from_bytes(payload[20:24], "big") == 512


def test_the_preview_size_is_the_one_the_contract_and_meta_declare():
    catalog = load_catalog()
    assert SIZE == 512
    assert (
        SIZE == catalog["deliverables"]["previewPixels"] == _meta()["preview_size_px"]
    )


def test_the_preview_render_is_byte_identical_across_runs(tmp_path: Path):
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    render(first)
    render(second)
    assert first.read_bytes() == second.read_bytes()


def _set(path: list[str], value):
    def mutate(meta, _catalog):
        target = meta
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _delete(path: list[str]):
    def mutate(meta, _catalog):
        target = meta
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]

    return mutate


def _catalog_budget(key: str, value):
    def mutate(_meta, catalog):
        catalog["budgets"][key] = value

    return mutate


def _coordinated_lod_drift(meta, catalog):
    """Both documents move together, 25% over the contract ceiling."""
    over = catalog["budgets"]["perArchetypeTrianglesLod0"] + 10000
    drifted = {"lod0": over, "lod1": int(over * 0.3), "lod2": int(over * 0.1)}
    _entry(catalog)["lod_triangles"] = drifted
    meta["lod_triangle_budget"] = drifted


def _unreduced_lod_chain(meta, _catalog):
    """A measured chain whose lod1 does not actually reduce."""
    meta["triangles_lod0"] = 10000
    meta["triangles_lod1"] = 9000


def _drop_archetype(_meta, catalog):
    catalog["archetypes"] = [
        item for item in catalog["archetypes"] if item["id"] != ARCHETYPE_ID
    ]


MUTATIONS = [
    (_set(["archetype_id"], "bogus_id"), "archetype_id does not match"),
    (_set(["contract_id"], "flux:bogus:v9"), "contract_id does not match"),
    (_set(["semantic_name"], "Something else"), "semantic_name does not match"),
    (_set(["category"], "not_a_category"), "category does not match"),
    (
        _set(["footprint_m"], {"length": 999, "width": 999}),
        "footprint_m does not match",
    ),
    (_set(["connectors"], ["HV_IN"]), "connectors does not match"),
    (_set(["connectors"], ["HV_MAGIC"]), "is not in the shared vocabulary"),
    (
        _set(["lod_triangle_budget"], {"lod0": 1, "lod1": 1, "lod2": 1}),
        "lod_triangle_budget does not match",
    ),
    (_coordinated_lod_drift, "exceeds the contract ceiling"),
    (_catalog_budget("perArchetypeTrianglesLod0", 100), "exceeds the contract ceiling"),
    (_set(["triangles_lod0"], 999999), "triangles.lod0"),
    (_unreduced_lod_chain, "triangles.lod1"),
    (_delete(["author"]), "missing the contract field author"),
    (_set(["transform", "pivot"], "bounding_box_center"), "transform must match"),
    (_delete(["transform"]), "transform must match"),
    (_set(["container"], "obj"), "container must be the catalog runtime container"),
    (_set(["model_filename"], "other_asset.glb"), "model_filename must be"),
    (_set(["preview_filename"], "other_asset.preview.png"), "preview_filename must be"),
    (_set(["preview_size_px"], 256), "preview_size_px must be"),
    (
        _set(["material_slots", 0, "default"], "retired_red"),
        "neutral status slot",
    ),
    (_set(["license"], "   "), "license and source_of_shape are required"),
    (_set(["source_of_shape"], ""), "license and source_of_shape are required"),
    (_set(["catalog_limit"], "no caveat"), "catalog_limit must repeat"),
    (_delete(["catalog_limit"]), "catalog_limit must repeat"),
    (_set(["minnesota_issue"], "2WKG-000"), "minnesota_issue must match"),
    (
        _set(["minnesota_context", "render_mode"], "placed"),
        "render_mode must remain catalog_preview",
    ),
    (
        _set(["minnesota_context", "truth_label"], "illustrative"),
        "is not in statusMaterials.allowedLabels",
    ),
    (
        _set(
            ["minnesota_context", "disclosure"],
            "Illustrative catalogue preview — not Minnesota infrastructure yet.",
        ),
        "a label the catalog retires",
    ),
    (
        _set(["minnesota_context", "disclosure"], "This IS a real Minnesota plant."),
        "must state the asset is not Minnesota infrastructure",
    ),
    (_set(["minnesota_context", "disclosure"], "  "), "disclosure must state"),
    (_delete(["minnesota_context"]), "minnesota_context must be an object"),
    (_delete(["export_recipe"]), "export_recipe must be an object"),
    (
        _set(["export_recipe", "preview_renderer"], "scripts/does_not_exist.py"),
        "is not a file in this repository",
    ),
    (
        _set(["export_recipe", "model_producer"], "scripts/does_not_exist.py"),
        "is not a file in this repository",
    ),
    (_delete(["export_recipe", "model_producer"]), "must state model_producer"),
    (_set(["export_recipe", "required_outputs"], []), "required_outputs must be"),
    (_set(["export_recipe", "binary_policy"], " "), "binary_policy must state"),
    (_drop_archetype, "is missing from the shared catalog"),
]


@pytest.mark.parametrize(
    ("mutate", "expected"), MUTATIONS, ids=[expected for _m, expected in MUTATIONS]
)
def test_every_rule_reports_its_own_violation(mutate, expected):
    meta, catalog = _meta(), _catalog()
    assert validate(meta, catalog) == []
    mutate(meta, catalog)
    errors = validate(meta, catalog)
    assert any(expected in error for error in errors), errors


def test_a_non_object_metadata_is_reported_not_traced():
    assert validate(None, _catalog()) == ["metadata is not a JSON object"]


def test_a_malformed_catalog_is_reported_not_traced():
    assert validate(_meta(), {"contractId": "x"}) != []
    assert validate(_meta(), {"archetypes": [], "contractId": "x"}) == [
        f"{ARCHETYPE_ID} is missing from the shared catalog"
    ]


def test_main_exit_codes_distinguish_pass_fail_and_unreadable(tmp_path: Path, capsys):
    assert main([]) == 0
    assert "matches" in capsys.readouterr().out

    broken = tmp_path / "meta.json"
    document = _meta()
    document["license"] = ""
    broken.write_text(json.dumps(document), encoding="utf-8")
    assert main(["--meta", str(broken)]) == 1
    assert "license and source_of_shape" in capsys.readouterr().out

    assert main(["--meta", str(tmp_path / "absent.json")]) == 2
    assert "could not be read" in capsys.readouterr().err

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert main(["--meta", str(malformed)]) == 2


def test_the_committed_meta_lives_where_the_contract_says(tmp_path: Path):
    assert META_PATH.is_file()
    assert META_PATH.parent == ROOT / "data/3d/assets"
    assert not list((ROOT / "data/3d").rglob("*.glb"))
    assert copy.deepcopy(_meta())["export_recipe"]["model_producer"] is None
