from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from siting.candidate_source import (
    MAX_SYNTHETIC_PRODUCER_CANDIDATES,
    MIN_INTERCONNECT_KV,
    SyntheticCandidateSourceUnavailable,
    _generator_rows,
    producer_candidates,
)
from siting.search import (
    CANDIDATE_POPULATION_DECLARED,
    CANDIDATE_POPULATION_SYNTHETIC_SUBSTITUTE,
    SearchAdapters,
    SearchUnavailable,
    search_locations,
)
from twin.build import build_network
from twin.contracts import SYNTHETIC_TOPOLOGY_LABEL


def _source_db(
    tmp_path: Path, *, generators: int = 7, sub_threshold_bus: int | None = None
) -> Path:
    path = tmp_path / "synthetic-grid.duckdb"
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
        con.executemany(
            "INSERT INTO buses VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    index,
                    f"synthetic bus {index}",
                    115.0 if index == sub_threshold_bus else 230.0,
                    -100.0 - index,
                    30.0 + index,
                    "48001",
                )
                for index in range(1, generators + 1)
            ],
        )
        con.executemany(
            "INSERT INTO gens VALUES (?, ?, ?, ?)",
            [
                (index, index, "synthetic", float(100 + index))
                for index in range(1, generators + 1)
            ],
        )
        con.execute("INSERT INTO loads VALUES (1, 1, 20.0)")
    return path


def _screening_adapters() -> SearchAdapters:
    def cascade(**kwargs):
        candidate = next(
            (
                edit["element_id"]
                for edit in kwargs["edits"]
                if edit["kind"] == "add_gen"
            ),
            "baseline",
        )
        generator_id = (
            int(candidate.rsplit(":", 1)[-1]) if candidate != "baseline" else 0
        )
        return {
            "lost_load_mwh": float(100 - generator_id),
            "congestion_mwh": 100.0,
            "evaluation_scope": "synthetic_fixture",
        }

    return SearchAdapters(
        feasibility=lambda **kwargs: {"feasible": True},
        redundancy=lambda **kwargs: {"score": 1.0},
        cascade=cascade,
        edit_factory=lambda **kwargs: {
            key: value for key, value in kwargs.items() if value is not None
        },
    )


def test_candidates_are_bounded_deterministic_json_safe_and_duckdb_derived(
    tmp_path: Path,
) -> None:
    net = build_network(_source_db(tmp_path))

    first = producer_candidates(net)
    second = producer_candidates(net)

    assert first == second
    assert len(first) == MAX_SYNTHETIC_PRODUCER_CANDIDATES
    assert [row["candidate_id"] for row in first] == [
        f"synthetic-generator:{index}"
        for index in range(1, MAX_SYNTHETIC_PRODUCER_CANDIDATES + 1)
    ]
    assert first[0]["bus_id"] == 1
    assert first[0]["source_capacity_mw"] == 101.0
    assert first[0]["interconnect_distance_km"] == 0.0
    provenance = first[0]["candidate_provenance"]
    assert provenance["source_kind"] == "synthetic_topology_derived"
    assert provenance["topology"] == SYNTHETIC_TOPOLOGY_LABEL
    assert provenance["source_bus_id"] == 1
    assert "not a physical site" in provenance["derivation"]
    json.dumps(first, allow_nan=False)


def test_generator_lookup_accepts_declared_native_sgen_list_metadata() -> None:
    # The native-PPC builder path represents lookup locations as lists and
    # can map a source generator to pandapower's static-generator table.
    assert _generator_rows(
        {"generator:1": ["ext_grid", 0], "generator:2": ["sgen", 4]}
    ) == [
        ("generator:1", "ext_grid", 0),
        ("generator:2", "sgen", 4),
    ]


def test_zero_capacity_generator_is_not_an_attachment_candidate(tmp_path: Path) -> None:
    net = build_network(_source_db(tmp_path, generators=6))
    # Generator 2 is the first normal ``gen`` row; a zero declared nameplate
    # supplies no actual source capacity for the candidate population.
    net.gen.at[0, "pmax_mw"] = 0.0

    assert [row["candidate_id"] for row in producer_candidates(net)] == [
        "synthetic-generator:1",
        "synthetic-generator:3",
        "synthetic-generator:4",
        "synthetic-generator:5",
        "synthetic-generator:6",
    ]


