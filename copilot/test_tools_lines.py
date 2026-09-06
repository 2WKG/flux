"""Behavioural checks for `TopLinesReader` against the real DuckDB contract.

Fixtures are built through `pipelines.db.connect` (real `ensure_schema` DDL,
with its primary keys, foreign keys, CHECKs, and NOT NULLs) so a column rename
or constraint change in `pipelines/db.py` fails this suite instead of leaving a
hand-typed shadow schema green.
"""

from datetime import UTC, datetime

import duckdb
import pytest

from copilot.tools_lines import TopLinesReader
from pipelines.db import connect

SHA = "a" * 64
PROVENANCE = {
    "source_name": "fixture",
    "source_ref": "fixture-ref",
    "source_version": None,
    "source_retrieved_at": None,
    "fixture_batch_id": "batch-1",
}


def _insert(con, table, row):
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    con.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", list(row.values())
    )


def _seed_buses(con):
    for bus_id in (1, 2):
        _insert(
            con,
            "buses",
            {
                "bus_id": bus_id,
                "name": f"b{bus_id}",
                "base_kv": 230.0,
                "lon": -97.0,
                "lat": 31.0,
                "county_fips": None,
                "ba_code": "ERCO",
                "coord_source": "fixture",
                "zone": None,
                "area": None,
                **PROVENANCE,
            },
        )


def _add_line(con, line_id):
    _insert(
        con,
        "lines",
        {
            "line_id": line_id,
            "from_bus": 1,
            "to_bus": 2,
            "circuit": f"c{line_id}",
            "base_kv": 230.0,
            "r_pu": 0.01,
            "x_pu": 0.1,
            "rate_a_mw": 300.0,
            "length_km": 10.0,
            "geom_wkb": None,
            "is_transformer": False,
            **PROVENANCE,
        },
    )


def _add_ranking(
    con,
    line_id,
    *,
    scenario="uri_2021",
    region="ERCOT",
    score=20.0,
    dlr_cost=1_000_000.0,
    reconductor_cost=2_000_000.0,
    best_tech="dlr",
    method="exact",
    run_id=None,
    source_kind="fixture",
):
    contract = {
        "ranking_version": "v1",
        "contract_version": "1.0.0",
        "computed_at": datetime(2026, 1, 1, tzinfo=UTC),
        "simulation_run_id": run_id,
        "grid_input_sha256": SHA,
        "weather_input_sha256": None,
        "cost_params_sha256": SHA,
        "source_kind": source_kind,
    }
    _insert(
        con,
        "line_upgrade_scores",
        {
            "line_id": line_id,
            "scenario_id": scenario,
            "congestion_usd_yr": 100.0,
            "dlr_uplift_mw": 20.0,
            "reconductor_uplift_mw": 10.0,
            "dlr_cost_usd": dlr_cost,
            "reconductor_cost_usd": reconductor_cost,
            "mw_per_musd": score,
            "ferc_screen_pass": True,
            "spark_eligible": False,
            **contract,
            **PROVENANCE,
        },
    )
    _insert(
        con,
        "line_upgrade_detail",
        {
            "line_id": line_id,
            "scenario_id": scenario,
            "static_rating_mw": 400.0,
            "best_tech": best_tech,
            "congestion_method": method,
            "region": region,
            **contract,
            **PROVENANCE,
        },
    )


def _db(path, *, scenarios=("uri_2021",), source_kind="fixture"):
    con = connect(path)
    _seed_buses(con)
    for index, scenario in enumerate(scenarios, 1):
        _add_line(con, index)
        _add_ranking(
            con, index, scenario=scenario, score=20 - index, source_kind=source_kind
        )
    con.close()


# (line_id, score, dlr cost, simulation run, congestion method), designed so the
# ranked order ["3", "2", "1", "4"] differs from any line_id or insertion order:
# 3 has the best score; 1, 2 and 4 tie on score, 2 is cheaper, and 1 vs 4 tie on
# score AND cost so only the line_id key separates them.
RANKED_ROWS = {
    1: (20.0, 1_000_000.0, None, "exact"),
    2: (20.0, 500_000.0, "run-2", "exact"),
    3: (30.0, 1_000_000.0, None, "twin_proxy"),
    4: (20.0, 1_000_000.0, None, "fuzzy"),
}
RANKED_ORDER = ["3", "2", "1", "4"]


