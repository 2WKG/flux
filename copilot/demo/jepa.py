"""Read a separately-labelled experimental JEPA count-forecast artifact.

This is a supplemental demo card loader, not a registered Copilot tool.  The
artifact forecasts observed customers-out counts from an observed history.  It
cannot be translated into weather, outage probability, physical-grid, or
cascade claims by this adapter.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from copilot.demo.bridge import DemoToolResult

DEFAULT_JEPA_ARTIFACT = Path(
    "data/artifacts/jepa/eaglei-2024-count-v1/jepa_count_forecast_artifact.json"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_KIND = "experimental_jepa_count_forecast"


def read_experimental_jepa_forecast(
    path: Path = DEFAULT_JEPA_ARTIFACT, *, county_fips: str | None = None
) -> DemoToolResult:
    """Return an exact, labelled artifact slice or a named unavailable result."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _unavailable("The experimental JEPA forecast artifact is not installed.")
    except (OSError, json.JSONDecodeError):
        return _unavailable("The experimental JEPA forecast artifact cannot be read.")
    if not isinstance(value, dict):
        return _unavailable("The experimental JEPA forecast artifact is malformed.")

    issue = _validate(value, county_fips)
    if issue is not None:
        return _unavailable(issue)

    source = value["source"]
    forecast = value["forecast"]
    assert isinstance(source, dict) and isinstance(forecast, dict)
    source_sha = str(source["sha256"])
    model_version = str(value["model_version"])
    limitations = tuple(str(item) for item in value["limitations"])
    return DemoToolResult(
        status="available",
        label="Experimental observed-count trajectory forecast",
        data={
            "artifact_kind": value["artifact_kind"],
            "status": value["status"],
            "model_version": model_version,
            "source": source,
            "scope": value["scope"],
            "split": value["split"],
            "metrics": value["metrics"],
            "forecast": forecast,
            "limitations": list(limitations),
        },
        provenance=(
            f"artifact:jepa:{source_sha[:16]}",
            f"source_sha256:{source_sha}",
            f"artifact_path:{path.as_posix()}",
        ),
        limitations=limitations,
    )


def _validate(value: dict[str, Any], county_fips: str | None) -> str | None:
    if value.get("artifact_kind") != _EXPECTED_KIND:
        return "The artifact is not an experimental JEPA count forecast."
    if value.get("status") != "experimental":
        return "The JEPA artifact is not explicitly marked experimental."
    source = value.get("source")
    scope = value.get("scope")
    forecast = value.get("forecast")
    limitations = value.get("limitations")
    if not isinstance(source, dict) or not _SHA256.fullmatch(str(source.get("sha256", ""))):
        return "The JEPA artifact has no valid source SHA-256."
    if not isinstance(scope, dict) or not isinstance(forecast, dict):
        return "The JEPA artifact has no valid scope or forecast record."
    observed = scope.get("observed_county_fips")
    forecast_county = forecast.get("county_fips")
    if not isinstance(observed, list) or not isinstance(forecast_county, str):
        return "The JEPA artifact has no observed county coverage record."
    if forecast_county not in observed:
        return "The JEPA forecast county is outside its observed coverage."
    if county_fips is not None and county_fips != forecast_county:
        return "No experimental JEPA forecast is available for the selected county."
    if not isinstance(value.get("model_version"), str) or not value["model_version"]:
        return "The JEPA artifact has no model version."
    if not isinstance(limitations, list) or not limitations or not all(
        isinstance(item, str) and item for item in limitations
    ):
        return "The JEPA artifact has no usable limitations."
    predicted, actual = _count_arrays(forecast)
    if predicted is None or actual is None or len(predicted) != len(actual) or not predicted:
        return "The JEPA artifact has invalid forecast count arrays."
    return None


def _count_arrays(forecast: dict[str, Any]) -> tuple[list[Any] | None, list[Any] | None]:
    """Accept the two explicit count-array spellings used by artifact revisions."""

    predicted = forecast.get("predicted_customers_out", forecast.get("predicted_counts"))
    actual = forecast.get("actual_customers_out", forecast.get("actual_counts"))
    return (
        predicted if isinstance(predicted, list) else None,
        actual if isinstance(actual, list) else None,
    )


def _unavailable(reason: str) -> DemoToolResult:
    return DemoToolResult(
        status="unavailable",
        label="Experimental observed-count trajectory forecast",
        reason=reason,
        limitations=(
            "This artifact is experimental and cannot support weather, probability, or cascade claims.",
        ),
    )
