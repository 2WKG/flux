"""Fail-closed narration of accepted Copilot tool results.

The narration boundary intentionally does not call a model.  It receives one
already-validated tool result and returns a small, deterministic summary plus
the exact evidence needed by a later UI or provider runtime.  That keeps
availability, provenance, citations, and limitations attached to the result
that established them instead of asking prose generation to recreate facts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from pydantic import ValidationError

from copilot.tools.schemas import (
    TOOL_REGISTRY,
    ArtifactRef,
    CausalData,
    CiteData,
    RetrievalHit,
    ToolOutput,
    Unavailable,
    UnavailableCode,
    UnavailableOutput,
)


@dataclass(frozen=True)
class GroundedNarration:
    """A deterministic narration whose facts come from one accepted result.

    ``evidence`` is the tool's typed payload excluding transport metadata.  It
    is intentionally kept beside the summary so a later provider or browser
    cannot turn a status-only sentence into an unsupported operational, legal,
    or physical claim.  It is frozen all the way down (nested mappings become
    read-only views and nested lists become tuples) so a renderer cannot make
    ``evidence`` disagree with ``citations``.  ``citations`` contain only hits
    returned by ``cite``.  An unavailable narration may still carry the
    tool's ``provenance`` (which artifacts were consulted) while ``evidence``
    stays empty.
    """

    status: Literal["available", "unavailable"]
    text: str
    evidence: Mapping[str, object]
    provenance: tuple[ArtifactRef, ...]
    citations: tuple[RetrievalHit, ...]
    limitations: tuple[str, ...]
    unavailable: Unavailable | None = None

    def __post_init__(self) -> None:
        if self.status == "available":
            if self.unavailable is not None:
                raise ValueError(
                    "available narration cannot carry unavailable metadata"
                )
            if not self.provenance:
                raise ValueError("available narration requires provenance")
        else:
            if self.unavailable is None:
                raise ValueError("unavailable narration requires an unavailable reason")
            if self.evidence or self.citations:
                raise ValueError("unavailable narration cannot carry answer evidence")


_DEFINITION_BY_NAME = {definition.name: definition for definition in TOOL_REGISTRY}
_METADATA_FIELDS = frozenset({"status", "provenance", "unavailable"})


def narrate(tool_name: str, result: ToolOutput) -> GroundedNarration:
    """Narrate one validated tool result without deriving a new claim.

    A result must be the documented output class for ``tool_name``.  Type
    mismatches and malformed available citation results become explicit
    unavailable narrations, since attaching a label to the wrong evidence is
    less honest than returning no answer.  The summary deliberately contains
    no domain numbers or legal/physical conclusions; callers render the exact
    payload in :attr:`GroundedNarration.evidence`.
    """

    definition = _DEFINITION_BY_NAME.get(tool_name)
    if definition is None:
        return _unavailable(
            "unsupported_request", "the requested tool is not registered"
        )
    if not isinstance(result, ToolOutput):
        return _unavailable(
            "invalid_prerequisite", "tool result is not a validated output"
        )
    # Fail closed on our own boundary rather than trusting that the caller ran
    # validation: a ``model_construct``-built result (or one mutated after
    # validation) is re-checked against its own contract before narration.
    try:
        result = type(result).model_validate(result.model_dump(mode="json"))
    except ValidationError:
        return _unavailable(
            "invalid_prerequisite", "tool result failed contract validation"
        )

    if result.status == "unavailable":
        # ``UnavailableOutput`` is shared by every registered tool, so any tool
        # name accepts it here; the tool-name check above already ran.
        if not isinstance(result, UnavailableOutput) or result.unavailable is None:
            return _unavailable(
                "invalid_prerequisite", "tool result has an invalid unavailable shape"
            )
        # The reason is copied verbatim; it is tool-authored text, not model
        # prose.  A later /ask loop must treat any numbers in it as
        # tool-provenanced when running its number trace, not as invented.
        return GroundedNarration(
            status="unavailable",
            text=result.unavailable.reason,
            evidence=MappingProxyType({}),
            provenance=tuple(result.provenance),
            citations=(),
            limitations=(),
            unavailable=result.unavailable,
        )

    available_model = definition.output_model[0]
    if not isinstance(result, available_model):
        return _unavailable(
            "invalid_prerequisite",
            "tool result does not match the registered available output",
        )

    citations: tuple[RetrievalHit, ...] = ()
    if isinstance(result, CiteData):
        if not result.hits:
            return _unavailable(
                "insufficient_evidence",
                "accepted cite result contains no citation hits",
            )
        citations = tuple(result.hits)

    payload = result.model_dump(mode="json")
    evidence = _freeze(
        {key: value for key, value in payload.items() if key not in _METADATA_FIELDS}
    )
    return GroundedNarration(
        status="available",
        text=_summary(tool_name, citations),
        evidence=evidence,
        provenance=tuple(result.provenance),
        citations=citations,
        limitations=_limitations(result),
    )


def _freeze(value: object) -> object:
    """Return a read-only deep copy: dicts become proxies, lists become tuples."""

    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _summary(tool_name: str, citations: tuple[RetrievalHit, ...]) -> str:
    if citations:
        return "Accepted citation evidence is available."
    return f"An accepted {tool_name} result is available."


def _limitations(result: ToolOutput) -> tuple[str, ...]:
    """Return only labels or caveats already carried by the accepted result."""

    limitations = [
        f"Evidence source kind: {provenance.source_kind}."
        for provenance in result.provenance
        if provenance.source_kind != "observed"
    ]
    if isinstance(result, CausalData):
        limitations.extend(result.assumptions)
    return tuple(dict.fromkeys(limitations))


def _unavailable(code: UnavailableCode, reason: str) -> GroundedNarration:
    unavailable = Unavailable(code=code, reason=reason)
    return GroundedNarration(
        status="unavailable",
        text=reason,
        evidence=MappingProxyType({}),
        provenance=(),
        citations=(),
        limitations=(),
        unavailable=unavailable,
    )