def _ranked_db(path, insertion_order):
    con = connect(path)
    _seed_buses(con)
    for line_id in insertion_order:
        score, dlr_cost, run_id, method = RANKED_ROWS[line_id]
        _add_line(con, line_id)
        _add_ranking(
            con, line_id, score=score, dlr_cost=dlr_cost, run_id=run_id, method=method
        )
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
        assert (
            TopLinesReader(path).top_lines("ERCOT", "any").provenance[0].source_kind
            == kind
        )


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
        assert con.execute("SELECT count(*) FROM line_upgrade_scores").fetchone() == (
            1,
        )


def test_invalid_direct_inputs_and_metadata_fail_closed(tmp_path):
    path = tmp_path / "grid.duckdb"
    _db(path)
    reader = TopLinesReader(path)
    assert reader.top_lines("ERCOT", "unknown").status == "unavailable"
    assert reader.top_lines("ERCOT", "any", 51).status == "unavailable"
    with duckdb.connect(str(path)) as con:
        # The real contract forbids a NULL method; the reader must still refuse
        # the one persisted method it has no source class for.
        with pytest.raises(duckdb.ConstraintException):
            con.execute("UPDATE line_upgrade_detail SET congestion_method = NULL")
        con.execute("UPDATE line_upgrade_detail SET congestion_method = 'unmapped'")
    assert reader.top_lines("ERCOT", "any").status == "unavailable"
    with duckdb.connect(str(path)) as con:
        con.execute("UPDATE line_upgrade_detail SET congestion_method = 'exact'")
        con.execute("UPDATE line_upgrade_scores SET source_kind = NULL")
    assert reader.top_lines("ERCOT", "any").status == "unavailable"


def test_final_output_separates_tech_filters_and_simulated_source_class(tmp_path):
    path = tmp_path / "grid.duckdb"
    _db(path)
    with duckdb.connect(str(path)) as con:
        con.execute("UPDATE line_upgrade_scores SET simulation_run_id = 'run-1'")
        con.execute("UPDATE line_upgrade_detail SET best_tech = 'reconductor'")
    result = TopLinesReader(path).top_lines("ERCOT", "reconductor", 1)
    assert result.lines[0].intervention_type == "reconductor"
    assert result.lines[0].source_class == "simulated"
    assert TopLinesReader(path).top_lines("ERCOT", "dlr", 1).lines == []


def test_ranking_orders_by_score_then_cost_then_line_id_and_truncates(tmp_path):
    path = tmp_path / "grid.duckdb"
    _ranked_db(path, insertion_order=[1, 2, 3, 4])
    result = TopLinesReader(path).top_lines("ERCOT", "any", 10)
    assert result.status == "available"
    assert [line.line_id for line in result.lines] == RANKED_ORDER
    assert [line.source_class for line in result.lines] == [
        "proxy",
        "simulated",
        "observed",
        "observed",
    ]
    top = TopLinesReader(path).top_lines("ERCOT", "any", 1)
    assert [line.line_id for line in top.lines] == RANKED_ORDER[:1]


def test_top_lines_is_reproducible_across_insertion_order_and_repeated_reads(
    tmp_path,
):
    forward = tmp_path / "forward.duckdb"
    reverse = tmp_path / "reverse.duckdb"
    _ranked_db(forward, insertion_order=[1, 2, 3, 4])
    _ranked_db(reverse, insertion_order=[4, 3, 2, 1])
    first = TopLinesReader(forward).top_lines("ERCOT", "any", 10)
    assert first.status == "available"
    assert len(first.lines) == len(RANKED_ROWS)
    expected = first.model_dump(mode="json")
    assert (
        TopLinesReader(reverse).top_lines("ERCOT", "any", 10).model_dump(mode="json")
        == expected
    )
    assert (
        TopLinesReader(forward).top_lines("ERCOT", "any", 10).model_dump(mode="json")
        == expected
    )


def test_rows_are_scoped_to_the_selected_scenario_partition(tmp_path):
    path = tmp_path / "grid.duckdb"
    con = connect(path)
    _seed_buses(con)
    for line_id in (1, 2, 3):
        _add_line(con, line_id)
    _add_ranking(con, 1, scenario="uri_2021", score=20.0)
    _add_ranking(con, 2, scenario="uri_2021", score=19.0)
    # A second same-region scenario with no score is not a ranking partition, so
    # `uri_2021` stays unambiguous; its rows must not leak into the ranking.
    _add_ranking(con, 3, scenario="beryl_2024", score=None)
    con.close()
    result = TopLinesReader(path).top_lines("ERCOT", "any", 10)
    assert result.status == "available"
    assert result.scenario_id == "uri_2021"
    assert [line.line_id for line in result.lines] == ["1", "2"]
    assert {line.scenario_id for line in result.lines} == {"uri_2021"}
