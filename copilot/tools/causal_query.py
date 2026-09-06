"""Bounded, read-only access to validated causal evidence artifacts.

This module never invokes a causal estimator.  Deployment registers exact
request-to-artifact bindings, and the tool reads only those files.  Every
missing, malformed, or insufficient artifact becomes the normal unavailable
envelope rather than a plausible effect response.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from causal.validation import ValidationResult, validate_artifact
from copilot.tools.schemas import (
    ArtifactRef,
    CausalData,
    CausalQueryInput,
    UnavailableOutput,
    unavailable_output,
)

_ARTIFACT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "causal-evidence-artifact.schema.json"
)


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
    """Typed evidence payload awaiting the shared CausalData contract join."""

    question: Mapping[str, Any]
    sources: tuple[Mapping[str, Any], ...]
    sample: Mapping[str, Any]
    diagnostics: tuple[Mapping[str, Any], ...]
    citations: tuple[Mapping[str, Any], ...]


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
            artifact = _load_json_object(registration.path)
        except (OSError, TypeError, json.JSONDecodeError):
            return unavailable_output(
                "artifact_unavailable", "Causal evidence artifact is unavailable."
            )
        if not self._validator.is_valid(artifact):
            return unavailable_output(
                "insufficient_evidence", "Causal evidence artifact is malformed."
            )
        validation = validate_artifact(artifact)
        if not validation.estimable:
            return _unavailable_for_validation(validation)
        return _available_response(artifact, registration)


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


def evidence_from_artifact(artifact: Mapping[str, Any]) -> CausalEvidence:
    """Extract the fields that the shared typed response will expose."""

    return CausalEvidence(
        question=_mapping(artifact["question"]),
        sources=tuple(_mapping(item) for item in artifact["sources"]),
        sample=_mapping(artifact["sample"]),
        diagnostics=tuple(_mapping(item) for item in artifact["diagnostics"]),
        citations=tuple(_mapping(item) for item in artifact["citations"]),
    )


def _available_response(
    artifact: Mapping[str, Any], registration: RegisteredCausalArtifact
) -> CausalData:
    """Map the estimate into the current response while schemas are integrating.

    ``evidence_from_artifact`` retains the typed payload.  The 130 schema join
    will place that payload in top-level CausalData fields instead of encoding
    it in free-form evidence rows.
    """

    estimate = _mapping(artifact.get("estimate"))
    interval = _mapping(estimate.get("interval"))
    artifact_ref = ArtifactRef(
        artifact_id=_required_text(artifact, "artifact_id"),
        artifact_version=_required_text(artifact, "artifact_version"),
        source_kind=registration.source_kind,
        source_ref=str(registration.path),
    )
    return CausalData(
        status="available",
        provenance=[artifact_ref],
        answer_numbers={"effect": _required_number(estimate, "effect")},
        method=_required_text(estimate, "method"),
        assumptions=list(artifact["assumptions"]),
        interval=[
            _required_number(interval, "lower"),
            _required_number(interval, "upper"),
        ],
        evidence_rows=[],
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _required_text(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing required causal artifact text field: {key}")
    return value


def _required_number(document: Mapping[str, Any], key: str) -> float | int:
    value = document.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"missing required causal artifact number field: {key}")
    return value
