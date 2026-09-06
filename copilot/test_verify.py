"""Unit tests for the post-answer verification traces (spec 05 §Verification)."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from copilot.tools.schemas import RetrievalHit
from copilot.verify import REGULATORY_CLAIM_WITHOUT_CITE, verify


def _hit(doc: str = "10cfr100", page: int = 12, text: str = "e") -> RetrievalHit:
    return RetrievalHit(
        content_kind="source",
        date="2026-01-01",
        doc=doc,
        locator=f"p. {page}",
        provenance={"retrieved_at": "2026-01-02T00:00:00Z"},
        source="https://example.test/d",
        title="10 CFR Part 100",
        page=page,
        chunk_id=f"{doc}-p{page}-c1",
        score=1.0,
        text=text,
        version="2026-01-01",
    )


def test_planted_number_lands_in_unverified_numbers() -> None:
    """Spec 05 acceptance 8: the made-up ``999 MWh`` is caught."""
    report = verify(
        "This site reduces loss-of-load by 999 MWh.",
        [{"site_id": "site_tx_0007", "lol_reduction_mwh": 1240}],
        [],
    )

    assert report.unverified_numbers == ("999",)
    assert report.verified is False


def test_numbers_trace_exactly_or_after_rounding_to_printed_precision() -> None:
    report = verify(
        "About 1,240 MWh (82.1%) for $5k across 300 MW.",
        [{"lol": 1239.6, "pct": 82.13, "cost": 5000, "unit_mw": 300}],
        [],
    )

    assert report.unverified_numbers == ()
    assert report.verified is True


def test_rounding_tolerance_does_not_accept_a_different_value() -> None:
    report = verify("About 1,240 MWh.", [{"lol": 1234.4}], [])

    assert report.unverified_numbers == ("1,240",)


def test_multiplier_suffix_is_reported_as_printed() -> None:
    report = verify("Roughly $5k of the 3M budget.", [{"cost": 5000}], [])

    assert report.unverified_numbers == ("3M",)


def test_source_identifiers_are_exempt_from_the_number_trace() -> None:
    text = (
        "Per 10 CFR 100.21 and § 100.10, EO 14301 (p. 12; page 3) on 2026-01-01 "
        "for FIPS 48201 [10cfr100 p.12]."
    )

    report = verify(text, [], [_hit()])

    assert report.unverified_numbers == ()
    assert report.unverified_citations == ()
    assert report.verified is True


def test_numbers_inside_frozen_nested_evidence_count_as_traced() -> None:
    evidence = MappingProxyType(
        {"hits": (MappingProxyType({"score": 82.1, "rows": (7,)}),)}
    )

    report = verify("Score 82.1 across 7 rows.", [evidence], [])

    assert report.verified is True


def test_numbers_inside_cited_excerpts_and_pages_count_as_traced() -> None:
    report = verify(
        "Density limits apply within 4 miles [10cfr100 p.12].",
        [],
        [_hit(text="population within 4 miles of the site")],
    )

    assert report.verified is True


def test_citation_marker_must_name_a_returned_hit() -> None:
    report = verify(
        "See [10cfr100 p.12] and [10cfr100 p.13] and [other p.12].",
        [],
        [_hit(page=12)],
    )

    assert report.unverified_citations == ("[10cfr100 p.13]", "[other p.12]")
    assert report.verified is False


@pytest.mark.parametrize(
    "text",
    [
        "The NRC requires it.",
        "Under 10 CFR 100 the site must be reviewed.",
        "The DOE may authorize it.",
        "An executive order covers federal land.",
        "EO 14301 applies.",
        "The ADVANCE Act brownfield path.",
        "Reg Guide 4.7 discusses siting.",
    ],
)
def test_regulatory_claim_without_cite_is_unverified(text: str) -> None:
    report = verify(text, [{"ok": True}], [])

    assert report.reason == REGULATORY_CLAIM_WITHOUT_CITE
    assert report.verified is False


def test_regulatory_claim_with_a_cite_hit_carries_no_reason() -> None:
    report = verify("Under 10 CFR 100 [10cfr100 p.12].", [], [_hit()])

    assert report.reason is None
    assert report.verified is True


def test_report_is_a_label_not_an_edit() -> None:
    text = "reduces loss-of-load by 999 MWh"
    report = verify(text, [], [])

    assert report.unverified_numbers == ("999",)
    # No field of the report contains rewritten answer text.
    assert all(
        not isinstance(value, str) or value == REGULATORY_CLAIM_WITHOUT_CITE
        for value in (report.reason,)
    )


def test_citation_hit_identity_is_validated() -> None:
    with pytest.raises(ValueError, match="non-empty doc"):
        verify("x", [], [{"doc": "", "page": 1}])
    with pytest.raises(ValueError, match="positive integer page"):
        verify("x", [], [{"doc": "d", "page": "1"}])
