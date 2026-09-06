"""Behavioral tests for the static ``buses`` map layer through the real app.

The fixture mirrors the canonical ``buses`` DDL from ``pipelines/db.py`` on
master (``bus_id BIGINT``, ``coord_source TEXT NOT NULL``, provenance
columns, coordinate CHECKs); the foreign key to ``counties`` is omitted
because this fixture does not build that table.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.routes.layers import BUILT_LAYERS, DOCUMENTED_LAYERS

PROVENANCE_COLUMNS = """
    source_name TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_version TEXT,
    source_retrieved_at TIMESTAMP,
    fixture_batch_id TEXT NOT NULL
"""

BUSES_DDL = f"""
    CREATE TABLE buses (
        bus_id BIGINT PRIMARY KEY, name TEXT NOT NULL, base_kv DOUBLE NOT NULL CHECK (base_kv > 0),
        lon DOUBLE NOT NULL CHECK (lon BETWEEN -180 AND 180), lat DOUBLE NOT NULL CHECK (lat BETWEEN -90 AND 90),
        county_fips TEXT, ba_code TEXT, coord_source TEXT NOT NULL,
        zone INTEGER, area INTEGER, {PROVENANCE_COLUMNS})
"""

# An unconstrained twin of the contract table, for rows the DDL would reject.
LOOSE_BUSES_DDL = """
    CREATE TABLE buses (
        bus_id BIGINT, name TEXT, base_kv DOUBLE, lon DOUBLE, lat DOUBLE,
        county_fips TEXT, ba_code TEXT, coord_source TEXT, zone INTEGER, area INTEGER,
        source_name TEXT, source_ref TEXT, source_version TEXT,
        source_retrieved_at TIMESTAMP, fixture_batch_id TEXT)
