"""Bounded, read-only access to validated causal evidence artifacts.

This module never invokes a causal estimator.  Deployment registers exact
request-to-artifact bindings, and the tool reads only those files.  Every
missing, malformed, or insufficient artifact becomes the normal unavailable
envelope rather than a plausible effect response, and no artifact content can
escape this module as a raised exception.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from causal.validation import ValidationResult, validate_artifact
from copilot.tools.schemas import (
    ArtifactRef,
    CausalCitation,
    CausalData,
    CausalDiagnostic,
    CausalQueryInput,
    CausalQuestion,
    CausalSample,
    CausalSource,
    UnavailableOutput,
    unavailable_output,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACT_SCHEMA_PATH = _REPO_ROOT / "docs" / "causal-evidence-artifact.schema.json"
# CLAUDE.md: ``[UNVERIFIED]`` claims remain unresolved, so they can never be
# served as identifying assumptions or supporting evidence.
UNVERIFIED_TAG = "[UNVERIFIED"
# Artifacts are small JSON documents; anything larger is refused before it is
# read so a runaway file can neither exhaust memory nor overflow the decoder.
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
# ``CausalData.assumptions`` is unbounded on the frozen wire model
# (``copilot/tools/schemas.py``), so the reader bounds it at the read boundary
# with the same limits ``docs/causal-evidence-artifact.schema.json`` declares.
MAX_TEXT_LIST_ITEMS = 50
MAX_TEXT_LIST_ITEM_LENGTH = 1024
MAX_ESTIMAND_LENGTH = 256
_default_reader: CausalArtifactReader | None = None


@dataclass(frozen=True)
class RegisteredCausalArtifact:
    """A deployment-owned binding from one exact request to one local artifact."""

    request: CausalQueryInput
    path: Path
    source_kind: str

    def __post_init__(self) -> None:
        if self.source_kind not in {"fixture", "observed", "simulated", "heuristic"}:
            raise ValueError(
                "causal artifact source_kind must be a known local evidence kind"
            )


@dataclass(frozen=True)
class CausalEvidence:
    """The explicit evidence fields carried by an available causal response."""

    question: CausalQuestion
    sources: tuple[CausalSource, ...]
    sample: CausalSample
    diagnostics: tuple[CausalDiagnostic, ...]
    citations: tuple[CausalCitation, ...]


class CausalArtifactReader:
    """Read a finite, deployment-provided set of causal artifact paths."""

    def __init__(self, registrations: tuple[RegisteredCausalArtifact, ...]) -> None:
        keys = [
            registration.request.model_dump_json() for registration in registrations
        ]
        if len(keys) != len(set(keys)):
            raise ValueError(
                "causal artifact registrations must not duplicate a request"
            )
        self._registrations = {
            key: registration for key, registration in zip(keys, registrations)
        }
        self._schema = _load_schema()
        self._validator = Draft202012Validator(self._schema)

    def query(
        self, request: CausalQueryInput | Mapping[str, Any]
    ) -> CausalData | UnavailableOutput:
        """Read a registered artifact, never deriving an estimate on demand."""

        try:
            validated_request = (
                request
                if isinstance(request, CausalQueryInput)
                else CausalQueryInput.model_validate(request)
            )
        except ValidationError:
            return unavailable_output(
                "unsupported_request", "Causal query selection is not supported."
            )
        registration = self._registrations.get(validated_request.model_dump_json())
        if registration is None:
            return unavailable_output(
                "unsupported_request", "Causal query selection is not registered."
            )
        try:
            size = registration.path.stat().st_size
            if size > MAX_ARTIFACT_BYTES:
                return unavailable_output(
                    "artifact_unavailable",
                    "Causal evidence artifact exceeds the size cap "
                    f"({size} > {MAX_ARTIFACT_BYTES} bytes).",
                )
            artifact = _load_json_object(registration.path)
        except (OSError, TypeError, ValueError, RecursionError) as error:
            # ``json.JSONDecodeError`` and ``UnicodeDecodeError`` are ValueErrors;
            # deeply nested documents overflow the decoder with RecursionError.
            return unavailable_output(
                "artifact_unavailable",
                f"Causal evidence artifact is unavailable ({type(error).__name__}).",
            )
        if not self._validator.is_valid(artifact):
            return unavailable_output(
                "insufficient_evidence", "Causal evidence artifact is malformed."
            )
        validation = validate_artifact(artifact)
        if not validation.estimable:
            return _unavailable_for_validation(validation)
        if _carries_unverified_claim(artifact):
            return unavailable_output(
                "insufficient_evidence",
                "Causal evidence artifact carries unresolved [UNVERIFIED] claims.",
            )
        try:
            return _available_response(artifact, registration)
        except (ValidationError, ValueError, TypeError, KeyError) as error:
            # The artifact passed its schema but does not fit the wire contract
            # (schema/contract skew).  Fail closed instead of raising.
            return unavailable_output(
                "insufficient_evidence",
                "Causal evidence artifact does not fit the response contract "
                f"({type(error).__name__}).",
            )


def configure_causal_artifacts(
    registrations: tuple[RegisteredCausalArtifact, ...],
) -> None:
    """Install deployment-owned causal artifact bindings for the tool process."""

    global _default_reader
    _default_reader = CausalArtifactReader(registrations)


def causal_query(
    kind: str,
    county_fips: str | None = None,
    scenario_id: str = "uri_2021",
    site_id: str | None = None,
    capacity_mw: int | None = None,
    treatment: str | None = None,
) -> CausalData | UnavailableOutput:
    """Run the frozen causal-query signature as a bounded artifact lookup."""

    if _default_reader is None:
        return unavailable_output(
            "artifact_unavailable", "Causal artifact bindings are unavailable."
        )
    return _default_reader.query(
        {
            "kind": kind,
            "county_fips": county_fips,
            "scenario_id": scenario_id,
            "site_id": site_id,
            "capacity_mw": capacity_mw,
            "treatment": treatment,
        }
    )


def _load_schema() -> dict[str, Any]:
    return _load_json_object(_ARTIFACT_SCHEMA_PATH)


def _load_json_object(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError("causal artifact must be a JSON object")
    return document


def _unavailable_for_validation(validation: ValidationResult) -> UnavailableOutput:
    codes = ", ".join(validation.unavailable_codes)
    return unavailable_output(
        "insufficient_evidence",
        f"Causal evidence prerequisites are not met: {codes}.",
    )


def _carries_unverified_claim(artifact: Mapping[str, Any]) -> bool:
    """True when any string anywhere in the artifact is tagged ``[UNVERIFIED``.

    Every text field of the artifact can reach the model (question definitions,
    population, source names, estimand, evidence, caveats, ...), so the guard
    walks every string leaf rather than an allow-list of fields.
    """

    return any(UNVERIFIED_TAG in text for text in _string_leaves(artifact))


def _string_leaves(document: object) -> Iterable[str]:
    """Yield every string value (and key) in a JSON document, iteratively."""

    stack: list[object] = [document]
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            yield value
        elif isinstance(value, Mapping):
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def evidence_from_artifact(artifact: Mapping[str, Any]) -> CausalEvidence:
    """Extract the validated evidence fields into the public typed contract."""

    return CausalEvidence(
        question=CausalQuestion.model_validate(artifact["question"]),
        sources=tuple(
            CausalSource.model_validate(item) for item in artifact["sources"]
        ),
        sample=CausalSample.model_validate(artifact["sample"]),
        diagnostics=tuple(
            CausalDiagnostic.model_validate(item) for item in artifact["diagnostics"]
        ),
        citations=tuple(
            CausalCitation.model_validate(item) for item in artifact["citations"]
        ),
    )


def _available_response(
    artifact: Mapping[str, Any], registration: RegisteredCausalArtifact
) -> CausalData:
    """Map a validated estimate and its required evidence into the response.

    Follows the artifact-to-response mapping in
    ``docs/causal-evidence-artifact.md``: assumptions and caveats both land in
    ``assumptions``; the estimate's estimand, effect, interval, confidence level
    and evidence citations land in one ``evidence_rows`` entry so every number in
    ``answer_numbers`` is traceable to an evidence row.
    """

    estimate = _mapping(artifact.get("estimate"))
    interval = _mapping(estimate.get("interval"))
    evidence = evidence_from_artifact(artifact)
    artifact_ref = ArtifactRef(
        artifact_id=_required_text(artifact, "artifact_id"),
        artifact_version=_required_text(artifact, "artifact_version"),
        source_kind=registration.source_kind,
        source_ref=_source_ref(registration.path),
    )
    effect = _required_number(estimate, "effect")
    lower = _required_number(interval, "lower")
    upper = _required_number(interval, "upper")
    estimate_evidence = [
        CausalCitation.model_validate(item).model_dump()
        for item in _sequence(estimate.get("evidence"))
    ]
    return CausalData(
        status="available",
        provenance=[artifact_ref],
        answer_numbers={"effect": effect},
        method=_required_text(estimate, "method"),
        assumptions=[
            *_text_list(artifact.get("assumptions")),
            *_text_list(estimate.get("caveats")),
        ],
        interval=[lower, upper],
        evidence_rows=[
            {
                "estimand": _required_text(
                    estimate, "estimand", max_length=MAX_ESTIMAND_LENGTH
                ),
                "effect": effect,
                "interval": [lower, upper],
                "confidence_level": _required_number(estimate, "confidence_level"),
                "evidence": estimate_evidence,
            }
        ],
        question=evidence.question,
        sources=list(evidence.sources),
        sample=evidence.sample,
        diagnostics=list(evidence.diagnostics),
        citations=list(evidence.citations),
    )


def _source_ref(path: Path) -> str:
    """Name the artifact without leaking the host filesystem layout."""

    try:
        return path.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Iterable[Any]:
    return value if isinstance(value, list) else ()


def _text_list(value: object) -> list[str]:
    items = list(_sequence(value))
    if not all(isinstance(item, str) for item in items):
        raise TypeError("causal artifact text lists must contain only strings")
    if len(items) > MAX_TEXT_LIST_ITEMS:
        raise ValueError("causal artifact text list exceeds the item bound")
    if any(len(item) > MAX_TEXT_LIST_ITEM_LENGTH for item in items):
        raise ValueError("causal artifact text list item exceeds the length bound")
    return items


def _required_text(
    document: Mapping[str, Any], key: str, *, max_length: int | None = None
) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing required causal artifact text field: {key}")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"causal artifact text field exceeds its bound: {key}")
    return value


def _required_number(document: Mapping[str, Any], key: str) -> float | int:
    value = document.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"missing required causal artifact number field: {key}")
    return value
