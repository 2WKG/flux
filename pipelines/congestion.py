"""Load explicit, versioned congestion artifacts for the line-ranking pipeline.

This module deliberately does not pull a market endpoint or guess a constraint
mapping.  A caller supplies a reviewed JSON artifact whose records identify a
line and one of the typed congestion source classes.  Malformed records are
reported to the caller as unavailable rather than being relabelled observed.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from pipelines.line_upgrade_contracts import Congestion

_CONGESTION = TypeAdapter(Congestion)


class CongestionArtifactError(ValueError):
    """The supplied congestion artifact cannot safely support a ranking."""


def load_congestion_artifact(path: Path, *, scenario_id: str) -> dict[int, Congestion]:
    """Return typed congestion keyed by line ID from an explicit JSON artifact.

    The file must declare its format and scenario, and each line ID may occur
    once.  Callers preserve omitted line IDs as ``NO_CONGESTION_INPUT`` rather
    than filling them with a proxy or zero.
    """

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CongestionArtifactError(
            f"cannot read congestion artifact {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict) or raw.get("format") != "flux-congestion-v1":
        raise CongestionArtifactError(
            "congestion artifact format must be 'flux-congestion-v1'"
        )
    if raw.get("scenario_id") != scenario_id:
        raise CongestionArtifactError(
            "congestion artifact scenario_id does not match request"
        )
    records = raw.get("records")
    if not isinstance(records, list):
        raise CongestionArtifactError("congestion artifact records must be an array")

    result: dict[int, Congestion] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise CongestionArtifactError(
                f"congestion records[{index}] must be an object"
            )
        line_id = record.get("line_id")
        if isinstance(line_id, bool) or not isinstance(line_id, int):
            raise CongestionArtifactError(
                f"congestion records[{index}].line_id must be an integer"
            )
        if line_id in result:
            raise CongestionArtifactError(
                f"congestion artifact repeats line_id {line_id}"
            )
        payload = {key: value for key, value in record.items() if key != "line_id"}
        try:
            result[line_id] = _CONGESTION.validate_python(payload)
        except ValidationError as exc:
            raise CongestionArtifactError(
                f"congestion records[{index}] is not a typed congestion record: {exc}"
            ) from exc
    return result
