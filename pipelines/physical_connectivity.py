"""Normalize only source-native electrical terminal evidence.

This adapter deliberately has no geometry-to-topology operation.  A caller may
provide line geometry as display context, but an edge is publishable here only
when its source supplies two stable terminal identifiers and each endpoint is
present in the same source release.  This keeps a future state parser useful
without treating a line endpoint, a crossing, or a nearby facility as an
electrical connection.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass


class ConnectivityEvidenceError(ValueError):
    """Raised when a record would turn non-terminal context into topology."""


@dataclass(frozen=True)
class NativeTerminal:
    terminal_id: str
    source_record_id: str


@dataclass(frozen=True)
class ConnectivityEdge:
    edge_id: str
    from_terminal_id: str
    to_terminal_id: str
    source_record_id: str
    circuit_id: str | None = None


def _required_text(record: Mapping[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConnectivityEvidenceError(
            f"record {record.get('edge_id', '<unknown>')!r} lacks source-native {field!r}"
        )
    return value.strip()


def normalize_native_connectivity(
    terminals: Iterable[Mapping[str, object]], edges: Iterable[Mapping[str, object]]
) -> tuple[tuple[NativeTerminal, ...], tuple[ConnectivityEdge, ...]]:
    """Validate one authoritative release's terminal and circuit references.

    Input names are intentionally canonical rather than guessed from geometry
    sources.  State-specific acquisition/parsers must map their documented
    native fields before calling this function.
    """
    normalized_terminals: dict[str, NativeTerminal] = {}
    for raw in terminals:
        terminal = NativeTerminal(
            terminal_id=_required_text(raw, "terminal_id"),
            source_record_id=_required_text(raw, "source_record_id"),
        )
        prior = normalized_terminals.get(terminal.terminal_id)
        if prior is not None and prior != terminal:
            raise ConnectivityEvidenceError(
                f"terminal_id {terminal.terminal_id!r} has conflicting source records"
            )
        normalized_terminals[terminal.terminal_id] = terminal

    normalized_edges: dict[str, ConnectivityEdge] = {}
    for raw in edges:
        edge = ConnectivityEdge(
            edge_id=_required_text(raw, "edge_id"),
            from_terminal_id=_required_text(raw, "from_terminal_id"),
            to_terminal_id=_required_text(raw, "to_terminal_id"),
            source_record_id=_required_text(raw, "source_record_id"),
            circuit_id=(
                raw["circuit_id"].strip()
                if isinstance(raw.get("circuit_id"), str) and raw["circuit_id"].strip()
                else None
            ),
        )
        if edge.from_terminal_id == edge.to_terminal_id:
            raise ConnectivityEvidenceError(
                f"edge {edge.edge_id!r} repeats one terminal; no continuity claim is possible"
            )
        missing = {
            edge.from_terminal_id,
            edge.to_terminal_id,
        } - normalized_terminals.keys()
        if missing:
            raise ConnectivityEvidenceError(
                f"edge {edge.edge_id!r} references terminals absent from this release: {sorted(missing)!r}"
            )
        prior = normalized_edges.get(edge.edge_id)
        if prior is not None and prior != edge:
            raise ConnectivityEvidenceError(
                f"edge_id {edge.edge_id!r} has conflicting source records"
            )
        normalized_edges[edge.edge_id] = edge
    return (
        tuple(
            sorted(normalized_terminals.values(), key=lambda value: value.terminal_id)
        ),
        tuple(sorted(normalized_edges.values(), key=lambda value: value.edge_id)),
    )


def blocked_readiness_receipt(
    *,
    state: str,
    source_name: str,
    source_url: str,
    source_version: str,
    assessed_at: str,
    reason: str,
) -> dict[str, object]:
    """Return an explicit, machine-readable non-coverage receipt.

    A blocked acquisition is evidence about access only.  It contains no asset
    count or inferred edge and must never be read as completed state coverage.
    """
    if state not in {"TX", "MN"}:
        raise ValueError("state must be TX or MN")
    return {
        "format": "flux-physical-connectivity-readiness-v1",
        "state": state,
        "status": "blocked",
        "source": {
            "name": source_name,
            "url": source_url,
            "version": source_version,
            "assessed_at": assessed_at,
        },
        "accepted_terminal_count": 0,
        "accepted_edge_count": 0,
        "reason": reason,
        "prohibited_inferences": [
            "line endpoints",
            "line crossings",
            "proximity",
            "plant coordinates",
            "street geometry",
        ],
    }


def normalized_receipt(
    *,
    state: str,
    source_name: str,
    source_url: str,
    source_version: str,
    assessed_at: str,
    terminals: Iterable[Mapping[str, object]],
    edges: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Return a receipt with source-native terminals/edges after validation."""
    normalized_terminals, normalized_edges = normalize_native_connectivity(
        terminals, edges
    )
    return {
        "format": "flux-physical-connectivity-readiness-v1",
        "state": state,
        "status": "ready_for_contract_integration",
        "source": {
            "name": source_name,
            "url": source_url,
            "version": source_version,
            "assessed_at": assessed_at,
        },
        "accepted_terminal_count": len(normalized_terminals),
        "accepted_edge_count": len(normalized_edges),
        "terminals": [asdict(value) for value in normalized_terminals],
        "edges": [asdict(value) for value in normalized_edges],
    }
