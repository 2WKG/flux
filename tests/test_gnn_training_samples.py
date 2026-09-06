from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pytest

from gnn.artifactwriter import ArtifactWriter, split_by_contingency
from gnn.contracts import PlannedSample, SampleLabels, TrainingSample
from gnn.generate import GenerationConfig, generate_training_samples
from gnn.hours import hourly_demand_profile, select_hours
from gnn.sampler import SamplerConfig, build_plan
from twin.build import build_network


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
    nodes = b"[]\n"
    edges = b"[]\n"
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
    assert [point.band for point in profile] == ["calm", "mid", "stress"]
    assert select_hours(profile, count=3, seed=490) == select_hours(
        profile, count=3, seed=490
    )


def test_sampler_and_split_keep_contingency_families_together(tmp_path: Path) -> None:
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
    assert (
        first["identity"]["source_database_sha256"]
        == hashlib.sha256(database.read_bytes()).hexdigest()
    )
    assert all(record["solver"] == "pandapower.rundcpp" for record in records)


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
