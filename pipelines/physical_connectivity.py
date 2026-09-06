"""Normalize only source-native electrical terminal evidence.

This adapter deliberately has no geometry-to-topology operation.  A caller may
provide line geometry as display context, but an edge is publishable here only
when its source supplies two stable terminal identifiers and each endpoint is
present in the same source release.

Structural validity is **not** re-implemented here.  Every structural rule --
identifier uniqueness, endpoint existence, an edge joining two distinct
terminals, ``asset_id`` and ``source_id`` resolving inside the release -- is
owned by :func:`pipelines.physical_inventory.validate_artifact` (2WKG-441) and
is enforced by handing the produced rows to that validator.  What this module
owns is the one rule the contract cannot express, because the contract only
ever sees post-deduplication rows: a native release may repeat an identifier,
and repeating it with a *different* source record is a conflict rather than a
duplicate.

The consumer is 2WKG-456 (the state connectivity parser): it maps a state's
documented native fields onto these inputs, and puts the returned rows straight
into the 2WKG-441 physical-inventory artifact.  There is no second persistence
schema and no alternate artifact shape here.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pipelines.physical_inventory import (
    PhysicalInventoryError,
    artifact_sha256,
    validate_artifact,
)

READINESS_FORMAT = "flux-physical-connectivity-readiness-v1"
READINESS_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "sources"
    / "physical-connectivity-readiness-v1.json"
)
SUPPORTED_STATES = frozenset({"TX", "MN"})
PROHIBITED_INFERENCES = (
    "line endpoints",
    "line crossings",
    "proximity",
    "plant coordinates",
    "street geometry",
)


class ConnectivityEvidenceError(ValueError):
    """Raised when a record would turn non-terminal context into topology."""


@dataclass(frozen=True)
class NativeTerminal:
    terminal_id: str
    asset_id: str
    source_id: str
    source_record_id: str


@dataclass(frozen=True)
class ConnectivityEdge:
    edge_id: str
    from_terminal_id: str
    to_terminal_id: str
    source_id: str
    source_record_id: str


def _required_text(record: Mapping[str, object], field: str, kind: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        label = record.get("edge_id" if kind == "edge" else "terminal_id", "<unknown>")
        raise ConnectivityEvidenceError(
            f"{kind} {label!r} lacks source-native {field!r}"
        )
    return value.strip()


def _state(state: str) -> str:
    if state not in SUPPORTED_STATES:
        raise ConnectivityEvidenceError("state must be TX or MN")
    return state


def normalize_native_connectivity(
    *,
    source_id: str,
    terminals: Iterable[Mapping[str, object]],
    edges: Iterable[Mapping[str, object]],
) -> tuple[tuple[NativeTerminal, ...], tuple[ConnectivityEdge, ...]]:
    """Collapse one authoritative release's repeated rows into canonical rows.

    Input names are intentionally canonical rather than guessed from geometry
    sources. State-specific acquisition/parsers must map their documented native
    fields before calling this function. ``source_id`` must be the matching
    source entry in the canonical physical-inventory artifact.

    Only the deduplication rule lives here: an identifier repeated with an
    identical source record is one row, and an identifier repeated with a
    different source record is a conflict.  Everything structural is left to
    :func:`pipelines.physical_inventory.validate_artifact`, which
    :func:`normalized_receipt` runs over the rows returned here.
    """
    if not isinstance(source_id, str) or not source_id.strip():
        raise ConnectivityEvidenceError("source_id is required for a native release")
    normalized_terminals: dict[str, NativeTerminal] = {}
    for raw in terminals:
        terminal = NativeTerminal(
            terminal_id=_required_text(raw, "terminal_id", "terminal"),
            asset_id=_required_text(raw, "asset_id", "terminal"),
            source_id=source_id,
            source_record_id=_required_text(raw, "source_record_id", "terminal"),
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
            edge_id=_required_text(raw, "edge_id", "edge"),
            from_terminal_id=_required_text(raw, "from_terminal_id", "edge"),
            to_terminal_id=_required_text(raw, "to_terminal_id", "edge"),
            source_id=source_id,
            source_record_id=_required_text(raw, "source_record_id", "edge"),
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


def contract_precheck(
    *,
    state: str,
    created_at: str,
    source: Mapping[str, object],
    assets: Sequence[Mapping[str, object]],
    terminals: Sequence[Mapping[str, object]],
    edges: Sequence[Mapping[str, object]],
    coverage: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Run the produced rows through the 2WKG-441 contract validator.

    The probe artifact is never published; it exists so a state parser learns at
    normalization time, and not at publication time, that its rows do not
    satisfy :func:`pipelines.physical_inventory.validate_artifact`.
    """
    artifact: dict[str, Any] = {
        "artifact_id": f"{state}:physical-inventory:0.0.0",
        "contract_version": "1.0.0",
        "geography_id": state,
        "artifact_version": "0.0.0",
        "inventory_mode": "physical_observed",
        "electrical_model_mode": "source_backed",
        "created_at": created_at,
        "sources": [dict(source)],
        "assets": [dict(asset) for asset in assets],
        "terminals": [dict(row) for row in terminals],
        "connectivity_edges": [dict(row) for row in edges],
        "coverage": [dict(row) for row in coverage],
    }
    artifact["content_sha256"] = artifact_sha256(artifact)
    try:
        return validate_artifact(artifact)
    except PhysicalInventoryError as exc:
        raise ConnectivityEvidenceError(
            f"rows are rejected by the physical-inventory contract: {exc}"
        ) from exc


