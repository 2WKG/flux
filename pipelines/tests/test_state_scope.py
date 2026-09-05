import pytest

from pipelines.eaglei import load_eaglei
from pipelines.state_context import connect_context, context_db_path
from pipelines.state_scope import parse_states, scope, synthetic_topology_supported


def test_normalizes_full_name_fips_and_repeated_comma_state_inputs():
    assert scope(["MN,New York", "48"]).usps == ("MN", "NY", "TX")
    assert scope("Texas").fips == ("48",)
    assert parse_states(["NY,MN", "TX"]) == ("NY", "MN", "TX")


def test_context_uses_shared_store_and_rejects_texas_topology_build(tmp_path):
    assert context_db_path("MN", tmp_path) == tmp_path / "grid.duckdb"
    assert context_db_path("WI", tmp_path) == context_db_path("MN", tmp_path)
    assert not synthetic_topology_supported("MN")
    with pytest.raises(ValueError, match="Texas P0"):
        connect_context("TX", tmp_path)


def test_minnesota_eaglei_ingests_from_full_name_source_value(tmp_path):
    source = tmp_path / "outages.csv"
    source.write_text(
        "fips_code,county,state,customers_out,run_start_time\n27001,Aitkin,Minnesota,2,2024-01-01 00:00:00\n"
    )
    con = connect_context("MN", tmp_path)
    try:
        # The shared contract has an FK to counties; seed a placeholder context county via SQL only for this focused loader test.
        con.execute(
            """INSERT INTO counties (county_fips,name,state,pop,geom_wkb,source_name,source_ref,source_version,source_retrieved_at,fixture_batch_id) VALUES ('27001','Aitkin','MN',1,?, 'test','test',NULL,NULL,'test')""",
            [bytes.fromhex("010300000000000000")],
        )
        assert load_eaglei(con, str(source), 2024, "UTC", "MN") == 1
        assert con.execute(
            "SELECT county_fips, customers_out FROM eaglei_outages"
        ).fetchall() == [("27001", 2)]
    finally:
        con.close()
