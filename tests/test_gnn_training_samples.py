from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pytest

from gnn.artifactwriter import ArtifactWriter, split_by_contingency
from gnn.contracts import (
    PlannedSample,
    SampleLabels,
    SamplingError,
    TrainingSample,
)
from gnn.generate import GenerationConfig, generate_training_samples
from gnn.hours import hourly_demand_profile, select_hours
from gnn.normalization import normalize_feature_value
from gnn.sampler import SamplerConfig, _coalesce_contingency_families, build_plan


def _fixture_db(tmp_path: Path) -> Path:
    """A small native-electrical fixture with observed ERCO demand."""
    path = tmp_path / "grid.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE buses(bus_id BIGINT, name TEXT, base_kv DOUBLE, lon DOUBLE, lat DOUBLE, county_fips TEXT)"
        )
        con.execute(
            "CREATE TABLE lines(line_id BIGINT, from_bus BIGINT, to_bus BIGINT, base_kv DOUBLE, r_pu DOUBLE, x_pu DOUBLE, rate_a_mw DOUBLE, length_km DOUBLE, is_transformer BOOLEAN)"
        )
        con.execute(
            "CREATE TABLE gens(gen_id BIGINT, bus_id BIGINT, fuel TEXT, pmax_mw DOUBLE)"
        )
        con.execute(
            "CREATE TABLE loads(load_id BIGINT, bus_id BIGINT, p_mw_nominal DOUBLE)"
        )
        con.execute(
            "CREATE TABLE ba_load_hourly(ba_code TEXT, ts TIMESTAMP, demand_mw DOUBLE)"
        )
        con.execute(
            "CREATE TABLE synthetic_bus_electrical(bus_id BIGINT, bus_type INTEGER, pd_mw DOUBLE, qd_mvar DOUBLE, gs_mw DOUBLE, bs_mvar DOUBLE, vm_pu DOUBLE, va_deg DOUBLE, vmin_pu DOUBLE, vmax_pu DOUBLE)"
        )
        con.execute(
            "CREATE TABLE synthetic_branch_electrical(line_id BIGINT, b_pu DOUBLE, tap_ratio DOUBLE, shift_deg DOUBLE, status INTEGER)"
        )
        con.execute(
            "CREATE TABLE synthetic_generator_electrical(gen_id BIGINT, p_mw DOUBLE, q_mvar DOUBLE, qmax_mvar DOUBLE, qmin_mvar DOUBLE, pmin_mw DOUBLE, status INTEGER)"
        )
        con.execute(
            "INSERT INTO buses VALUES (10, 'slack', 230, -97, 30, '48001'), (20, 'load', 115, -97.1, 30.1, '48003'), (30, 'island', 230, -97.2, 30.2, '48003')"
        )
        con.execute(
            "INSERT INTO lines VALUES (1, 10, 20, 230, .01, .1, 100, 2, false), (2, 20, 30, 230, .01, .1, 30, 1, true)"
        )
        con.execute("INSERT INTO gens VALUES (1, 10, 'ng', 100), (2, 20, 'solar', 20)")
        con.execute("INSERT INTO loads VALUES (1, 20, 10), (2, 30, 20)")
        con.execute(
            "INSERT INTO synthetic_bus_electrical VALUES (10, 3, 0, 0, 0, 0, 1, 0, .9, 1.1), (20, 2, 10, 0, 0, 0, 1, 0, .9, 1.1), (30, 1, 20, 0, 0, 0, 1, 0, .9, 1.1)"
        )
        con.execute(
            "INSERT INTO synthetic_branch_electrical VALUES (1, 0, 0, 0, 1), (2, 0, 0, 0, 1)"
        )
        con.execute(
            "INSERT INTO synthetic_generator_electrical VALUES (1, 30, 0, 100, -100, 0, 1), (2, 0, 0, 20, -20, 0, 1)"
        )
        con.execute(
            "INSERT INTO ba_load_hourly VALUES ('ERCO', '2021-02-14 07:00:00', 30000), ('ERCO', '2021-02-14 08:00:00', 45000), ('ERCO', '2021-02-14 09:00:00', 70000)"
        )
    return path


