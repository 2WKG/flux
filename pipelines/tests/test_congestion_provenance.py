from pipelines.congestion import parse_congestion_inputs

SHA = "a" * 64


def test_each_classification_persists_deterministic_contract_safe_provenance():
    inputs = [
        {
            "source": "observed",
            "usd_per_year": 1250.0,
            "market": "ERCOT SCED",
            "input_sha256": SHA,
            "mapping_confidence": 1.0,
            "mapping_method": "exact",
            "scenario": "summer-peak",
            "timestamp": "2026-07-01T15:00:00Z",
        },
        {
            "source": "simulated",
            "usd_per_year": 5.0,
            "run_id": "run-1",
        },
        {
            "source": "proxy",
            "usd_per_year": 4.0,
            "assumed_usd_per_mwh": 20.0,
            "assumption_note": "replay",
        },
    ]

    first = parse_congestion_inputs(inputs)
    second = parse_congestion_inputs(inputs)

    assert [item.provenance.input_sha256 for item in first] == [
        item.provenance.input_sha256 for item in second
    ]
    assert first[0].provenance.source_identifier == "ERCOT SCED"
    assert first[0].provenance.scenario == "summer-peak"
    assert first[0].provenance.timestamp == "2026-07-01T15:00:00Z"
    assert first[0].provenance.assumptions == ()
    assert first[1].provenance.source_identifier == "run-1"
    assert first[1].provenance.scenario is None
    assert first[1].provenance.timestamp is None
    assert first[2].provenance.source_identifier is None
    assert first[2].provenance.assumptions == (
        ("assumed_usd_per_mwh", 20.0),
        ("assumption_note", "replay"),
    )


def test_input_hash_is_independent_of_mapping_order():
    observed = {
        "source": "observed",
        "usd_per_year": 1250.0,
        "market": "ERCOT SCED",
        "input_sha256": SHA,
        "mapping_confidence": 1.0,
        "mapping_method": "exact",
    }

    forward = parse_congestion_inputs([observed])[0]
    reverse = parse_congestion_inputs([dict(reversed(observed.items()))])[0]

    assert forward.provenance.input_sha256 == reverse.provenance.input_sha256
