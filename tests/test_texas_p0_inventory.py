from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "validate_texas_p0_inventory.py"
INVENTORY_PATH = REPO_ROOT / "data" / "sources" / "texas-p0-inventory.json"
CATALOG_PATH = REPO_ROOT / "datasets" / "catalog.json"
SPEC = importlib.util.spec_from_file_location("texas_p0_inventory", MODULE_PATH)
assert SPEC and SPEC.loader
inventory_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory_module)

ACTIVSG_INDEX = 0
TIGER_INDEX = 1
HRRR_INDEX = 5
EAGLEI_INDEX = 6


def _inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _record(inventory: dict, identifier: str) -> dict:
    return next(record for record in inventory["records"] if record["id"] == identifier)


def test_checked_in_texas_p0_inventory_validates_and_labels_public_scope(
    tmp_path: Path,
) -> None:
    report = inventory_module.build_report(_inventory(), tmp_path / "missing-raw")

    assert report["validation"] == {"passed": True, "errors": []}
    assert report["summary"] == {
        "excluded": 1,
        "ingested": 0,
        "unavailable": 0,
        "validated": 10,
    }
    assert "synthetic" in report["synthetic_geometry_caveat"].lower()
    assert "not the real ercot" in report["synthetic_geometry_caveat"].lower()
    # POSIX separators on every platform: the ledger is a published artifact, so a
    # Windows-authored run must produce the same bytes as a Linux one.
    assert report["records"][ACTIVSG_INDEX]["checked_in_receipt"] == {
        "path": "data/sources/activsg2000.json",
        "passed": True,
        "mismatches": [],
    }
    for identifier in (
        "census-tiger-2024-counties",
        "fema-nri-v1.20",
        "pudl-eia860-v2026.2.0",
    ):
        record = _record(_inventory(), identifier)
        assert record["status"] == "validated"
        assert record["checked_in_receipt"]
        assert all(
            artifact["immutable_id"] is None
            or artifact["immutable_id"].startswith("sha256:")
            for artifact in record["artifacts"]
        )
    assert report["requested_raw_root"] == (tmp_path / "missing-raw").as_posix()
    assert all(record["schema_valid"] for record in report["records"])
    assert all(
        record["license_access"]["access"] == "public" for record in report["records"]
    )
    assert all(
        not artifact["present_in_requested_raw_root"]
        for record in report["records"]
        for artifact in record["artifacts"]
    )


def test_inventory_covers_every_p0_raw_input_the_builder_accepts() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    raw_paths = {
        artifact["raw_path"]
        for record in _inventory()["records"]
        for artifact in record["artifacts"]
        if artifact.get("raw_path")
    }
    for entry in catalog["p0_raw_inputs"]:
        alternatives = ["/".join(parts) for parts in entry["paths"]]
        assert any(path in raw_paths for path in alternatives), entry["label"]
    # The builder's first-choice NRI input is declared, not only the 403 legacy ZIP.
    assert "nri/v1.20/NRI_Counties_TX.json" in raw_paths


def test_inventory_rejects_unexplained_or_nonpublic_records() -> None:
    inventory = copy.deepcopy(_inventory())
    inventory["records"][ACTIVSG_INDEX]["reason"] = ""
    inventory["records"][TIGER_INDEX]["license_access"]["access"] = "restricted"

    errors = inventory_module.validate_inventory(inventory)

    assert any("reason" in error for error in errors)
    assert any("public-only" in error for error in errors)


def _flip_status(inventory: dict, index: int, status: str) -> None:
    inventory["records"][index]["status"] = status


def _drop_receipt(inventory: dict, index: int, status: str) -> None:
    del inventory["records"][index]["checked_in_receipt"]


def _timestamp_on_unavailable(inventory: dict, index: int, status: str) -> None:
    inventory["records"][index]["ingestion_timestamp"] = "2026-09-05T00:00:00+00:00"


