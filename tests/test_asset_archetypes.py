from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import re
import subprocess
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
    validate_published_runtime,
)


def _catalog() -> dict:
    return json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))


def _repo_root() -> Path:
    return Path(DEFAULT_CATALOG).resolve().parents[2]


def _tracked_model_files() -> list[str]:
    """Model binaries git actually tracks — the honest packaging boundary."""
    root = _repo_root()
    if not (root / ".git").exists():
        pytest.skip("not a git checkout; the committed-binary boundary is unmeasurable")
    result = subprocess.run(
        ["git", "ls-files", "--", "*.glb", "*.gltf"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def _expected_runtime_model_files(catalog: dict) -> list[str]:
    """Derive the complete checked-in Flux grid pack from catalog identities."""
    return sorted(
        f"web/public/assets/flux-grid/{archetype_id}/{archetype_id}{lod_suffix}.glb"
        for archetype_id in (entry["id"] for entry in catalog["archetypes"])
        for lod_suffix in ("", ".lod1", ".lod2")
    )


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
    # Runtime binaries are permitted only as the verified published pack. The
    # source catalog itself still never authorizes a GLB in data/ or elsewhere
    # in the web tree; the release receipt and immutable per-file inventory do.
    assert validate_published_runtime(_repo_root(), catalog) == []
    assert _tracked_model_files() == sorted(
        path for path in find_model_files() if path.endswith(".glb")
    )
    assert report["modelFiles"] == find_model_files()
    assert report["modelFilesPresent"] == bool(report["modelFiles"])


def _write_verified_runtime_fixture(
    root: Path, catalog: dict, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, bytes]]:
    """Make a complete tiny runtime tree with the same receipt boundary as production."""
    catalog_path = root / "data/3d/asset-archetypes-v1.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, sort_keys=True), encoding="utf-8")
    files: list[tuple[str, bytes]] = []
    for archetype in catalog["archetypes"]:
        asset_id = archetype["id"]
        for suffix in (".glb", ".lod1.glb", ".lod2.glb"):
            relative = f"{asset_id}/{asset_id}{suffix}"
            contents = f"glTF:{relative}".encode()
            target = root / "web/public/assets/flux-grid" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
            files.append((relative, contents))
    receipt = {
        **validator.PUBLISHED_RUNTIME_RELEASE,
        "publication_status": "published_external_attachment_verified",
        "source_contract": {
            "file": "data/3d/asset-archetypes-v1.json",
            "sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        },
    }
    receipt_path = root / validator.PUBLISHED_RELEASE_RECEIPT
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    manifest = root / "web/public/assets/flux-grid/manifest.json"
    manifest.write_text('{"fixture": true}', encoding="utf-8")
    monkeypatch.setitem(
        validator.PUBLISHED_RUNTIME_RELEASE,
        "runtime_manifest_sha256",
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )
    receipt["runtime_manifest_sha256"] = validator.PUBLISHED_RUNTIME_RELEASE[
        "runtime_manifest_sha256"
    ]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    inventory = {
        "schema_version": 1,
        "release_tag": validator.PUBLISHED_RUNTIME_RELEASE["release_tag"],
        "archive_sha256": validator.PUBLISHED_RUNTIME_RELEASE["archive_sha256"],
        "runtime_manifest_sha256": validator.PUBLISHED_RUNTIME_RELEASE[
            "runtime_manifest_sha256"
        ],
        "files": [
            {
                "path": relative,
                "sha256": hashlib.sha256(contents).hexdigest(),
                "bytes": len(contents),
            }
            for relative, contents in files
        ],
    }
    inventory_path = root / validator.PUBLISHED_RUNTIME_INVENTORY
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    return files


def test_published_runtime_is_the_only_pinned_model_binary_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    catalog = _catalog()
    files = _write_verified_runtime_fixture(tmp_path, catalog, monkeypatch)

    assert validate_published_runtime(tmp_path, catalog) == []

    # A changed runtime binary has no authority merely because it shares the
    # approved path; its digest and byte count must still be release-pinned.
    runtime = tmp_path / "web/public/assets/flux-grid" / files[0][0]
    runtime.write_bytes(b"tampered")
    assert any(
        "digest does not match inventory" in error
        for error in validate_published_runtime(tmp_path, catalog)
    )

    # A source-side or arbitrary web binary is never covered by the published
    # runtime inventory, even when the intended release is otherwise valid.
    runtime.write_bytes(files[0][1])
    stray = tmp_path / "data/3d/unverified.glb"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"glTF")
    assert any(
        "outside published runtime location" in error
        for error in validate_published_runtime(tmp_path, catalog)
    )

    # An added binary under the otherwise authorized runtime root is still not
    # allowed: the inventory is an exact 54-file set, not a directory permit.
    stray.unlink()
    extra = tmp_path / "web/public/assets/flux-grid/hospital/extra.glb"
    extra.write_bytes(b"glTF")
    assert any(
        "outside published runtime location" in error
        for error in validate_published_runtime(tmp_path, catalog)
    )


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


def _message_chunks(node: ast.AST) -> list[str] | None:
    """The literal text of an error message, split at its interpolations.

    ``f"{label}: lod1 must be <= {share} of lod0"`` yields
    ``["", ": lod1 must be <= ", " of lod0"]``. None means the message is not a
    literal at all, which the rule inventory refuses to guess at.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        chunks = [""]
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                chunks[-1] += part.value
            else:
                chunks.append("")
        return chunks
    return None


def _validator_rule_sites() -> list[tuple[int, list[str]]]:
    """Every place validate_catalog records a violation, as (line, chunks).

    Counted forms: ``errors.append(msg)``, ``errors.extend([...])`` and
    ``errors += [...]``. A rule written in any of them is a rule; matching only
    ``.append`` let a new rule hide from the inventory entirely.
    """
    tree = ast.parse(inspect.getsource(validator))
    (function,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "validate_catalog"
    ]

    sites: list[tuple[int, list[str]]] = []
    unreadable: list[int] = []

    def record(node: ast.AST) -> None:
        chunks = _message_chunks(node)
        if chunks is None:
            unreadable.append(getattr(node, "lineno", -1))
        else:
            sites.append((node.lineno, chunks))

    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"append", "extend"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "errors"
        ):
            if node.func.attr == "append":
                for arg in node.args:
                    record(arg)
            else:
                for arg in node.args:
                    if isinstance(arg, (ast.List, ast.Tuple, ast.Set)):
                        for element in arg.elts:
                            record(element)
                    else:
                        unreadable.append(node.lineno)
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "errors"
        ):
            if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                for element in node.value.elts:
                    record(element)
            else:
                unreadable.append(node.lineno)

    assert not unreadable, (
        f"validate_catalog records a violation with a non-literal message at "
        f"lines {sorted(unreadable)}; the rule inventory cannot pair it with a "
        "negative case"
    )
    return sorted(sites)


def _fragment_can_come_from(expected: str, chunks: list[str]) -> bool:
    """Could `expected` appear in a message built from these literal chunks?

    Either it sits inside one literal run, or it spans an interpolation — in
    which case it must still be anchored on real literal text at both ends, so
    a message ending in `{value}` cannot absorb an arbitrary tail.
    """
    if any(expected in chunk for chunk in chunks):
        return True

    def alternatives(options: list[str]) -> str:
        return "(?:" + "|".join(re.escape(option) for option in options) + ")"

    for i in range(len(chunks)):
        suffixes = [chunks[i][k:] for k in range(len(chunks[i]))]
        if not suffixes:
            continue
        for j in range(i + 1, len(chunks)):
            prefixes = [chunks[j][:k] for k in range(len(chunks[j]), 0, -1)]
            if not prefixes:
                continue
            middle = "".join(f"(?s:.*){re.escape(c)}" for c in chunks[i + 1 : j])
            pattern = (
                alternatives(suffixes) + middle + "(?s:.*)" + alternatives(prefixes)
            )
            if re.fullmatch(pattern, expected):
                return True
    return False


def test_every_validator_rule_has_exactly_one_negative_case():
    """RULE_CASES and the validator's rules are a bijection, not a count.

    A count is bypassable two ways, and both were: a new rule plus a duplicated
    RULE_CASES row satisfied it, and a rule written `errors += [...]` was not
    counted at all. So: every `expected` is distinct, every `expected` matches
    exactly one rule site, and every rule site is claimed by exactly one case.
    """
    sites = _validator_rule_sites()

    expectations = [expected for _, _, expected in RULE_CASES]
    assert len(set(expectations)) == len(expectations), (
        "RULE_CASES expectations must be distinct; a duplicated row lets a new "
        "validator rule ride in on another rule's coverage"
    )

    claimed: dict[int, str] = {}
    for rule_id, _, expected in RULE_CASES:
        matches = [
            line for line, chunks in sites if _fragment_can_come_from(expected, chunks)
        ]
        assert len(matches) == 1, (
            f"case {rule_id!r} expects {expected!r}, which matches "
            f"{len(matches)} validator rules (lines {matches}); a negative case "
            "must pin exactly one rule"
        )
        line = matches[0]
        assert line not in claimed, (
            f"cases {claimed[line]!r} and {rule_id!r} both pin the rule at line "
            f"{line}; one validator rule then has no case of its own"
        )
        claimed[line] = rule_id

    uncovered = sorted(line for line, _ in sites if line not in claimed)
    assert not uncovered, (
        f"validator rules at lines {uncovered} have no RULE_CASES row: they can "
        "be deleted without a test noticing"
    )
    assert len(sites) == len(RULE_CASES)


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
    root = _repo_root()
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

    # The catalog is one of the two places that states this; the design doc is
    # the other, and it drifts back just as easily. Pin the same facts there,
    # against the same lockfile, so the claim cannot be true in one place only.
    doc = (root / "docs/design/3d-asset-contract.md").read_text(encoding="utf-8")
    container_rows = [
        line for line in doc.splitlines() if line.startswith("| Container |")
    ]
    assert len(container_rows) == 1, (
        f"expected one Container row in the runtime-invariants table, found "
        f"{len(container_rows)}"
    )
    container = container_rows[0]

    assert "@deck.gl/mesh-layers" in container and "@loaders.gl/gltf" in container
    assert "three.js is **not** a current dependency" in container, (
        "docs/design/3d-asset-contract.md must say what the lockfile says: "
        f"three.js is absent, so the Container row may not imply otherwise: "
        f"{container}"
    )