def _evidence_item(item: Mapping[str, object]) -> dict[str, object]:
    """Validate one captured page: a URL, a capture method, and an outcome."""
    required = {
        "url",
        "http_status",
        "captured_at",
        "bytes",
        "sha256",
        "capture_method",
        "quote",
        "quote_status",
        "note",
    }
    if set(item) != required:
        raise ConnectivityEvidenceError(
            f"evidence item must carry exactly {sorted(required)!r}"
        )
    for field in ("url", "captured_at", "capture_method", "quote_status", "note"):
        if not isinstance(item[field], str) or not item[field].strip():
            raise ConnectivityEvidenceError(f"evidence item lacks {field!r}")
    if item["quote_status"] not in {"verified", "unverified_as_committed"}:
        raise ConnectivityEvidenceError(
            "quote_status must be 'verified' or 'unverified_as_committed'"
        )
    if not isinstance(item["http_status"], int) or isinstance(
        item["http_status"], bool
    ):
        raise ConnectivityEvidenceError("evidence item needs an integer http_status")
    if not isinstance(item["bytes"], int) or isinstance(item["bytes"], bool):
        raise ConnectivityEvidenceError("evidence item needs an integer byte count")
    digest = item["sha256"]
    if digest is not None and (
        not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise ConnectivityEvidenceError(
            "evidence sha256 must be a lowercase SHA-256 or null with a stated reason"
        )
    if item["quote_status"] == "verified" and (
        digest is None
        or not isinstance(item["quote"], str)
        or not item["quote"].strip()
    ):
        raise ConnectivityEvidenceError(
            "a verified quote needs the quoted text and the sha256 of the body it came from"
        )
    return dict(item)


def blocked_readiness_receipt(
    *,
    state: str,
    source_name: str,
    source_url: str,
    source_version: str,
    assessed_at: str,
    reason: str,
    capture_method: str,
    evidence: Sequence[Mapping[str, object]],
    verification: Mapping[str, object],
) -> dict[str, object]:
    """Return an explicit, machine-readable non-coverage receipt.

    A blocked acquisition is evidence about access only.  It contains no asset
    count or inferred edge and must never be read as completed state coverage.
    The receipt carries the checked-in ``data/sources`` shape introduced by
    2WKG-199/2WKG-216: how each page was captured, the sha256 of what was
    captured, and an explicit verification block -- not a bare timestamp.
    """
    _state(state)
    if not evidence:
        raise ConnectivityEvidenceError(
            "a blocked receipt must carry at least one capture attempt"
        )
    if not verification:
        raise ConnectivityEvidenceError("a blocked receipt must carry verification")
    if not isinstance(capture_method, str) or not capture_method.strip():
        raise ConnectivityEvidenceError("capture_method is required")
    return {
        "format": READINESS_FORMAT,
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
        "capture_method": capture_method,
        "evidence": [_evidence_item(item) for item in evidence],
        "verification": dict(verification),
        "prohibited_inferences": list(PROHIBITED_INFERENCES),
    }


def normalized_receipt(
    *,
    state: str,
    source: Mapping[str, object],
    assessed_at: str,
    assets: Sequence[Mapping[str, object]],
    coverage: Sequence[Mapping[str, object]],
    terminals: Iterable[Mapping[str, object]],
    edges: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Return a receipt with source-native terminals/edges after validation.

    ``source`` is the release's row from the physical-inventory artifact's
    ``sources[]``, ``assets`` are that release's asset rows and ``coverage`` its
    declared coverage rows; all three are passed through to the contract
    validator, so the receipt's "ready for the 2WKG-441 artifact" status is a
    checked claim rather than a label.
    """
    _state(state)
    if not isinstance(source, Mapping) or not isinstance(source.get("source_id"), str):
        raise ConnectivityEvidenceError(
            "source must be the release's physical-inventory sources[] row"
        )
    source_id = source["source_id"]
    normalized_terminals, normalized_edges = normalize_native_connectivity(
        source_id=source_id, terminals=terminals, edges=edges
    )
    terminal_rows = [asdict(value) for value in normalized_terminals]
    edge_rows = [asdict(value) for value in normalized_edges]
    contract_precheck(
        state=state,
        created_at=assessed_at,
        source=source,
        assets=assets,
        terminals=terminal_rows,
        edges=edge_rows,
        coverage=coverage,
    )
    return {
        "format": READINESS_FORMAT,
        "state": state,
        "status": "ready_for_contract_integration",
        "source": dict(source),
        "assessed_at": assessed_at,
        "validated_by": "pipelines.physical_inventory.validate_artifact",
        "accepted_terminal_count": len(terminal_rows),
        "accepted_edge_count": len(edge_rows),
        "terminals": terminal_rows,
        "edges": edge_rows,
    }


_TX_CAPTURE_METHOD = (
    "HTTPS GET of each cited ERCOT page with a desktop user agent; "
    "sha256 computed from the response body as received"
)
_MN_CAPTURE_METHOD = (
    "HTTPS GET of the cited MnGeo catalog URL, then, after that request was "
    "answered by a bot-manager interstitial, an HTTPS GET of the Internet "
    "Archive snapshot of the same URL; sha256 computed from each response body "
    "as received"
)
_MN_QUOTE = (
    "7/20/2022: Given existing accuracy problems with the dataset and "
    "insufficient current information, the Minnesota Department of Commerce "
    "cannot continue to support the distribution and use of this dataset."
)
_TX_QUOTE = (
    "This partial implementation created a new role required for holders of "
    "Digital Certificates (Certificate Holders) to access ERCOT Critical "
    "Energy Infrastructure Information (ECEII) posted to the Market "
    "Information System (MIS) Secure or Certified Area."
)


def build_readiness_document() -> dict[str, object]:
    """Build the committed readiness record from ``blocked_readiness_receipt``.

    ``data/sources/physical-connectivity-readiness-v1.json`` is the serialized
    output of this function; ``python -m pipelines.physical_connectivity``
    rewrites it, and a test asserts the committed file still equals it.
    """
    return {
        "format": READINESS_FORMAT,
        "scope": (
            "Access and evidence receipts only. These records do not establish "
            "class coverage or a published inventory; 2WKG-441 owns that "
            "contract."
        ),
        "generated_by": "pipelines.physical_connectivity.build_readiness_document",
        "receipts": [
            blocked_readiness_receipt(
                state="TX",
                source_name="ERCOT Network Operations Model / planning-model access",
                source_url="https://www.ercot.com/gridinfo/modeling",
                source_version="public access check",
                assessed_at="2026-09-06T07:43:54Z",
                reason=(
                    "ERCOT publishes modeling process and schema material, while "
                    "the network-model data is handled under CEII/ECEII access "
                    "controls. No authorized, versioned terminal-and-circuit "
                    "release was obtained in this work."
                ),
                capture_method=_TX_CAPTURE_METHOD,
                evidence=[
                    {
                        "url": "https://www.ercot.com/services/comm/mkt_notices/archives/5178",
                        "http_status": 200,
                        "captured_at": "2026-09-06T07:43:54Z",
                        "bytes": 9369,
                        "sha256": "d4bd5f4c7bc1e25d63c1624ab8d1fcc9d3d3c73356e1125d4bb68c56cecdb9a9",
                        "capture_method": _TX_CAPTURE_METHOD,
                        "quote": _TX_QUOTE,
                        "quote_status": "verified",
                        "note": (
                            "ERCOT market notice 5178; the quoted sentence is "
                            "present in the captured body."
                        ),
                    },
                    {
                        "url": "https://www.ercot.com/gridinfo/modeling",
                        "http_status": 200,
                        "captured_at": "2026-09-06T07:43:54Z",
                        "bytes": 60979,
                        "sha256": "6871815baeb9164e80a917548eac4c38fbde27f998c30500dbbeda72c42996a1",
                        "capture_method": _TX_CAPTURE_METHOD,
                        "quote": None,
                        "quote_status": "unverified_as_committed",
                        "note": (
                            "Captured as context for the modeling process and CIM "
                            "schema material; no sentence is quoted from it."
                        ),
                    },
                ],
                verification={
                    "sha256_computed_from_response_body": True,
                    "quoted_sentence_found_in_captured_body": True,
                    "authorized_release_obtained": False,
                    "terminals_or_edges_accepted": 0,
                },
            ),
            blocked_readiness_receipt(
                state="MN",
                source_name="Minnesota transmission and substation public GIS context",
                source_url="https://www.mngeo.state.mn.us/chouse/utilities.html",
                source_version="public catalog access check",
                assessed_at="2026-09-06T07:46:41Z",
                reason=(
                    "Minnesota's catalog states that the Minnesota Department of "
                    "Commerce cannot continue to support distribution and use of "
                    "the electric transmission-lines-and-substations dataset, "
                    "citing accuracy problems and insufficient current "
                    "information. The catalog is geometry/context evidence, not a "
                    "terminal-and-circuit release."
                ),
                capture_method=_MN_CAPTURE_METHOD,
                evidence=[
                    {
                        "url": "https://www.mngeo.state.mn.us/chouse/utilities.html",
                        "http_status": 200,
                        "captured_at": "2026-09-06T07:46:41Z",
                        "bytes": 21621,
                        "sha256": None,
                        "capture_method": _MN_CAPTURE_METHOD,
                        "quote": None,
                        "quote_status": "unverified_as_committed",
                        "note": (
                            "The cited URL 301-redirects to https://mn.gov/mngeo, "
                            "which answered with a Radware Bot Manager captcha "
                            "interstitial from validate.perfdrive.com. The body "
                            "carries a per-request nonce, so it has no stable "
                            "sha256 and the catalog text could not be read live."
                        ),
                    },
                    {
                        "url": "http://web.archive.org/web/20260421111929/https://www.mngeo.state.mn.us/chouse/utilities.html",
                        "http_status": 200,
                        "captured_at": "2026-09-06T07:46:41Z",
                        "bytes": 46317,
                        "sha256": "fb8f8132c45fbde6eb6a09f01c16272736cfd848a4e4a136a4210ce0001032ee",
                        "capture_method": _MN_CAPTURE_METHOD,
                        "quote": _MN_QUOTE,
                        "quote_status": "verified",
                        "note": (
                            "Internet Archive snapshot of 2026-04-21T11:19:29Z of "
                            "the same catalog URL; the quoted sentence is present "
                            "in the captured body. Two fetches produced the same "
                            "sha256."
                        ),
                    },
                ],
                verification={
                    "sha256_computed_from_response_body": True,
                    "live_catalog_url_readable": False,
                    "quoted_sentence_found_in_archived_body": True,
                    "authorized_release_obtained": False,
                    "terminals_or_edges_accepted": 0,
                },
            ),
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Rewrite the committed readiness record from the generator."""
    argv = list(sys.argv[1:] if argv is None else argv)
    path = Path(argv[0]) if argv else READINESS_PATH
    path.write_text(
        json.dumps(build_readiness_document(), indent=2, ensure_ascii=False) + "\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