"""

_ACTIVSG = (
    "ACTIVSg2000.aux (2018 build)",
    "pipelines.activsg",
    "matpower:case_ACTIVSg2000.m",
    "2018",
    "2026-09-05T12:00:00",
    "activsg2000@2018",
)
_FIXTURE = (
    "fixture:hand-placed",
    "fixture:flux-demo",
    "pipelines/fixtures/inputs/buses.json",
    "1.0.0",
    "2026-01-01T00:00:00",
    "fixture:flux-demo@1.0.0",
)
_PLAIN_FIXTURE = (
    "fixture:hand-placed",
    "fixture",
    "pipelines/fixtures/inputs/buses.json",
    "1.0.0",
    "2026-01-01T00:00:00",
    "fixture@1.0.0",
)


def _insert(
    connection: duckdb.DuckDBPyConnection, rows: list[tuple[object, ...]]
) -> None:
    if rows:
        connection.executemany(
            "INSERT INTO buses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def _row(
    bus_id: int, name: str, lon: object, lat: object, provenance=_ACTIVSG
) -> tuple:
    coord_source, *rest = provenance
    return (bus_id, name, 230.0, lon, lat, "48453", "ERCO", coord_source, 1, 1, *rest)


def _fixture_database(
    path: Path, *, rows: list[tuple[object, ...]] | None = None
) -> None:
    connection = duckdb.connect(str(path))
    connection.execute(BUSES_DDL)
    if rows is None:
        rows = [
            _row(2, "West", -97.5, 30.1),
            _row(10, "North", -97.0, 32.9),
            _row(1, "East", -96.1, 31.2),
        ]
    _insert(connection, rows)
    connection.close()


def _loose_database(path: Path, rows: list[tuple[object, ...]]) -> None:
    connection = duckdb.connect(str(path))
    connection.execute(LOOSE_BUSES_DDL)
    _insert(connection, rows)
    connection.close()


def _client(database: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=database)))


def test_buses_layer_is_bare_geojson_through_the_real_app(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get(
        "/layers/buses", headers={"X-Request-ID": "layer-1"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/geo+json")
    assert response.headers["X-Request-ID"] == "layer-1"
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert body["crs"] == {"type": "name", "properties": {"name": "EPSG:4326"}}
    assert body["layer"] == "buses"
    assert "status" not in body and "data" not in body  # unwrapped, per spec 00/05/06
    # BIGINT ids order numerically (2, 10, 1 -> 1, 2, 10), not lexicographically.
    assert [feature["id"] for feature in body["features"]] == ["1", "2", "10"]
    east = body["features"][0]
    assert east["geometry"] == {"type": "Point", "coordinates": [-96.1, 31.2]}
    assert east["properties"] == {
        "bus_id": "1",
        "name": "East",
        "kv": 230.0,
        "county_fips": "48453",
        "ba_code": "ERCO",
        "coord_source": "ACTIVSg2000.aux (2018 build)",
        "source_name": "pipelines.activsg",
    }
    assert body["attributes"]["kv"] == {
        "unit": "kV",
        "kind": "measure",
        "source": "buses.base_kv",
    }
    assert body["attributes"]["coord_source"]["source"] == "buses.coord_source"


def test_activsg_rows_carry_the_synthetic_topology_label_from_their_provenance(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    body = _client(database).get("/layers/buses").json()

    assert body["provenance"] == {
        "source_kinds": ["simulated"],
        "topology": "synthetic (ACTIVSg2000)",
        "topologies": ["synthetic (ACTIVSg2000)"],
        "source_names": ["pipelines.activsg"],
        "coord_sources": ["ACTIVSg2000.aux (2018 build)"],
        "fixture_batch_ids": ["activsg2000@2018"],
    }


def test_plain_fixture_source_name_is_labelled_fixture(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(
        database, rows=[_row(1, "Plain fixture", -96.1, 31.2, _PLAIN_FIXTURE)]
    )

    provenance = _client(database).get("/layers/buses").json()["provenance"]

    assert provenance["source_kinds"] == ["fixture"]
    assert provenance["source_names"] == ["fixture"]
    assert provenance["topology"] is None


def test_fixture_rows_are_labelled_fixture_not_hardcoded(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(
        database,
        rows=[
            _row(1, "East", -96.1, 31.2, _FIXTURE),
            _row(2, "West", -97.5, 30.1, _ACTIVSG),
        ],
    )

    provenance = _client(database).get("/layers/buses").json()["provenance"]

    assert provenance["source_kinds"] == ["fixture", "simulated"]
    assert provenance["source_names"] == ["fixture:flux-demo", "pipelines.activsg"]
    assert provenance["coord_sources"] == [
        "ACTIVSg2000.aux (2018 build)",
        "fixture:hand-placed",
    ]
    assert provenance["topology"] == "synthetic (ACTIVSg2000)"


def test_rows_without_provenance_are_refused_with_a_named_reason(
    tmp_path: Path,
) -> None:
    database = tmp_path / "loose.duckdb"
    _loose_database(
        database,
        [
            (
                7,
                "No coord source",
                230.0,
                -96.1,
                31.2,
                "48453",
                "ERCO",
                None,
                1,
                1,
                "pipelines.activsg",
                "ref",
                None,
                None,
                "batch",
            )
        ],
    )

    response = _client(database).get("/layers/buses")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["error"]["details"] == {
        "artifact": "buses",
        "reason": "provenance_missing",
        "bus_id": "7",
        "column": "coord_source",
    }


def test_annotated_bus_layer_scales_draw_and_marks_missing_ba_hour_unavailable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "annotated.duckdb"
    _fixture_database(
        database, rows=[_row(1, "Both", -96.1, 31.2), _row(2, "Consumer", -97.5, 30.1)]
    )
    con = duckdb.connect(str(database))
    con.execute(
        "CREATE TABLE gens (gen_id BIGINT, bus_id BIGINT, fuel TEXT, pmax_mw DOUBLE)"
    )
    con.execute(
        "CREATE TABLE loads (load_id BIGINT, bus_id BIGINT, p_mw_nominal DOUBLE)"
    )
    con.execute("CREATE TABLE counties (county_fips TEXT, name TEXT)")
    con.execute(
        "CREATE TABLE critical_loads (cl_id BIGINT, kind TEXT, name TEXT, bus_id BIGINT)"
    )
    con.execute("CREATE TABLE scenarios (scenario_id TEXT, ts_start TIMESTAMP)")
    con.execute(
        "CREATE TABLE ba_load_hourly (ba_code TEXT, ts TIMESTAMP, demand_mw DOUBLE)"
    )
    con.execute("INSERT INTO gens VALUES (1, 1, 'gas', 40)")
    con.execute("INSERT INTO loads VALUES (1, 1, 10), (2, 2, 5)")
    con.execute("INSERT INTO counties VALUES ('48453', 'Travis')")
    con.execute("INSERT INTO critical_loads VALUES (7, 'hospital', 'Central', 1)")
    con.execute("INSERT INTO scenarios VALUES ('storm', '2024-01-01 00:00:00')")
    con.execute(
        "INSERT INTO ba_load_hourly VALUES ('ERCO', '2024-01-01 00:00:00', 100), ('ERCO', '2024-01-01 01:00:00', 150)"
    )
    con.close()

    response = _client(database).get("/layers/buses?scenario_id=storm&hour=1")

    assert response.status_code == 200
    both, consumer = response.json()["features"]
    assert both["properties"]["role"] == "both"
    assert both["properties"]["generation_capacity_mw"] == 40
    assert both["properties"]["draw_mw"] == 15
    assert both["properties"]["county_name"] == "Travis"
    assert both["properties"]["critical_loads"] == [
        {"cl_id": 7, "name": "Central", "kind": "hospital"}
    ]
    assert both["properties"]["field_provenance"]["lon"] == "synthetic"
    assert both["properties"]["field_provenance"]["county_name"] == "source_backed"
    assert consumer["properties"]["draw_mw"] == 7.5

    con = duckdb.connect(str(database))
    con.execute("DELETE FROM ba_load_hourly WHERE ts = '2024-01-01 01:00:00'")
    con.close()
    missing = (
        _client(database)
        .get("/layers/buses?scenario_id=storm&hour=1")
        .json()["features"]
    )
    assert all(feature["properties"]["draw_mw"] is None for feature in missing)
    assert all(
        feature["properties"]["draw_status"] == "unavailable" for feature in missing
    )


@pytest.mark.parametrize("variant", ["empty", "all-null-geometry"])
def test_empty_or_unmappable_table_is_unavailable_not_an_empty_success(
    tmp_path: Path, variant: str
) -> None:
    database = tmp_path / f"{variant}.duckdb"
    if variant == "empty":
        _fixture_database(database, rows=[])
    else:
        _loose_database(
            database,
            [_row(1, "Nowhere", None, None)],
        )

    response = _client(database).get("/layers/buses")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["data"] is None
    assert body["error"]["code"] == "unavailable"
    assert body["error"]["details"] == {"artifact": "buses", "reason": "no_rows"}


def test_missing_buses_table_is_the_shared_unavailable_response(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    duckdb.connect(str(database)).close()

    response = _client(database).get("/layers/buses")

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "unavailable",
        "message": "The buses artifact is unavailable.",
        "retryable": True,
        "retry_after_s": 30,
        "details": {"artifact": "buses", "reason": "missing"},
    }


def test_missing_database_file_names_the_database_artifact(tmp_path: Path) -> None:
    response = _client(tmp_path / "missing.duckdb").get("/layers/buses")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "database",
        "reason": "missing",
    }


def test_schema_drift_is_a_named_schema_mismatch_not_a_500(tmp_path: Path) -> None:
    database = tmp_path / "drift.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute(
        "CREATE TABLE buses (bus_id BIGINT, name TEXT, lon DOUBLE, lat DOUBLE, "
        "county_fips TEXT, ba_code TEXT)"
    )
    connection.execute(
        "INSERT INTO buses VALUES (1, 'No kv', -96.1, 31.2, '48453', 'ERCO')"
    )
    connection.close()

    response = _client(database).get("/layers/buses")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "buses",
        "reason": "schema_mismatch",
    }


def test_non_numeric_coordinates_are_invalid_geometry_not_a_500(tmp_path: Path) -> None:
    database = tmp_path / "text-coords.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute(
        "CREATE TABLE buses (bus_id BIGINT, name TEXT, base_kv DOUBLE, lon VARCHAR, lat VARCHAR, "
        "county_fips TEXT, ba_code TEXT, coord_source TEXT, zone INTEGER, area INTEGER, "
        "source_name TEXT, source_ref TEXT, source_version TEXT, source_retrieved_at TIMESTAMP, "
        "fixture_batch_id TEXT)"
    )
    _insert(connection, [_row(1, "Words", "west", "north")])
    connection.close()

    response = _client(database).get("/layers/buses")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "buses",
        "reason": "invalid_geometry",
    }


@pytest.mark.parametrize(
    ("lon", "lat"),
    [(31.2, -97.5), (-96.1, 91.0), (181.0, 31.2), (-96.1, -90.5)],
    ids=["swapped-columns", "lat-over-90", "lon-over-180", "lat-under-minus-90"],
)
def test_out_of_range_coordinates_are_refused_by_bus(
    tmp_path: Path, lon: float, lat: float
) -> None:
    database = tmp_path / "range.duckdb"
    _loose_database(database, [_row(1, "East", -96.1, 31.2), _row(2, "Bad", lon, lat)])

    response = _client(database).get("/layers/buses")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "buses",
        "reason": "invalid_geometry",
        "bus_id": "2",
    }


@pytest.mark.parametrize("layer", sorted(DOCUMENTED_LAYERS - BUILT_LAYERS))
def test_documented_but_unbuilt_layers_are_unavailable_not_built(
    tmp_path: Path, layer: str
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get(f"/layers/{layer}")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["data"] is None
    assert body["error"]["code"] == "unavailable"
    assert body["error"]["details"] == {"artifact": layer, "reason": "not_built"}


@pytest.mark.parametrize("layer", ["bus", "busses", "line", "national_hex2"])
def test_well_formed_undocumented_layer_is_not_found_not_an_empty_success(
    tmp_path: Path, layer: str
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get(f"/layers/{layer}")

    assert response.status_code == 404
    assert response.json()["status"] == "error"
    assert response.json()["data"] is None
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["details"] == {"layer": layer}


@pytest.mark.parametrize(
    "layer",
    ["not-a-layer", "BUSES", "Buses", "1lines", "b" * 33, "a%2Fb", "%C3%BCri", "a.b"],
)
def test_malformed_layer_name_is_invalid_input_before_any_lookup(
    tmp_path: Path, layer: str
) -> None:
    # A missing database must not matter: shape validation runs first.
    response = _client(tmp_path / "missing.duckdb").get(f"/layers/{layer}")

    assert response.status_code in (404, 422)
    body = response.json()
    assert body["status"] == "error"
    assert body["data"] is None
    if response.status_code == 422:
        assert body["error"] == {
            "code": "invalid_input",
            "message": "Request parameters do not match the documented contract.",
            "retryable": False,
            "retry_after_s": None,
            "details": {"field": "path.layer_name"},
        }
    else:
        # ``a%2Fb`` decodes to two path segments and misses every route; it
        # still gets the versioned envelope, never a raw {"detail": "Not Found"}.
        assert layer == "a%2Fb"
        assert body["error"]["code"] == "not_found"
        assert body["error"]["message"] == "No route matches the request path."
    assert body["meta"]["request_id"] == response.headers["X-Request-ID"]


def test_lines_is_documented_but_not_built(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get("/layers/lines")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["error"]["details"] == {
        "artifact": "lines",
        "reason": "not_built",
    }


def test_layers_root_is_an_enveloped_not_found(tmp_path: Path) -> None:
    response = _client(tmp_path / "missing.duckdb").get("/layers/")

    assert response.status_code == 404
    body = response.json()
    assert body["status"] == "error"
    assert body["data"] is None
    assert body["error"]["code"] == "not_found"
    assert body["meta"]["request_id"] == response.headers["X-Request-ID"]


def test_non_404_http_errors_keep_fastapi_status_headers_and_body(
    tmp_path: Path,
) -> None:
    response = _client(tmp_path / "missing.duckdb").post("/layers/buses")

    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
    assert response.json() == {"detail": "Method Not Allowed"}