def _receipt_on_unavailable(inventory: dict, index: int, status: str) -> None:
    inventory["records"][index]["checked_in_receipt"] = "data/sources/activsg2000.json"


def _duplicate_id(inventory: dict, index: int, status: str) -> None:
    inventory["records"][index]["id"] = inventory["records"][ACTIVSG_INDEX]["id"]


def _http_url(inventory: dict, index: int, status: str) -> None:
    inventory["records"][index]["source_url"] = "http://example.com/data.zip"


def _drop_immutable_ids(inventory: dict, index: int, status: str) -> None:
    for artifact in inventory["records"][index]["artifacts"]:
        artifact["immutable_id"] = None


def _weaken_caveat(inventory: dict, index: int, status: str) -> None:
    inventory["synthetic_geometry_caveat"] = "ACTIVSg2000 is a Texas network."


@pytest.mark.parametrize(
    ("mutate", "index", "status", "expected_error"),
    [
        # A receipt-less source cannot claim evidence just by changing one word.
        (
            _flip_status,
            HRRR_INDEX,
            "ingested",
            "ingested record needs a checked_in_receipt path",
        ),
        (
            _flip_status,
            HRRR_INDEX,
            "ingested",
            "ingested record needs an ingestion_timestamp",
        ),
        (
            _drop_receipt,
            EAGLEI_INDEX,
            "validated",
            "validated record needs a checked_in_receipt path",
        ),
        (
            _flip_status,
            HRRR_INDEX,
            "validated",
            "validated record needs an immutable artifact identifier",
        ),
        # The evidenced record cannot silently drop its receipt.
        (
            _drop_receipt,
            ACTIVSG_INDEX,
            "validated",
            "validated record needs a checked_in_receipt path",
        ),
        (
            _drop_immutable_ids,
            ACTIVSG_INDEX,
            "validated",
            "validated record needs an immutable artifact identifier",
        ),
        # Unevidenced statuses must not carry evidence fields.
        (
            _timestamp_on_unavailable,
            HRRR_INDEX,
            "excluded",
            "excluded record must have a null ingestion_timestamp",
        ),
        (
            _receipt_on_unavailable,
            HRRR_INDEX,
            "excluded",
            "excluded record must not claim a checked_in_receipt",
        ),
        (
            _timestamp_on_unavailable,
            5,
            "excluded",
            "excluded record must have a null ingestion_timestamp",
        ),
        # Structural rules.
        (
            _duplicate_id,
            HRRR_INDEX,
            "excluded",
            "duplicate record id: activsg2000-current",
        ),
        (
            _http_url,
            HRRR_INDEX,
            "excluded",
            "records[5].source_url must be an https URL",
        ),
        (
            _weaken_caveat,
            ACTIVSG_INDEX,
            "validated",
            "synthetic_geometry_caveat must say",
        ),
    ],
)
def test_validator_rejects_evidence_claims_the_inventory_cannot_back(
    mutate, index: int, status: str, expected_error: str
) -> None:
    inventory = copy.deepcopy(_inventory())
    mutate(inventory, index, status)
    assert inventory["records"][index]["status"] == status

    errors = inventory_module.validate_inventory(inventory)

    assert any(expected_error in error for error in errors), errors