def _graph_fixture(out_dir: Path) -> None:
    graph = out_dir / "graph"
    graph.mkdir(parents=True)
    nodes = b'[{"features":{"base_kv":230.0,"p_mw_nominal":null}}]\n'
    edges = b'[{"features":{"rate_a_mw":null,"x_pu":0.1}}]\n'
    (graph / "nodes.json").write_bytes(nodes)
    (graph / "edges.json").write_bytes(edges)
    manifest = {
        "dataset_sha256": "a" * 64,
        "schema_version": "1.0.0",
        "topology_label": "synthetic (ACTIVSg2000)",
        "files": {
            "nodes.json": hashlib.sha256(nodes).hexdigest(),
            "edges.json": hashlib.sha256(edges).hexdigest(),
        },
    }
    (graph / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_observed_hours_are_utc_stratified_and_deterministic(tmp_path: Path) -> None:
    profile = hourly_demand_profile(_fixture_db(tmp_path))

    assert [point.ts for point in profile] == [
        "2021-02-14T07:00:00Z",
        "2021-02-14T08:00:00Z",
        "2021-02-14T09:00:00Z",
    ]
    assert [point.band for point in profile] == ["calm", "stress", "stress"]
    assert select_hours(profile, count=3, seed=490) == select_hours(
        profile, count=3, seed=490
    )


def test_sampler_and_split_keep_contingency_families_together(tmp_path: Path) -> None:
    from twin.build import build_network

    database = _fixture_db(tmp_path)
    profile = hourly_demand_profile(database)
    plans = build_plan(
        build_network(database),
        profile[:2],
        seed=490,
        config=SamplerConfig(n1_per_hour=1, n2_per_hour=1, placement_per_hour=2),
    )

    assert plans == build_plan(
        build_network(database),
        profile[:2],
        seed=490,
        config=SamplerConfig(n1_per_hour=1, n2_per_hour=1, placement_per_hour=2),
    )
    families = {plan.group_key for plan in plans if plan.kind != "baseline"}
    assert all(
        {plan.kind for plan in plans if plan.group_key == family}
        >= {"n1", "n2", "placement_gen", "placement_load"}
        for family in families
    )
    split = split_by_contingency(plans, seed=490, held_out_fraction=0.5)
    assert not set(split["train_group_keys"]).intersection(split["held_out_group_keys"])
    for family in families:
        ids = {plan.sample_index for plan in plans if plan.group_key == family}
        assert ids.issubset(set(split["train_sample_ids"])) or ids.issubset(
            set(split["held_out_sample_ids"])
        )
    assert (
        split["holdout_axes"]["contingency_family"]["temporal_holdout"] == "not_claimed"
    )


def test_overlapping_n2_secondary_cannot_leak_into_another_family() -> None:
    plans = _coalesce_contingency_families(
        [
            PlannedSample(0, "n1", 0, ("line:1",), "line:1", "contingency:line:1"),
            PlannedSample(
                1,
                "n2",
                0,
                ("line:1", "line:2"),
                "line:1",
                "contingency:line:1",
            ),
            PlannedSample(2, "n1", 1, ("line:2",), "line:2", "contingency:line:2"),
        ]
    )

    assert len({plan.group_key for plan in plans}) == 1
    split = split_by_contingency(plans, seed=490, held_out_fraction=0.5)
    assert set(split["train_sample_ids"]) in ({0, 1, 2}, set())
    assert set(split["held_out_sample_ids"]) in ({0, 1, 2}, set())


def test_generation_is_resumable_and_binds_the_graph_export(tmp_path: Path) -> None:
    database = _fixture_db(tmp_path)
    output = tmp_path / "artifact"
    _graph_fixture(output)
    config = GenerationConfig(
        hours=1,
        sampler=SamplerConfig(n1_per_hour=1, n2_per_hour=1, placement_per_hour=2),
    )

    first = generate_training_samples(database, output, config=config)
    second = generate_training_samples(database, output, config=config)
    records = [
        json.loads(line) for line in (output / "samples.jsonl").read_text().splitlines()
    ]

    assert first == second
    assert first["planned_count"] == 5
    assert len(records) == 5
    assert first["graph_dataset"]["topology_label"] == "synthetic (ACTIVSg2000)"
    normalization = json.loads((output / "normalization.json").read_text())
    assert normalization["fit_partition"] == "train"
    assert not set(normalization["fit_sample_ids"]).intersection(
        normalization["excluded_partitions"]["held_out"]
    )
    assert normalization["statistics"]["node_features"]["base_kv"]["mean"] == 230.0
    assert (
        normalize_feature_value(
            230.0, normalization["statistics"]["node_features"]["base_kv"]
        )
        == 0.0
    )
    assert (
        first["identity"]["source_database_sha256"]
        == hashlib.sha256(database.read_bytes()).hexdigest()
    )
    _assert_rows_came_from_the_solver(first, records)


def test_writer_rejects_tampered_graph_and_identity_changes(tmp_path: Path) -> None:
    database = _fixture_db(tmp_path)
    output = tmp_path / "artifact"
    _graph_fixture(output)
    writer = ArtifactWriter(output, source_db=database, identity={"seed": 490})
    assert writer.ensure_graph_dataset()["schema_version"] == "1.0.0"
    (output / "graph" / "nodes.json").write_text("tampered\n")
    with pytest.raises(Exception, match="hash mismatch"):
        writer.ensure_graph_dataset()
    with pytest.raises(Exception, match="identity does not match"):
        ArtifactWriter(output, source_db=database, identity={"seed": 491})


def test_writer_persists_a_record_once(tmp_path: Path) -> None:
    database = _fixture_db(tmp_path)
    writer = ArtifactWriter(
        tmp_path / "artifact", source_db=database, identity={"seed": 490}
    )
    plan = PlannedSample(0, "baseline", 0, (), None, "baseline:hour:0")
    sample = TrainingSample(
        "sample-0",
        plan,
        "labelled",
        490,
        "observed_ba_load",
        {},
        {},
        labels=SampleLabels(0, 30, 0, True, "solved"),
    )

    assert writer.append(sample)
    assert not writer.append(sample)


# The fixture network carries exactly 30 MW of nominal load (10 MW at bus 20,
# 20 MW at bus 30) and the selected hour scales it by 1.0. These are the DC
# solver's own answers for that network, recorded from a real run; a stub, a
# hardcoded constant or an unimportable backend cannot reproduce them.
SOLVER_ORACLE = {
    "baseline": (30.0, 0.0, ()),
    "n1": (10.0, 20.0, ("impedance:2",)),
    "n2": (0.0, 30.0, ("impedance:2", "line:1")),
    "placement_gen": (10.0, 20.0, ("impedance:2",)),
    "placement_load": (10.0, 20.0, ("impedance:2",)),
}
FIXTURE_NOMINAL_LOAD_MW = 30.0


def _assert_rows_came_from_the_solver(manifest: dict, records: list[dict]) -> None:
    """Every row is a real solve, labelled synthetic, and matches the oracle."""
    assert manifest["labelled_count"] == manifest["planned_count"]
    assert manifest["failed_count"] == 0
    assert [record["status"] for record in records] == ["labelled"] * len(records)
    for record in records:
        assert record["solver"] == "pandapower.rundcpp"
        assert record["topology"] == "synthetic (ACTIVSg2000)"
        assert record["synthetic"] is True
        labels = record["labels"]
        assert labels is not None
        served = labels["total_served_load_mw"]
        lost = labels["lost_load_mw"]
        assert labels["lost_load_reconciled"] is True
        assert served + lost == pytest.approx(FIXTURE_NOMINAL_LOAD_MW)
        expected_served, expected_lost, expected_out = SOLVER_ORACLE[
            record["plan"]["kind"]
        ]
        assert served == pytest.approx(expected_served), record["plan"]["kind"]
        assert lost == pytest.approx(expected_lost), record["plan"]["kind"]
        assert tuple(labels["out_of_service_element_ids"]) == expected_out
    # The five contingencies do not all produce the same answer; a single
    # hardcoded pair of numbers cannot satisfy the oracle above.
    assert len({record["labels"]["total_served_load_mw"] for record in records}) == 3


def test_two_fresh_generations_are_byte_identical(tmp_path: Path) -> None:
    """Determinism, measured the only way that can see it: TWO FRESH directories.

    The resumable test cannot detect a non-reproducible record, because its
    second call resumes the same directory and appends nothing.
    """
    database = _fixture_db(tmp_path)
    config = GenerationConfig(
        hours=1,
        sampler=SamplerConfig(n1_per_hour=1, n2_per_hour=1, placement_per_hour=2),
    )
    manifests = {}
    for name in ("run_a", "run_b"):
        output = tmp_path / name
        _graph_fixture(output)
        manifests[name] = generate_training_samples(database, output, config=config)

    first_bytes = (tmp_path / "run_a" / "samples.jsonl").read_bytes()
    second_bytes = (tmp_path / "run_b" / "samples.jsonl").read_bytes()
    assert first_bytes == second_bytes
    assert manifests["run_a"]["samples_sha256"] == manifests["run_b"]["samples_sha256"]
    assert manifests["run_a"] == manifests["run_b"]

    records = [json.loads(line) for line in first_bytes.decode().splitlines()]
    # No wall-clock value may reach the canonical record or its digest.
    assert all("solve_seconds" not in record for record in records)
    _assert_rows_came_from_the_solver(manifests["run_a"], records)

    # The timings are still published, just beside the samples.
    timings = [
        json.loads(line)
        for line in (tmp_path / "run_a" / "timings.jsonl").read_text().splitlines()
    ]
    assert {entry["sample_id"] for entry in timings} == {
        record["sample_id"] for record in records
    }
    assert all(entry["solve_seconds"] >= 0.0 for entry in timings)


def test_failed_training_sample_keeps_labels_missing_and_names_synthetic_topology() -> (
    None
):
    """A failed row carries no labels and claims no solver (carried from #320)."""
    plan = PlannedSample(0, "n1", 0, ("line:1",), None, "n1:line:1")
    failed = TrainingSample(
        "sample-0",
        plan,
        "failed",
        490,
        "observed_ba_load",
        {},
        {},
        failure_kind="RuntimeError",
        failure_message="solver diverged",
        solve_seconds=1.5,
    ).json()

    assert failed["status"] == "failed"
    assert failed["labels"] is None
    assert failed["topology"] == "synthetic (ACTIVSg2000)"
    assert failed["synthetic"] is True
    # No solver is named on a row that produced no solver output.
    assert failed["solver"] is None
    # And no wall-clock value reaches the canonical record.
    assert "solve_seconds" not in failed


def test_missing_solver_backend_is_refused_before_any_row_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unimportable backend is an environment failure, not 5 failed labels."""
    import gnn.generate as generate_module

    def unavailable() -> None:
        raise SamplingError("solver backend unavailable: no module named twin.cascade")

    monkeypatch.setattr(generate_module, "require_solver_backend", unavailable)
    database = _fixture_db(tmp_path)
    output = tmp_path / "artifact"
    _graph_fixture(output)
    with pytest.raises(SamplingError, match="solver backend unavailable"):
        generate_training_samples(database, output, config=GenerationConfig(hours=1))
    assert not (output / "samples.jsonl").exists()


def test_finish_refuses_a_complete_artifact_with_zero_labelled_rows(
    tmp_path: Path,
) -> None:
    """`generation_status: "complete"` must never mean "every row failed"."""
    database = _fixture_db(tmp_path)
    output = tmp_path / "artifact"
    _graph_fixture(output)
    writer = ArtifactWriter(output, source_db=database, identity={"seed": 490})
    graph_dataset = writer.ensure_graph_dataset()
    plan = PlannedSample(0, "baseline", 0, (), None, "baseline:hour:0")
    writer.append(
        TrainingSample(
            "sample-0",
            plan,
            "failed",
            490,
            "observed_ba_load",
            {},
            {},
            failure_kind="ModuleNotFoundError",
            failure_message="No module named 'twin.cascade'",
        )
    )
    split = split_by_contingency([plan], seed=490, held_out_fraction=0.2)
    with pytest.raises(SamplingError, match="zero labelled samples"):
        writer.finish(split, planned_count=1, graph_dataset=graph_dataset)
