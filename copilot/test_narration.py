"""Behavioral coverage for grounded tool-result narration."""

from __future__ import annotations

import pytest

from copilot.narration import narrate
from copilot.tools.schemas import (
    ArtifactRef,
    CausalData,
    CiteData,
    LinesData,
    RetrievalHit,
    unavailable_output,
)


def _provenance(*, source_kind: str = "observed") -> list[ArtifactRef]:
    return [
        ArtifactRef(
            artifact_id="artifact-1",
            artifact_version="v1",
            source_kind=source_kind,  # type: ignore[arg-type]
            source_ref="source-1",
        )
    ]


def _hit(*, page: int = 4, chunk: int = 1, score: float = 1.0) -> RetrievalHit:
    return RetrievalHit(
        content_kind="source",
        date="2026-01-01",
        doc="mn-rule.pdf",
        locator=f"p. {page}",
        provenance={"retrieved_at": "2026-01-02T03:04:05Z"},
        source="https://example.test/mn-rule.pdf",
        title="Minnesota rule",
        page=page,
        chunk_id=f"mn-rule-p{page}-c{chunk}",
        score=score,
        text="Exact source excerpt.",
        version="2026-01-01",
    )


def _cite(*, hits: list[RetrievalHit] | None = None) -> CiteData:
    return CiteData(
        status="available",
        provenance=_provenance(source_kind="retrieval"),
        hits=hits if hits is not None else [_hit()],
    )


def test_citation_narration_preserves_exact_hit_and_retrieval_provenance() -> None:
    result = _cite()

    narration = narrate("cite", result)

    assert narration.status == "available"
    assert narration.text == "Accepted citation evidence is available."
    assert narration.citations == tuple(result.hits)
    assert narration.provenance == tuple(result.provenance)
    assert narration.evidence["hits"][0]["doc"] == "mn-rule.pdf"
    assert narration.evidence["hits"][0]["page"] == 4
    assert narration.evidence["hits"][0]["content_kind"] == "source"
    assert narration.evidence["hits"][0]["date"] == "2026-01-01"
    assert narration.evidence["hits"][0]["locator"] == "p. 4"
    assert narration.evidence["hits"][0]["provenance"] == {
        "retrieved_at": "2026-01-02T03:04:05Z"
    }
    assert narration.evidence["hits"][0]["source"] == "https://example.test/mn-rule.pdf"
    assert narration.evidence["hits"][0]["version"] == "2026-01-01"
    assert narration.limitations == ("Evidence source kind: retrieval.",)


def test_available_tool_narration_keeps_payload_but_does_not_invent_claims() -> None:
    result = LinesData(
        status="available",
        provenance=_provenance(source_kind="simulated"),
        region="MN",
        scenario_id="winter_2025",
        artifact_id="line-artifact",
        tech="any",
        lines=[],
    )

    narration = narrate("top_lines", result)

    assert narration.status == "available"
    assert narration.text == "An accepted top_lines result is available."
    assert narration.evidence == {
        "region": "MN",
        "scenario_id": "winter_2025",
        "artifact_id": "line-artifact",
        "tech": "any",
        "lines": (),
    }
    assert narration.citations == ()
    assert narration.limitations == ("Evidence source kind: simulated.",)
    assert "MN" not in narration.text
    assert "winter" not in narration.text


def test_unavailable_result_preserves_its_reason_without_answer_or_citation() -> None:
    result = unavailable_output(
        "artifact_unavailable",
        "citation corpus has not been provisioned",
        provenance=_provenance(source_kind="retrieval"),
    )

    narration = narrate("cite", result)

    assert narration.status == "unavailable"
    assert narration.text == "citation corpus has not been provisioned"
    assert narration.unavailable == result.unavailable
    assert narration.provenance == tuple(result.provenance)
    assert narration.evidence == {}
    assert narration.citations == ()


def test_empty_citation_result_fails_closed() -> None:
    narration = narrate("cite", _cite(hits=[]))

    assert narration.status == "unavailable"
    assert narration.unavailable.code == "insufficient_evidence"
    assert narration.evidence == {}
    assert narration.citations == ()


