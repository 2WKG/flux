"""Fail-closed parsing and classification of line-upgrade congestion inputs.

Raw constraint rows are not market observations merely because they contain a
number called ``shadow_price``.  This module turns only explicitly attributed,
fully-provenanced inputs into the immutable congestion types defined by
``line_upgrade_contracts``.  Everything else has an explicit unavailable or
unattributed outcome.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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
        if source is CongestionSource.OBSERVED:
            return ObservedCongestion.model_validate(raw)
        if source is CongestionSource.SIMULATED:
            return SimulatedCongestion.model_validate(raw)
        if source is CongestionSource.PROXY:
            return ProxyCongestion.model_validate(raw)
        return UnattributedCongestion.model_validate(raw)
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
        ClassifiedCongestion(index, classify_congestion_input(raw))
        for index, raw in enumerate(inputs)
    )
