"""Post-answer verification for one Copilot answer attempt (spec 05 §Verification).

The model narrates; it never computes.  This module checks the final text
against the evidence that was actually produced during the attempt:

- **Number trace** -- every numeral in the text must appear in a tool result
  (exactly, or after rounding the tool value to the printed precision).
  Regulatory references (``10 CFR 100``, ``EO 14301``), page locators
  (``p. 12``), ISO dates, and FIPS codes are exempt because they identify a
  source rather than state a quantity.
- **Citation trace** -- every ``[doc p.N]`` marker must name a ``cite`` hit
  returned in this attempt (``doc`` and ``page`` exact).
- **Regulatory-claim guard** -- text that invokes a regulator or rule with no
  ``cite`` hit is unverified with ``reason="regulatory_claim_without_cite"``.

It never edits the text and never fabricates evidence: the result is a label
for the ``done`` terminal, and an empty trace is reported as such.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

REGULATORY_CLAIM_WITHOUT_CITE = "regulatory_claim_without_cite"

_EXEMPT_SPANS = (
    re.compile(r"\[[^\]\n]*\bp\.\s?\d+\]"),  # [doc p.N] citation markers
    re.compile(r"\b\d+\s+CFR\s+(?:Part\s+)?\d+(?:\.\d+)?", re.IGNORECASE),
    re.compile(r"§\s?\d+(?:\.\d+)*"),
    re.compile(r"\bEO\s?\d{5}\b|\bExecutive Order\s+\d+\b", re.IGNORECASE),
    re.compile(r"\b(?:p\.|page)\s?\d+\b", re.IGNORECASE),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\bFIPS\s+\d{5}\b", re.IGNORECASE),
)
_NUMERAL = re.compile(
    r"(?<![\w.])\$?(?P<digits>\d{1,3}(?:,\d{3})+|\d+)(?P<fraction>\.\d+)?"
    r"(?P<multiplier>[kMB])?(?=\b|[^\w.])"
)
_CITATION_MARKER = re.compile(r"\[(?P<doc>[^\]\s]+)\s+p\.\s?(?P<page>\d+)\]")
_REGULATORY = re.compile(
    r"\bNRC\b|\b10 CFR\b|\bDOE\b|\bFERC\b|executive order|\bEO 14\d{3}\b"
    r"|ADVANCE Act|Reg(?:ulatory)? Guide",
    re.IGNORECASE,
)
_MULTIPLIERS = {"k": 1e3, "M": 1e6, "B": 1e9}


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """The outcome of the three traces for one final text."""

    unverified_numbers: tuple[str, ...]
    unverified_citations: tuple[str, ...]
    reason: str | None

    @property
    def verified(self) -> bool:
        return (
            not self.unverified_numbers
            and not self.unverified_citations
            and self.reason is None
        )


def verify(
    final_text: str,
    tool_results: Iterable[object],
    citations: Sequence[object],
) -> VerificationReport:
    """Trace ``final_text`` against the attempt's tool results and cite hits."""

    evidence_values: set[float] = set()
    for result in tool_results:
        _collect_numbers(result, evidence_values)
    cited: set[tuple[str, int]] = set()
    for hit in citations:
        doc, page, excerpt = _hit_identity(hit)
        cited.add((doc, page))
        _collect_numbers(excerpt, evidence_values)
        evidence_values.add(float(page))

    unverified_numbers = tuple(
        printed
        for printed, value, decimals in _numerals(final_text)
        if not _traced(value, decimals, evidence_values)
    )
    unverified_citations = tuple(
        f"[{match.group('doc')} p.{match.group('page')}]"
        for match in _CITATION_MARKER.finditer(final_text)
        if (match.group("doc"), int(match.group("page"))) not in cited
    )
    reason = None
    if not citations and _REGULATORY.search(final_text):
        reason = REGULATORY_CLAIM_WITHOUT_CITE
    return VerificationReport(
        unverified_numbers=unverified_numbers,
        unverified_citations=unverified_citations,
        reason=reason,
    )


def _numerals(text: str) -> list[tuple[str, float, int]]:
    """Return ``(printed, value, printed_decimals)`` for every traceable numeral."""

    scrubbed = text
    for pattern in _EXEMPT_SPANS:
        scrubbed = pattern.sub(lambda match: " " * len(match.group(0)), scrubbed)
    found: list[tuple[str, float, int]] = []
    for match in _NUMERAL.finditer(scrubbed):
        digits = match.group("digits")
        fraction = match.group("fraction") or ""
        printed = digits + fraction
        value = float(digits.replace(",", "") + fraction)
        decimals = len(fraction) - 1 if fraction else 0
        multiplier = match.group("multiplier")
        if multiplier:
            value *= _MULTIPLIERS[multiplier]
            # Rounding tolerance applies to the printed digits, not to the
            # scaled value: "1.2k" claims 1200 exactly.
            decimals = 0
        found.append((printed, value, decimals))
    return found


def _traced(value: float, decimals: int, evidence: set[float]) -> bool:
    for candidate in evidence:
        if math.isclose(candidate, value, rel_tol=0, abs_tol=1e-9):
            return True
        if math.isclose(round(candidate, decimals), value, rel_tol=0, abs_tol=1e-9):
            return True
    return False


def _collect_numbers(value: object, into: set[float]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return
        into.add(float(value))
        return
    if isinstance(value, str):
        for _, number, _ in _numerals(value):
            into.add(number)
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _collect_numbers(item, into)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _collect_numbers(item, into)
        return
    if hasattr(value, "model_dump"):
        _collect_numbers(value.model_dump(mode="json"), into)
        return
    # Unknown objects are serialized defensively; numbers inside still count.
    try:
        _collect_numbers(json.loads(json.dumps(value, default=str)), into)
    except (TypeError, ValueError):
        return


def _hit_identity(hit: object) -> tuple[str, int, str]:
    data: Mapping[str, Any]
    if isinstance(hit, Mapping):
        data = hit
    elif hasattr(hit, "model_dump"):
        data = hit.model_dump(mode="json")
    else:
        data = {
            "doc": getattr(hit, "doc", None),
            "page": getattr(hit, "page", None),
            "text": getattr(hit, "text", None),
        }
    doc = data.get("doc")
    page = data.get("page")
    if not isinstance(doc, str) or not doc:
        raise ValueError("citation hit requires a non-empty doc")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("citation hit requires a positive integer page")
    excerpt = data.get("excerpt", data.get("text"))
    return doc, page, excerpt if isinstance(excerpt, str) else ""
