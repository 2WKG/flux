"""Fail-closed parsing and classification of line-upgrade congestion inputs.

Raw constraint rows are not market observations merely because they contain a
number called ``shadow_price``.  This module turns only explicitly attributed,
fully-provenanced inputs into the immutable congestion types defined by
``line_upgrade_contracts``.  Everything else has an explicit unavailable or
unattributed outcome.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from pydantic import ValidationError

from pipelines.line_upgrade_contracts import (
    Congestion,
    CongestionSource,
    ObservedCongestion,
    ProxyCongestion,
    SimulatedCongestion,
    UnattributedCongestion,
    UnavailableReason,
)


@dataclass(frozen=True, slots=True)
class ClassifiedCongestion:
    """One input's contract-safe classification, in caller input order."""

    input_index: int
    congestion: Congestion
    provenance: CongestionInputProvenance

    @property
    def source(self) -> CongestionSource:
        return self.congestion.source

    @property
    def unavailable_reason(self) -> UnavailableReason | None:
        """The explicit reason when this input cannot yield a line figure."""
        if isinstance(self.congestion, UnattributedCongestion):
            return self.congestion.reason
        return None

    @property
    def is_unavailable(self) -> bool:
        """Whether this input was safely withheld from line-level scoring."""
        return isinstance(self.congestion, UnattributedCongestion)

    @property
    def required_action(self) -> str | None:
        """State the next safe data action for an unavailable input.

        This keeps an incomplete declared source distinguishable from a usable
        simulated or proxy value: it remains unattributed and tells callers
        how to make a later classification possible.
        """
        if self.unavailable_reason is UnavailableReason.UNMAPPED_CONSTRAINT:
            return "Map the constraint to a line before classifying congestion."
        if self.unavailable_reason is UnavailableReason.NO_CONGESTION_INPUT:
            return (
                "Provide an explicit source and that source's required "
                "provenance fields."
            )
        return None


@dataclass(frozen=True, slots=True)
class CongestionInputProvenance:
    """Deterministic metadata retained with every classified input.

    ``scenario`` and ``timestamp`` are optional because the line-upgrade
    contract has no canonical fields for either.  They therefore record only
    values explicitly supplied by the caller and never imply market or model
    provenance that the congestion contract does not establish.
    """

    input_sha256: str
    source_identifier: str | None
    scenario: str | None
    timestamp: str | None
    assumptions: tuple[tuple[str, str | float], ...]


def _canonical_input(value: Any) -> Any:
    """Return a JSON-safe, stable representation for an input content hash."""
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_input(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_input(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return _canonical_input(value.model_dump(mode="json"))
    return value


def _input_sha256(raw: Mapping[str, Any] | Congestion) -> str:
    """Hash caller input as canonical JSON, independent of mapping order."""
    serialized = json.dumps(
        _canonical_input(raw),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _optional_raw_text(raw: Mapping[str, Any], field: str) -> str | None:
    """Preserve only explicit, text-like optional metadata from the raw input."""
    value = raw.get(field)
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else None


def _provenance(
    raw: Mapping[str, Any] | Congestion, congestion: Congestion
) -> CongestionInputProvenance:
    """Persist contract-derived provenance without upgrading incomplete input."""
    scenario = (
        _optional_raw_text(raw, "scenario")
        or _optional_raw_text(raw, "scenario_id")
        if isinstance(raw, Mapping)
        else None
    )
    timestamp = _optional_raw_text(raw, "timestamp") if isinstance(raw, Mapping) else None

    if isinstance(congestion, ObservedCongestion):
        source_identifier = congestion.market
        assumptions: tuple[tuple[str, str | float], ...] = ()
    elif isinstance(congestion, SimulatedCongestion):
        source_identifier = congestion.run_id
        assumptions = ()
    elif isinstance(congestion, ProxyCongestion):
        source_identifier = None
        assumptions = (
            ("assumed_usd_per_mwh", congestion.assumed_usd_per_mwh),
            ("assumption_note", congestion.assumption_note),
        )
    else:
        source_identifier = None
        assumptions = ()

    return CongestionInputProvenance(
        input_sha256=_input_sha256(raw),
        source_identifier=source_identifier,
        scenario=scenario,
        timestamp=timestamp,
        assumptions=assumptions,
    )

def _unattributed(raw: Mapping[str, Any]) -> UnattributedCongestion:
    """Choose only an explicit unavailable reason; otherwise fail closed."""
    if raw.get("mapping_method") == "unmapped":
        return UnattributedCongestion(reason=UnavailableReason.UNMAPPED_CONSTRAINT)

    reason = raw.get("reason", raw.get("unavailable_reason"))
    try:
        return UnattributedCongestion(reason=UnavailableReason(reason))
    except (TypeError, ValueError):
        return UnattributedCongestion(reason=UnavailableReason.NO_CONGESTION_INPUT)


def _parse_declared_source(raw: Mapping[str, Any]) -> Congestion:
    """Parse one declared contract source, falling back to an explicit state.

    We deliberately do not inspect arbitrary SCED-shaped fields to infer a
    source.  In particular, a raw ``Shadow Price`` column is insufficient to
    establish an observed per-line amount and its market provenance.
    """
    if raw.get("mapping_method") == "unmapped":
        return _unattributed(raw)

    try:
        source = CongestionSource(raw.get("source"))
    except (TypeError, ValueError):
        return _unattributed(raw)

    try:
        # These transport metadata fields are persisted beside the classified
        # output by 2WKG-185, but are deliberately outside the frozen
        # line-upgrade congestion contract.
        contract_raw = {
            key: value
            for key, value in raw.items()
            if key not in {"scenario", "scenario_id", "timestamp"}
        }
        if source is CongestionSource.OBSERVED:
            return ObservedCongestion.model_validate(contract_raw)
        if source is CongestionSource.SIMULATED:
            return SimulatedCongestion.model_validate(contract_raw)
        if source is CongestionSource.PROXY:
            return ProxyCongestion.model_validate(contract_raw)
        return UnattributedCongestion.model_validate(contract_raw)
    except ValidationError:
        # Do not repair partial provenance or turn incomplete raw data into a
        # plausible value.  The caller can inspect the explicit reason instead.
        return _unattributed(raw)


def classify_congestion_input(raw: Mapping[str, Any] | Congestion) -> Congestion:
    """Return a contract congestion class for one input without guessing.

    Existing contract objects are already validated and retain their class.
    Mapping inputs require an explicit ``source`` and the fields required by
    that source's contract.  Unknown, malformed, and raw/unattributed inputs
    become ``UnattributedCongestion`` rather than ``ObservedCongestion``.
    """
    if isinstance(
        raw,
        (ObservedCongestion, SimulatedCongestion, ProxyCongestion, UnattributedCongestion),
    ):
        return raw
    if not isinstance(raw, Mapping):
        return UnattributedCongestion(reason=UnavailableReason.NO_CONGESTION_INPUT)
    return _parse_declared_source(raw)


def parse_congestion_inputs(
    inputs: Iterable[Mapping[str, Any] | Congestion],
) -> tuple[ClassifiedCongestion, ...]:
    """Classify every input in deterministic caller order.

    The index is part of the result so duplicate values remain distinct and a
    repeated parse of the same iterable contents produces the same ordering.
    """
    return tuple(
        ClassifiedCongestion(
            index,
            congestion := classify_congestion_input(raw),
            _provenance(raw, congestion),
        )
        for index, raw in enumerate(inputs)
    )