def test_receipt_cross_check_flags_hash_and_timestamp_drift(tmp_path: Path) -> None:
    inventory = copy.deepcopy(_inventory())
    activsg = inventory["records"][ACTIVSG_INDEX]
    aux = next(
        a for a in activsg["artifacts"] if a["logical_name"] == "ACTIVSg2000.aux"
    )
    aux["immutable_id"] = "sha256:" + "0" * 64

    report = inventory_module.build_report(inventory, tmp_path / "missing-raw")

    assert report["validation"]["passed"] is False
    assert (
        "activsg2000-current receipt does not match inventory: ACTIVSg2000.aux"
        in report["validation"]["errors"]
    )
    assert report["records"][ACTIVSG_INDEX]["checked_in_receipt"] == {
        "path": "data/sources/activsg2000.json",
        "passed": False,
        "mismatches": ["ACTIVSg2000.aux"],
    }

    inventory = copy.deepcopy(_inventory())
    inventory["records"][ACTIVSG_INDEX]["ingestion_timestamp"] = (
        "2026-09-05T15:21:51+00:00"
    )
    report = inventory_module.build_report(inventory, tmp_path / "missing-raw")
    assert report["records"][ACTIVSG_INDEX]["checked_in_receipt"]["mismatches"] == [
        "retrieved_at"
    ]
    assert "retrieved_at" in report["validation"]["errors"][0]


def test_receipt_cross_check_reads_the_receipt_it_is_pointed_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_source = REPO_ROOT / "data" / "sources" / "activsg2000.json"
    receipt = json.loads(receipt_source.read_text(encoding="utf-8"))
    receipt["files"]["ACTIVSg2000.aux"]["sha256"] = "f" * 64
    tampered = tmp_path / "receipts" / "activsg2000.json"
    tampered.parent.mkdir()
    tampered.write_text(json.dumps(receipt), encoding="utf-8")
    inventory = copy.deepcopy(_inventory())
    inventory["records"][ACTIVSG_INDEX]["checked_in_receipt"] = (
        "receipts/activsg2000.json"
    )
    monkeypatch.chdir(tmp_path)

    report = inventory_module.build_report(inventory, tmp_path / "missing-raw")

    assert report["records"][ACTIVSG_INDEX]["checked_in_receipt"] == {
        "path": "receipts/activsg2000.json",
        "passed": False,
        "mismatches": ["ACTIVSg2000.aux"],
    }
    assert report["validation"]["passed"] is False


@pytest.mark.parametrize(
    ("break_record", "expected_error"),
    [
        (lambda record: record.pop("artifacts"), "records[1] is missing artifacts"),
        (
            lambda record: record.__setitem__("artifacts", "not-a-list"),
            "records[1].artifacts must be a list",
        ),
        (
            lambda record: record.__setitem__("artifacts", ["not-an-object"]),
            "records[1].artifacts must be a list",
        ),
        (lambda record: record.clear(), "records[1] is missing"),
    ],
)
def test_build_report_reports_schema_failures_instead_of_raising(
    tmp_path: Path, break_record, expected_error: str
) -> None:
    inventory = copy.deepcopy(_inventory())
    break_record(inventory["records"][TIGER_INDEX])

    report = inventory_module.build_report(inventory, tmp_path / "missing-raw")

    assert report["validation"]["passed"] is False
    assert any(expected_error in error for error in report["validation"]["errors"])
    broken = report["records"][TIGER_INDEX]
    assert broken["schema_valid"] is False
    assert broken["artifacts"] == []
    assert broken["checked_in_receipt"] is None
    assert report["records"][ACTIVSG_INDEX]["schema_valid"] is True


def test_build_report_handles_non_object_records(tmp_path: Path) -> None:
    inventory = copy.deepcopy(_inventory())
    inventory["records"][TIGER_INDEX] = "not a record"

    report = inventory_module.build_report(inventory, tmp_path / "missing-raw")

    assert "records[1] must be an object" in report["validation"]["errors"]
    assert report["records"][TIGER_INDEX]["id"] is None
    assert report["records"][TIGER_INDEX]["schema_valid"] is False


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_prints_to_stdout_by_default_and_writes_only_when_asked(
    tmp_path: Path,
) -> None:
    before = {path for path in REPO_ROOT.rglob("*.json") if ".venv" not in path.parts}

    printed = _run_cli(cwd=REPO_ROOT)

    after = {path for path in REPO_ROOT.rglob("*.json") if ".venv" not in path.parts}
    assert printed.returncode == 0, printed.stderr
    assert json.loads(printed.stdout)["validation"] == {"passed": True, "errors": []}
    assert after == before, sorted(str(p) for p in after - before)

    target = tmp_path / "out" / "report.json"
    written = _run_cli("--report", str(target), cwd=REPO_ROOT)
    assert written.returncode == 0, written.stderr
    assert written.stdout == ""
    assert (
        json.loads(target.read_text(encoding="utf-8"))["validation"]["passed"] is True
    )