def test_causal_assumptions_are_preserved_as_limitations() -> None:
    variable = {
        "name": "outage duration",
        "definition": "hours without service",
        "unit_or_category": "hours",
        "source_id": "source-1",
    }
    result = CausalData(
        status="available",
        provenance=_provenance(),
        answer_numbers={"effect": 1.5},
        method="twfe_only",
        assumptions=["conditional exchangeability"],
        evidence_rows=[],
        question={
            "treatment": variable,
            "outcome": variable,
            "target_population": {
                "description": "test population",
                "geography": "MN",
                "time_window": "test period",
            },
        },
        sources=[
            {
                "source_id": "source-1",
                "name": "test source",
                "version": "v1",
                "locator": "table-1",
                "coverage": "test period",
            }
        ],
        sample={
            "unit": "county",
            "n_total": 2,
            "n_treated": 1,
            "n_control": 1,
            "period": "test period",
        },
        diagnostics=[{"name": "balance", "status": "pass", "evidence": "recorded"}],
        citations=[{"source_id": "source-1", "locator": "table-1"}],
    )

    narration = narrate("causal_query", result)

    assert narration.status == "available"
    assert narration.evidence["answer_numbers"] == {"effect": 1.5}
    assert narration.limitations == ("conditional exchangeability",)
    assert narration.citations == ()


def test_wrong_tool_type_and_unknown_tool_fail_closed() -> None:
    result = _cite()

    wrong_type = narrate("top_lines", result)
    unknown_tool = narrate("not-a-tool", result)

    assert wrong_type.status == "unavailable"
    assert wrong_type.unavailable.code == "invalid_prerequisite"
    assert unknown_tool.status == "unavailable"
    assert unknown_tool.unavailable.code == "unsupported_request"


def test_non_tool_output_input_fails_closed() -> None:
    as_dict = narrate("cite", {"status": "available", "hits": []})  # type: ignore[arg-type]
    as_none = narrate("cite", None)  # type: ignore[arg-type]

    for narration in (as_dict, as_none):
        assert narration.status == "unavailable"
        assert narration.unavailable.code == "invalid_prerequisite"
        assert narration.evidence == {}
        assert narration.citations == ()


def test_every_citation_hit_is_carried_in_order() -> None:
    hits = [
        _hit(page=4, chunk=1, score=0.9),
        _hit(page=7, chunk=2, score=0.8),
        _hit(page=9, chunk=1, score=0.7),
    ]
    result = _cite(hits=hits)

    narration = narrate("cite", result)

    assert narration.status == "available"
    assert len(narration.citations) == 3
    assert narration.citations == tuple(result.hits)
    assert [hit["chunk_id"] for hit in narration.evidence["hits"]] == [
        "mn-rule-p4-c1",
        "mn-rule-p7-c2",
        "mn-rule-p9-c1",
    ]


def test_every_provenance_ref_is_preserved() -> None:
    provenance = _provenance(source_kind="simulated") + [
        ArtifactRef(
            artifact_id="artifact-2",
            artifact_version="v3",
            source_kind="observed",
            source_ref="source-2",
        )
    ]
    result = LinesData(
        status="available",
        provenance=provenance,
        region="MN",
        scenario_id="winter_2025",
        artifact_id="line-artifact",
        tech="any",
        lines=[],
    )

    narration = narrate("top_lines", result)

    assert len(narration.provenance) == 2
    assert narration.provenance == tuple(result.provenance)
    assert narration.limitations == ("Evidence source kind: simulated.",)


def test_validation_bypassed_result_fails_closed() -> None:
    # ``model_construct`` skips validation: no ``doc`` and ``page=0`` would be
    # rejected by the contract, so the narration boundary must not trust it.
    bad_hit = RetrievalHit.model_construct(
        content_kind="source",
        date=None,
        locator="p. 0",
        provenance={},
        source="https://example.test/mn-rule.pdf",
        title="Minnesota rule",
        page=0,
        chunk_id="mn-rule-p0-c1",
        score=1.0,
        text="Exact source excerpt.",
        version="2026-01-01",
    )
    result = CiteData.model_construct(
        status="available",
        provenance=_provenance(source_kind="retrieval"),
        unavailable=None,
        hits=[bad_hit],
    )

    narration = narrate("cite", result)

    assert narration.status == "unavailable"
    assert narration.unavailable.code == "invalid_prerequisite"
    assert narration.text == "tool result failed contract validation"
    assert narration.evidence == {}
    assert narration.citations == ()


def test_evidence_is_immutable_all_the_way_down() -> None:
    narration = narrate("cite", _cite())

    with pytest.raises(TypeError):
        narration.evidence["hits"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        narration.evidence["hits"][0]["doc"] = "tampered.pdf"  # type: ignore[index]
    with pytest.raises(TypeError):
        narration.evidence["hits"][0]["provenance"]["retrieved_at"] = "never"  # type: ignore[index]
    with pytest.raises(AttributeError):
        narration.evidence["hits"].append({})  # type: ignore[attr-defined]
    assert narration.evidence["hits"][0]["doc"] == narration.citations[0].doc
