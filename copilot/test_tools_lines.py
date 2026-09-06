from datetime import UTC, datetime

import duckdb

from copilot.tools_lines import TopLinesReader


def _db(path, *, scenarios=("uri_2021",), source_kind="fixture"):
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE lines (line_id BIGINT, from_bus BIGINT, to_bus BIGINT, base_kv DOUBLE)")
    con.execute("CREATE TABLE line_upgrade_scores (line_id BIGINT, scenario_id TEXT, ranking_version TEXT, computed_at TIMESTAMP, source_name TEXT, source_ref TEXT, source_kind TEXT, congestion_usd_yr DOUBLE, dlr_uplift_mw DOUBLE, reconductor_uplift_mw DOUBLE, dlr_cost_usd DOUBLE, reconductor_cost_usd DOUBLE, mw_per_musd DOUBLE, ferc_screen_pass BOOLEAN, spark_eligible BOOLEAN, simulation_run_id TEXT)")
    con.execute("CREATE TABLE line_upgrade_detail (line_id BIGINT, scenario_id TEXT, best_tech TEXT, congestion_method TEXT, region TEXT)")
    for index, scenario in enumerate(scenarios, 1):
        con.execute("INSERT INTO lines VALUES (?, 1, 2, 230)", [index])
        con.execute("INSERT INTO line_upgrade_scores VALUES (?, ?, 'v1', ?, 'fixture', 'fixture-ref', ?, 100, 20, 10, 1000000, 2000000, ?, true, false, NULL)", [index, scenario, datetime(2026, 1, 1, tzinfo=UTC), source_kind, 20 - index])
        con.execute("INSERT INTO line_upgrade_detail VALUES (?, ?, 'dlr', 'exact', 'ERCOT')", [index, scenario])
    con.close()


def test_reads_one_partition_in_deterministic_order_with_provenance(tmp_path):
    path = tmp_path / "grid.duckdb"
    _db(path)
    result = TopLinesReader(path).top_lines("ERCOT", "dlr", 1)
    assert result.status == "available"
    assert result.scenario_id == "uri_2021"
    assert result.lines[0].source_class == "observed"
    assert result.provenance[0].source_kind == "fixture"


def test_preserves_explicit_source_kind(tmp_path):
    for kind in ("observed", "simulated", "heuristic"):
        path = tmp_path / f"{kind}.duckdb"
        _db(path, source_kind=kind)
        assert TopLinesReader(path).top_lines("ERCOT", "any").provenance[0].source_kind == kind


def test_ambiguous_or_missing_artifacts_fail_closed(tmp_path):
    path = tmp_path / "grid.duckdb"
    _db(path, scenarios=("uri_2021", "beryl_2024"))
    assert TopLinesReader(path).top_lines("ERCOT", "any").status == "unavailable"
    assert TopLinesReader(path).top_lines("PJM", "any").status == "unavailable"


def test_input_values_are_bound_and_reader_never_writes(tmp_path):
    path = tmp_path / "grid.duckdb"
    _db(path)
    result = TopLinesReader(path).top_lines("ERCOT' OR TRUE --", "any", 50)
    assert result.status == "unavailable"
    with duckdb.connect(str(path), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM line_upgrade_scores").fetchone() == (1,)


def test_invalid_direct_inputs_and_metadata_fail_closed(tmp_path):
    path = tmp_path / "grid.duckdb"
    _db(path)
    reader = TopLinesReader(path)
    assert reader.top_lines("ERCOT", "unknown").status == "unavailable"
    assert reader.top_lines("ERCOT", "any", 51).status == "unavailable"
    with duckdb.connect(str(path)) as con:
        con.execute("UPDATE line_upgrade_detail SET congestion_method = NULL")
    assert reader.top_lines("ERCOT", "any").status == "unavailable"
    with duckdb.connect(str(path)) as con:
        con.execute("UPDATE line_upgrade_detail SET congestion_method = 'exact'")
        con.execute("UPDATE line_upgrade_scores SET source_kind = NULL")
    assert reader.top_lines("ERCOT", "any").status == "unavailable"
