"""Behavioural tests for the runtime-store materializer.

The refusal tests drive ``materialize()`` itself rather than its private
helpers: the "verified" claim lives at the call sites, so a helper-only test
stays green while a corrupt input publishes.
"""

import gzip
import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from pipelines.db import connect as connect_store
from scripts.materialize_runtime_store import (
    CONTENT_DIGEST_ALGORITHM,
    MaterializationError,
    _derived_rows,
    _expected_counts,
    _published_releases,
    _require_hash,
    _scenario_windows,
    _validate_output,
    materialize,
    sha256_file,
    store_content_digest,
    verify,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_INVENTORY_ROOT = REPO_ROOT / "data/artifacts/physical_inventory"


def test_require_hash_rejects_a_receipt_that_does_not_bind_the_bytes(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"real bytes")
    assert _require_hash(artifact, sha256_file(artifact), "fixture") == sha256_file(
        artifact
    )
    with pytest.raises(MaterializationError, match="SHA-256 mismatch"):
        _require_hash(artifact, "0" * 64, "fixture")


def test_derived_rows_identifies_products_that_must_not_be_erased(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.duckdb"
    con = duckdb.connect(str(database))
    con.execute("CREATE TABLE cascade_runs (run_id TEXT)")
    con.execute("INSERT INTO cascade_runs VALUES ('uri_2021-s0')")
    con.execute("CREATE TABLE outage_predictions (scenario_id TEXT)")
    con.close()
    assert _derived_rows(database) == {"cascade_runs": 1}


def test_published_releases_rejects_a_self_consistent_replacement(
    tmp_path: Path,
) -> None:
    root = tmp_path / "physical_inventory"
    for state in ("tx", "mn"):
        directory = root / state
        directory.mkdir(parents=True)
        shutil.copy2(
            SOURCE_INVENTORY_ROOT / state / "physical-inventory-1.1.0.json.gz",
            directory / "physical-inventory-1.1.0.json.gz",
        )
    shutil.copy2(
        SOURCE_INVENTORY_ROOT / "manifest-1.1.0.json", root / "manifest-1.1.0.json"
    )
    # The Minnesota release remains an internally valid, self-consistent artifact,
    # but it is not the TX release pinned by the published manifest.
    shutil.copy2(
        SOURCE_INVENTORY_ROOT / "mn/physical-inventory-1.1.0.json.gz",
        root / "tx/physical-inventory-1.1.0.json.gz",
    )

    with pytest.raises(
        MaterializationError, match="published tx inventory.*SHA-256 mismatch"
    ):
        _published_releases(root, "1.1.0")


# --------------------------------------------------------------------------
# Fixtures: a synthetic runtime input set small enough to run in CI.
# --------------------------------------------------------------------------

SCENARIOS = ("uri_2021", "beryl_2024")


def _inventory_root(tmp_path: Path, *, tx_geography: str = "tx") -> Path:
    """Build a manifest-consistent inventory root with empty asset releases."""
    root = tmp_path / "physical_inventory"
    entries = []
    for state in SCENARIOS and ("tx", "mn"):
        (root / state).mkdir(parents=True)
        content_sha256 = hashlib.sha256(f"{state}-content".encode()).hexdigest()
        payload = {
            "artifact_id": f"{state}:physical-inventory:1.1.0",
            "artifact_version": "1.1.0",
            "content_sha256": content_sha256,
            "geography_id": tx_geography if state == "tx" else state,
            "assets": [],
        }
        raw = gzip.compress(
            json.dumps(payload, sort_keys=True).encode("utf-8"), mtime=0
        )
        (root / state / "physical-inventory-1.1.0.json.gz").write_bytes(raw)
        entries.append(
            {
                "state": state,
                "artifact_id": payload["artifact_id"],
                "published_path": (
                    f"data/artifacts/physical_inventory/{state}/"
                    "physical-inventory-1.1.0.json.gz"
                ),
                "compressed_sha256": hashlib.sha256(raw).hexdigest(),
                "canonical_content_sha256": content_sha256,
            }
        )
    (root / "manifest-1.1.0.json").write_text(
        json.dumps({"release_version": "1.1.0", "artifacts": entries}, indent=2)
    )
    return root


def _weather_store(
    path: Path,
    *,
    scenarios: tuple[str, ...] = SCENARIOS,
    counties: int = 254,
    hours: int = 2,
) -> Path:
    """A DuckDB shaped like the HRRR window database the materializer consumes."""
    con = connect_store(path)
    try:
        fips = [f"48{index:03d}" for index in range(counties)]
        con.executemany(
            "INSERT INTO counties VALUES (?, ?, 'TX', 1000, ?, 'test', 'test', NULL, NULL, 'batch')",
            [(code, f"county {code}", b"\x00") for code in fips],
        )
        base = datetime(2021, 2, 14, tzinfo=UTC).replace(tzinfo=None)
        for scenario_index, scenario in enumerate(scenarios):
            for hour in range(hours):
                ts = base + timedelta(hours=hour + 24 * scenario_index)
                con.executemany(
                    "INSERT INTO weather_hourly VALUES (?, ?, 1.0, 2.0, 3.0, 0.0, 0.0,"
                    " 'noaa_hrrr', 'run', NULL, NULL, 'batch')",
                    [(code, ts) for code in fips],
                )
                con.execute(
                    "INSERT INTO weather_source_runs VALUES (?, ?, 'noaa_hrrr', 'r',"
                    " 'f', 'hrrr', 'sig', ?, 0, ?, 0, 'u', 'u', NULL, NULL, '{}',"
                    " '{}', '{}', '{}', 'v1', 'receipt', ?, NULL, ?)",
                    [scenario, ts, ts, ts, ts, ts],
                )
    finally:
        con.close()
    return path


def _runtime_inputs(tmp_path: Path, **inventory_kwargs) -> dict[str, object]:
    """Verified paths plus receipts binding their bytes, ready for materialize()."""
    sources = tmp_path / "sources"
    sources.mkdir()
    hrrr_db = _weather_store(sources / "grid.duckdb")
    aux = sources / "ACTIVSg2000.aux"
    aux.write_bytes(b"aux bytes that a real run would parse")
    case = sources / "case_ACTIVSg2000.m"
    case.write_bytes(b"case bytes that a real run would parse")

    hrrr_receipt = sources / "hrrr-receipt.json"
    hrrr_receipt.write_text(
        json.dumps(
            {
                "retrieved_at": "2026-09-06T05:52:00Z",
                "files": {"grid.duckdb": {"sha256": sha256_file(hrrr_db)}},
                "validation": {
                    "total_weather_rows": 254 * 2 * len(SCENARIOS),
                    "beryl_2024": {"source_runs_total": 2 * len(SCENARIOS)},
                },
            }
        )
    )
    activsg_receipt = sources / "activsg-receipt.json"
    activsg_receipt.write_text(
        json.dumps(
            {
                "retrieved_at": "2026-09-05T15:21:50+00:00",
                "files": {
                    aux.name: {"sha256": sha256_file(aux)},
                    case.name: {"sha256": sha256_file(case)},
                },
                "aux_check": {"bus_records": 2000},
            }
        )
    )
    return {
        "hrrr_db": hrrr_db,
        "hrrr_receipt": hrrr_receipt,
        "aux": aux,
        "case": case,
        "activsg_receipt": activsg_receipt,
        "inventory_root": _inventory_root(tmp_path, **inventory_kwargs),
        "version": "1.1.0",
        "output": tmp_path / "out" / "grid.duckdb",
        "receipt_output": tmp_path / "out" / "runtime-store-receipt.json",
    }


def _corrupt(path: Path) -> None:
    payload = bytearray(path.read_bytes())
    payload[0] ^= 0xFF
    path.write_bytes(bytes(payload))


# --------------------------------------------------------------------------
# The "verified" claim, at its call site.
# --------------------------------------------------------------------------


def test_materialize_refuses_a_corrupted_aux_before_writing_anything(
    tmp_path: Path,
) -> None:
    """Replacing the AUX call-site hash check with sha256_file() must fail here."""
    options = _runtime_inputs(tmp_path)
    _corrupt(options["aux"])

    with pytest.raises(MaterializationError, match="ACTIVS AUX SHA-256 mismatch"):
        materialize(**options)

    assert not options["output"].exists()
    assert not options["receipt_output"].exists()


def test_materialize_refuses_a_corrupted_case_before_writing_anything(
    tmp_path: Path,
) -> None:
    options = _runtime_inputs(tmp_path)
    _corrupt(options["case"])

    with pytest.raises(
        MaterializationError, match="ACTIVS MATPOWER case SHA-256 mismatch"
    ):
        materialize(**options)
    assert not options["output"].exists()


def test_materialize_refuses_a_corrupted_hrrr_database_before_writing_anything(
    tmp_path: Path,
) -> None:
    options = _runtime_inputs(tmp_path)
    _corrupt(options["hrrr_db"])

    with pytest.raises(MaterializationError, match="HRRR DB SHA-256 mismatch"):
        materialize(**options)
    assert not options["output"].exists()


def test_materialize_names_a_receipt_that_does_not_exist(tmp_path: Path) -> None:
    options = _runtime_inputs(tmp_path)
    options["hrrr_receipt"] = tmp_path / "sources" / "absent-receipt.json"

    # The message has to distinguish "no such file" from "unreadable JSON": both
    # states name the path, so matching the path alone would assert nothing.
    with pytest.raises(
        MaterializationError,
        match=r"required receipt does not exist: .*absent-receipt\.json",
    ):
        materialize(**options)

    options["hrrr_receipt"].write_text("{ not json")
    with pytest.raises(MaterializationError, match="invalid JSON receipt"):
        materialize(**options)


# --------------------------------------------------------------------------
# The guards materialize() enforces before it stages anything.
# --------------------------------------------------------------------------


def test_materialize_refuses_a_release_whose_geography_is_not_its_state(
    tmp_path: Path,
) -> None:
    options = _runtime_inputs(tmp_path, tx_geography="mn")

    with pytest.raises(
        MaterializationError, match="geography does not match its state path"
    ):
        materialize(**options)
    assert not options["output"].exists()


def test_materialize_refuses_to_replace_an_existing_store_without_replace(
    tmp_path: Path,
) -> None:
    options = _runtime_inputs(tmp_path)
    options["output"].parent.mkdir(parents=True)
    options["output"].write_bytes(b"the store that is already serving")

    with pytest.raises(MaterializationError, match="output exists; use --replace"):
        materialize(**options)
    assert options["output"].read_bytes() == b"the store that is already serving"


def test_materialize_refuses_to_discard_derived_products_without_the_flag(
    tmp_path: Path,
) -> None:
    options = _runtime_inputs(tmp_path)
    options["output"].parent.mkdir(parents=True)
    con = duckdb.connect(str(options["output"]))
    con.execute("CREATE TABLE site_scores (site_id TEXT)")
    con.execute("INSERT INTO site_scores VALUES ('s-1')")
    con.close()
    before = options["output"].read_bytes()

    with pytest.raises(MaterializationError, match="holds derived products"):
        materialize(**options, replace=True)
    assert options["output"].read_bytes() == before

    # ...and the same call is still refused for the corrupt-input reason first.
    _corrupt(options["aux"])
    with pytest.raises(MaterializationError, match="ACTIVS AUX SHA-256 mismatch"):
        materialize(**options, replace=True, discard_derived=True)


def test_materialize_refuses_a_receipt_whose_retrieved_at_has_no_offset(
    tmp_path: Path,
) -> None:
    options = _runtime_inputs(tmp_path)
    receipt = json.loads(options["activsg_receipt"].read_text())
    receipt["retrieved_at"] = "2026-09-05T15:21:50"
    options["activsg_receipt"].write_text(json.dumps(receipt))

    with pytest.raises(MaterializationError, match="retrieved_at must have an offset"):
        materialize(**options)
    assert not options["output"].exists()


def test_materialize_leaves_the_published_store_untouched_when_staging_fails(
    tmp_path: Path,
) -> None:
    """Publication is all-or-nothing: a staging failure publishes nothing."""
    options = _runtime_inputs(tmp_path)
    options["output"].parent.mkdir(parents=True)
    serving = connect_store(options["output"])
    serving.execute("CREATE TABLE serving_marker (note TEXT)")
    serving.execute("INSERT INTO serving_marker VALUES ('the store already serving')")
    serving.close()
    # A weather input with no scenario tables fails inside the staging directory,
    # after the copy and well past every pre-flight guard.
    empty = tmp_path / "sources" / "empty.duckdb"
    duckdb.connect(str(empty)).close()
    options["hrrr_db"] = empty
    receipt = json.loads(options["hrrr_receipt"].read_text())
    receipt["files"]["grid.duckdb"]["sha256"] = sha256_file(empty)
    options["hrrr_receipt"].write_text(json.dumps(receipt))

    with pytest.raises(MaterializationError, match="lacks required tables"):
        materialize(**options, replace=True)

    still_serving = duckdb.connect(str(options["output"]), read_only=True)
    try:
        assert still_serving.execute("SELECT note FROM serving_marker").fetchone() == (
            "the store already serving",
        )
    finally:
        still_serving.close()
    assert not options["receipt_output"].exists()
    assert [entry.name for entry in options["output"].parent.iterdir()] == [
        options["output"].name
    ]


# --------------------------------------------------------------------------
# Window and count validation, against real DuckDB stores.
# --------------------------------------------------------------------------


def test_scenario_windows_requires_both_scenarios_over_every_county(
    tmp_path: Path,
) -> None:
    complete = duckdb.connect(str(_weather_store(tmp_path / "complete.duckdb")))
    try:
        windows = _scenario_windows(complete)
    finally:
        complete.close()
    assert [row[0] for row in windows] == ["beryl_2024", "uri_2021"]
    assert all(start is not None and end is not None for _, start, end in windows)

    short = duckdb.connect(str(_weather_store(tmp_path / "short.duckdb", counties=253)))
    try:
        with pytest.raises(MaterializationError, match="254 counties"):
            _scenario_windows(short)
    finally:
        short.close()

    one = duckdb.connect(
        str(_weather_store(tmp_path / "one.duckdb", scenarios=("uri_2021",)))
    )
    try:
        with pytest.raises(MaterializationError, match="weather scenarios must be"):
            _scenario_windows(one)
    finally:
        one.close()

    bare = duckdb.connect(str(tmp_path / "bare.duckdb"))
    try:
        with pytest.raises(MaterializationError, match="lacks required tables"):
            _scenario_windows(bare)
    finally:
        bare.close()


def test_validate_output_names_the_count_that_did_not_hold(tmp_path: Path) -> None:
    con = duckdb.connect(str(tmp_path / "counts.duckdb"))
    try:
        con.execute("CREATE TABLE buses (bus_id INTEGER)")
        con.execute("INSERT INTO buses VALUES (1), (2)")
        con.execute("CREATE TABLE lines (line_id INTEGER, is_transformer BOOLEAN)")
        con.execute("INSERT INTO lines VALUES (1, true), (2, false), (3, false)")
        for table in (
            "weather_hourly",
            "weather_source_runs",
            "scenarios",
            "physical_inventory_manifests",
            "physical_assets",
        ):
            con.execute(f"CREATE TABLE {table} (id INTEGER)")
            con.execute(f"INSERT INTO {table} VALUES (1)")
        expected = {
            "buses": 2,
            "lines": 3,
            "transformer_branches": 1,
            "weather_hourly": 1,
            "weather_source_runs": 1,
            "scenarios": 1,
            "physical_releases": 1,
            "physical_assets": 1,
        }
        assert _validate_output(con, expected) == expected

        with pytest.raises(MaterializationError) as excinfo:
            _validate_output(con, {**expected, "buses": 2000})
        assert "'buses': {'expected': 2000, 'actual': 2}" in str(excinfo.value)
    finally:
        con.close()


def test_expected_counts_are_read_from_the_input_receipts() -> None:
    hrrr = {
        "validation": {
            "total_weather_rows": 85344,
            "beryl_2024": {"source_runs_total": 336},
        }
    }
    activsg = {"aux_check": {"bus_records": 2000}}
    expected = _expected_counts(hrrr, activsg, 14396)
    assert expected["buses"] == 2000
    assert expected["weather_hourly"] == 85344
    assert expected["weather_source_runs"] == 336
    assert expected["physical_assets"] == 14396

    with pytest.raises(MaterializationError, match="do not declare"):
        _expected_counts({"validation": {}}, activsg, 14396)


# --------------------------------------------------------------------------
# The receipt has to survive the store's first use.
# --------------------------------------------------------------------------


def test_content_digest_survives_a_read_write_reopen(tmp_path: Path) -> None:
    """A file hash cannot make this claim; the content digest must."""
    store = _weather_store(tmp_path / "grid.duckdb")
    file_hash_before = sha256_file(store)
    digest_before = store_content_digest(store)

    connect_store(store).close()  # exactly what serving the store does

    assert sha256_file(store) != file_hash_before
    assert store_content_digest(store) == digest_before
    assert digest_before["algorithm"] == CONTENT_DIGEST_ALGORITHM
    assert digest_before["tables"]["counties"]["rows"] == 254


def test_content_digest_moves_when_a_single_row_changes(tmp_path: Path) -> None:
    store = _weather_store(tmp_path / "grid.duckdb")
    before = store_content_digest(store)
    con = connect_store(store)
    try:
        con.execute("UPDATE counties SET pop = 1001 WHERE county_fips = '48000'")
    finally:
        con.close()
    after = store_content_digest(store)
    assert after["sha256"] != before["sha256"]
    assert after["tables"]["counties"]["md5"] != before["tables"]["counties"]["md5"]


def test_verify_refuses_a_store_that_drifted_from_its_receipt(tmp_path: Path) -> None:
    store = _weather_store(tmp_path / "grid.duckdb")
    receipt_path = tmp_path / "runtime-store-receipt.json"
    receipt_path.write_text(
        json.dumps({"content_digest": store_content_digest(store)}, indent=2)
    )
    assert verify(output=store, receipt_output=receipt_path)["verified"] is True

    con = connect_store(store)
    try:
        con.execute("DELETE FROM weather_hourly WHERE county_fips = '48000'")
    finally:
        con.close()

    with pytest.raises(MaterializationError, match="no longer matches its receipt"):
        verify(output=store, receipt_output=receipt_path)
    with pytest.raises(MaterializationError, match="weather_hourly"):
        verify(output=store, receipt_output=receipt_path)


def test_verify_refuses_a_receipt_with_no_content_digest(tmp_path: Path) -> None:
    store = _weather_store(tmp_path / "grid.duckdb")
    receipt_path = tmp_path / "runtime-store-receipt.json"
    receipt_path.write_text(json.dumps({"output_sha256": "0" * 64}))
    with pytest.raises(MaterializationError, match="records no content digest"):
        verify(output=store, receipt_output=receipt_path)
