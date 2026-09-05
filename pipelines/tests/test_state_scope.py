from pathlib import Path

from pipelines.eaglei import load_eaglei
from pipelines.state_context import connect_context, context_db_path
from pipelines.state_scope import parse_states, scope, synthetic_topology_supported


def test_normalizes_full_name_fips_and_repeated_comma_state_inputs():
    assert scope(["MN,New York", "48"]).usps == ("MN", "NY", "TX")
    assert scope("Texas").fips == ("48",)
    assert parse_states(["NY,MN", "TX"]) == ("NY", "MN", "TX")


def test_non_texas_context_path_is_not_the_texas_store_and_has_no_topology_rows(tmp_path):
    path = context_db_path("MN", tmp_path)
    assert path == tmp_path / "context" / "mn.duckdb"
    assert not synthetic_topology_supported("MN")
    con = connect_context("MN", tmp_path)
    try:
        assert con.execute("SELECT count(*) FROM buses").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM lines").fetchone()[0] == 0
    finally:
        con.close()


def test_minnesota_eaglei_ingests_from_full_name_source_value(tmp_path):
    source = tmp_path / "outages.csv"
    source.write_text("fips_code,county,state,customers_out,run_start_time\n27001,Aitkin,Minnesota,2,2024-01-01 00:00:00\n")
    con = connect_context("MN", tmp_path)
    try:
        # The shared contract has an FK to counties; seed a legitimate context county via SQL only for this focused loader test.
        con.execute("""INSERT INTO counties VALUES ('27001','Aitkin','MN',1,?, 'test','test',NULL,NULL,'test')""", [bytes.fromhex("010300000000000000")])
        assert load_eaglei(con, str(source), 2024, "UTC", "MN") == 1
        assert con.execute("SELECT county_fips, customers_out FROM eaglei_outages").fetchall() == [("27001", 2)]
    finally:
        con.close()