def test_search_uses_synthetic_generator_bus_source_without_candidate_tables(
    tmp_path: Path,
) -> None:
    net = build_network(_source_db(tmp_path))
    assert net.get("site_candidates") is None
    assert net.get("producer_candidates") is None

    results = search_locations(
        net,
        kind="producer",
        unit_mw=300.0,
        scenario_id="interactive",
        n=2,
        hour=0,
        adapters=_screening_adapters(),
    )

    assert [row["candidate_id"] for row in results] == [
        "synthetic-generator:5",
        "synthetic-generator:4",
    ]
    assert all(
        row["candidate_provenance"]["source_kind"] == "synthetic_topology_derived"
        for row in results
    )
    json.dumps(results, allow_nan=False)


def test_missing_source_metadata_fails_closed(tmp_path: Path) -> None:
    net = build_network(_source_db(tmp_path, generators=1))
    net.pop("flux_input_sha256")

    with pytest.raises(SyntheticCandidateSourceUnavailable, match="flux_input_sha256"):
        producer_candidates(net)
    with pytest.raises(SearchUnavailable, match="flux_input_sha256"):
        search_locations(
            net,
            kind="producer",
            unit_mw=300.0,
            scenario_id="interactive",
            adapters=_screening_adapters(),
        )


def test_synthetic_topology_label_literal_is_pinned(tmp_path: Path) -> None:
    # Nothing else under twin/ pins this literal, so a relabel to a permitting
    # claim would otherwise stay green everywhere.
    assert SYNTHETIC_TOPOLOGY_LABEL == "synthetic (ACTIVSg2000)"

    net = build_network(_source_db(tmp_path, generators=1))
    provenance = producer_candidates(net)[0]["candidate_provenance"]
    assert provenance["topology"] == "synthetic (ACTIVSg2000)"


def test_interconnect_voltage_floor_matches_the_spec_and_excludes_low_buses(
    tmp_path: Path,
) -> None:
    # docs/specs/04-siting-engine.md:75-77 keeps buses at base_kv >= 138 and
    # drops every 115 kV bus.
    assert MIN_INTERCONNECT_KV == 138.0

    net = build_network(_source_db(tmp_path, generators=4, sub_threshold_bus=3))

    assert [row["candidate_id"] for row in producer_candidates(net)] == [
        "synthetic-generator:1",
        "synthetic-generator:2",
        "synthetic-generator:4",
    ]


def test_substituted_candidate_population_is_declared_in_every_result(
    tmp_path: Path,
) -> None:
    # The spec'd site_candidates table is absent, so search substitutes a
    # DIFFERENT population (generator buses, interconnect_distance_km 0.0).
    # That substitution must be visible to a consumer without inspecting the
    # nested per-candidate provenance.
    net = build_network(_source_db(tmp_path))
    assert net.get("site_candidates") is None
    assert net.get("producer_candidates") is None

    results = search_locations(
        net,
        kind="producer",
        unit_mw=300.0,
        scenario_id="interactive",
        n=2,
        hour=0,
        adapters=_screening_adapters(),
    )

    assert results
    assert CANDIDATE_POPULATION_SYNTHETIC_SUBSTITUTE != CANDIDATE_POPULATION_DECLARED
    assert CANDIDATE_POPULATION_SYNTHETIC_SUBSTITUTE == (
        "synthetic_generator_bus_substitute"
    )
    for row in results:
        assert row["candidate_population"] == CANDIDATE_POPULATION_SYNTHETIC_SUBSTITUTE
        assert row["candidate_population"] != CANDIDATE_POPULATION_DECLARED
    json.dumps(results, allow_nan=False)


def test_declared_candidate_table_is_not_reported_as_the_substitute(
    tmp_path: Path,
) -> None:
    # With the spec'd table present the substitution never happens, so the two
    # populations stay distinguishable and provenance is absent, not [].
    net = build_network(_source_db(tmp_path))
    net["site_candidates"] = [
        {"candidate_id": "site:coal_retired:1", "bus_id": 1},
        {"candidate_id": "site:doe_federal:2", "bus_id": 2},
    ]

    results = search_locations(
        net,
        kind="producer",
        unit_mw=300.0,
        scenario_id="interactive",
        n=2,
        hour=0,
        adapters=_screening_adapters(),
    )

    assert sorted(row["candidate_id"] for row in results) == [
        "site:coal_retired:1",
        "site:doe_federal:2",
    ]
    for row in results:
        assert row["candidate_population"] == CANDIDATE_POPULATION_DECLARED
        # A mapping-valued field must not default to a list: a consumer doing
        # row["candidate_provenance"]["source_kind"] needs an honest absence.
        assert row["candidate_provenance"] is None