@pytest.mark.parametrize(
    ("content", "expected_error"),
    [
        (None, "inventory unreadable"),
        ("{not json", "inventory is invalid JSON"),
        ('["a list"]', "inventory must be a JSON object"),
        ('{"schema_version": 1, "records": [{"id": "x"}]}', "records[0] is missing"),
    ],
)
def test_cli_writes_an_error_envelope_instead_of_a_traceback(
    tmp_path: Path, content: str | None, expected_error: str
) -> None:
    inventory_path = tmp_path / "inventory.json"
    if content is not None:
        inventory_path.write_text(content, encoding="utf-8")
    report_path = tmp_path / "report.json"

    result = _run_cli(
        "--inventory", str(inventory_path), "--report", str(report_path), cwd=REPO_ROOT
    )

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["validation"]["passed"] is False
    assert any(expected_error in error for error in report["validation"]["errors"])


HRRR_ID = "noaa-hrrr-scenario-weather"


def _write(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_unavailable_record_cannot_publish_an_artifact_checksum() -> None:
    """A record that says nothing was retrieved cannot hash what it did not retrieve."""
    inventory = copy.deepcopy(_inventory())
    record = _record(inventory, HRRR_ID)
    record["status"] = "unavailable"
    record["checked_in_receipt"] = None
    record["ingestion_timestamp"] = None
    assert any(artifact.get("immutable_id") for artifact in record["artifacts"])

    errors = inventory_module.validate_inventory(inventory)

    assert any("immutable artifact identifier" in error for error in errors), errors
    assert not any(
        "immutable artifact identifier" in error
        for error in inventory_module.validate_inventory(_inventory())
    )


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda record, tmp: record.update(
                feasibility_evidence="data/sources/does-not-exist.json"
            ),
            "feasibility_evidence is missing",
        ),
        (
            lambda record, tmp: record.update(
                feasibility_evidence=str(_write(tmp / "e.json", {"status": "ingested"}))
            ),
            "must declare status",
        ),
        (
            lambda record, tmp: record.update(
                feasibility_evidence=str(_write(tmp / "e.json", ["not-an-object"]))
            ),
            "must declare status",
        ),
    ],
)
def test_feasibility_evidence_must_exist_and_keep_disclaiming_ingest(
    tmp_path: Path, mutate, expected: str
) -> None:
    """Feasibility evidence may outlive a real run, but only as what it is."""
    inventory = copy.deepcopy(_inventory())
    record = _record(inventory, HRRR_ID)
    assert inventory_module.build_report(inventory, tmp_path)["validation"]["passed"]
    mutate(record, tmp_path)

    report = inventory_module.build_report(inventory, tmp_path)

    assert not report["validation"]["passed"]
    assert any(expected in error for error in report["validation"]["errors"]), report[
        "validation"
    ]["errors"]


def test_hrrr_record_does_not_deny_the_loader_this_clone_now_has() -> None:
    """The merged receipt must not assert an absence the repository contradicts."""
    loader_source = (REPO_ROOT / "pipelines" / "hrrr.py").read_text(encoding="utf-8")
    assert "def load_hrrr_window(" in loader_source
    assert "def build_county_index(" in loader_source

    record = _record(_inventory(), HRRR_ID)

    for denial in (
        "has no HRRR",
        "no HRRR county-grid index",
        "loader, GRIB transform",
    ):
        assert denial not in record["reason"], record["reason"]
