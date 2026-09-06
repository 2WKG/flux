"""Generate and validate the evidence-bound P0 Uri/Beryl calibration report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "data/calibration/p0-uri-beryl-calibration-ledger-v1.json"
DEFAULT_JSON_OUT = ROOT / "data/calibration/p0-uri-beryl-calibration-report-v1.json"
DEFAULT_MARKDOWN_OUT = ROOT / "docs/data/p0-uri-beryl-calibration.md"
VALUE_CLASSES = {"observed", "proxy", "modeled", "unavailable"}
REQUIRED_EVIDENCE_IDS = {
    "county_outage_observations",
    "county_weather_observations",
    "balancing_authority_demand",
    "hazard_or_event_observations",
    "operational_observations",
}
REQUIRED_LIMITS = {"syntheticTopologyMapping", "nonNodalAggregate", "restrictedData"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _exact_keys(value: Any, label: str, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        raise ValueError(f"{label} fields must be exactly {sorted(expected)}")
    return value


def load_ledger(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_ledger(ledger: dict[str, Any], *, repo_root: Path = ROOT) -> None:
    _exact_keys(
        ledger,
        "ledger",
        {
            "schemaVersion",
            "artifactId",
            "reportAsOf",
            "policy",
            "topologyContext",
            "requiredEvidence",
            "scenarios",
        },
    )
    if (
        ledger["schemaVersion"] != 1
        or ledger["artifactId"] != "flux:p0-uri-beryl-calibration-ledger:v1"
    ):
        raise ValueError("unsupported calibration ledger identity")
    policy = _exact_keys(
        ledger["policy"], "policy", {"calibrationRule", "allowedValueClasses", "scope"}
    )
    if (
        policy["calibrationRule"]
        != "fail_closed_when_required_observations_are_not_checked_in"
    ):
        raise ValueError("calibration policy must fail closed")
    if set(policy["allowedValueClasses"]) != VALUE_CLASSES:
        raise ValueError(
            "policy must enumerate observed, proxy, modeled, and unavailable"
        )

    topology = _exact_keys(
        ledger["topologyContext"],
        "topologyContext",
        {"valueClass", "role", "receipt", "receiptSha256", "citation", "mappingLimit"},
    )
    if (
        topology["valueClass"] != "modeled"
        or topology["role"] != "context_only_not_calibration_evidence"
    ):
        raise ValueError(
            "synthetic topology must remain modeled context, not calibration evidence"
        )
    receipt = repo_root / topology["receipt"]
    if not receipt.is_file() or _sha256(receipt) != topology["receiptSha256"]:
        raise ValueError("topology receipt is missing or its checksum changed")

    evidence = ledger["requiredEvidence"]
    if (
        not isinstance(evidence, list)
        or {item.get("id") for item in evidence} != REQUIRED_EVIDENCE_IDS
    ):
        raise ValueError("ledger must declare every required evidence category")
    for item in evidence:
        _exact_keys(
            item,
            f"evidence {item.get('id')}",
            {
                "id",
                "status",
                "source",
                "vintage",
                "coverage",
                "transformation",
                "method",
            },
        )
        if item["status"] != "unavailable" or any(
            item[key] != "not performed" for key in ("transformation", "method")
        ):
            raise ValueError(
                "unchecked-in evidence must remain unavailable and untransformed"
            )

    scenarios = ledger["scenarios"]
    if not isinstance(scenarios, list) or [
        item.get("scenarioId") for item in scenarios
    ] != ["uri_2021", "beryl_2024"]:
        raise ValueError("ledger must contain Uri then Beryl")
    for scenario in scenarios:
        _exact_keys(
            scenario,
            f"scenario {scenario.get('scenarioId')}",
            {
                "scenarioId",
                "label",
                "window",
                "evidenceIds",
                "calibration",
                "result",
                "comparison",
                "limits",
            },
        )
        if set(scenario["evidenceIds"]) != REQUIRED_EVIDENCE_IDS:
            raise ValueError(
                f"{scenario['scenarioId']} must require every evidence category"
            )
        calibration = _exact_keys(
            scenario["calibration"], "calibration", {"status", "method", "reason"}
        )
        if (
            calibration["status"] != "unavailable"
            or calibration["method"] != "not performed"
        ):
            raise ValueError(
                "calibration cannot be claimed without checked-in evidence"
            )
        result = _exact_keys(
            scenario["result"],
            "result",
            {
                "quantity",
                "valueClass",
                "value",
                "unit",
                "source",
                "vintage",
                "coverage",
                "transformation",
                "method",
                "uncertainty",
            },
        )
        if (
            result["valueClass"] != "unavailable"
            or result["value"] is not None
            or result["unit"] is not None
        ):
            raise ValueError(
                "no-evidence calibration result must be unavailable with no value"
            )
        if any(result[key] != "not performed" for key in ("transformation", "method")):
            raise ValueError(
                "unavailable result cannot claim a transformation or method"
            )
        comparison = _exact_keys(
            scenario["comparison"], "comparison", {"status", "reason"}
        )
        if comparison["status"] != "not_performed":
            raise ValueError(
                "like-for-like comparison must not run without observed and modeled values"
            )
        limits = scenario["limits"]
        if (
            not isinstance(limits, dict)
            or set(limits) != REQUIRED_LIMITS
            or not all(isinstance(value, str) and value for value in limits.values())
        ):
            raise ValueError(
                "each result must disclose all topology, aggregate, and restricted-data limits"
            )


def build_report(
    ledger: dict[str, Any], *, ledger_path: Path, repo_root: Path = ROOT
) -> dict[str, Any]:
    validate_ledger(ledger, repo_root=repo_root)
    results = []
    for scenario in ledger["scenarios"]:
        results.append(
            {
                "scenarioId": scenario["scenarioId"],
                "label": scenario["label"],
                "window": scenario["window"],
                "calibrationStatus": scenario["calibration"]["status"],
                "result": scenario["result"],
                "comparison": scenario["comparison"],
                "limits": scenario["limits"],
            }
        )
    return {
        "schemaVersion": 1,
        "artifactId": "flux:p0-uri-beryl-calibration-report:v1",
        "reportAsOf": ledger["reportAsOf"],
        "inputLedger": {
            "path": ledger_path.relative_to(repo_root).as_posix(),
            "sha256": _sha256(ledger_path),
        },
        "evidenceStatus": {
            "observed": 0,
            "proxy": 0,
            "modeled": 0,
            "unavailable": len(results),
        },
        "topologyContext": ledger["topologyContext"],
        "requiredEvidence": ledger["requiredEvidence"],
        "results": results,
        "conclusion": "No P0 Uri or Beryl calibration is available. The report fails closed because required public observations are not checked in.",
    }


def render_markdown(report: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {item['scenarioId']} | {item['calibrationStatus']} | {item['result']['valueClass']} | {item['comparison']['status']} |"
        for item in report["results"]
    )
    limits = "\n\n".join(
        f"### {item['label']} (`{item['scenarioId']}`)\n\n"
        f"- Like-for-like comparison: {item['comparison']['status']} — {item['comparison']['reason']}\n"
        f"- Synthetic-topology mapping: {item['limits']['syntheticTopologyMapping']}\n"
        f"- Non-nodal/aggregate limit: {item['limits']['nonNodalAggregate']}\n"
        f"- Restricted-data limit: {item['limits']['restrictedData']}\n"
        f"- Uncertainty: {item['result']['uncertainty']}"
        for item in report["results"]
    )
    return (
        "# P0 Uri/Beryl calibration status\n\n"
        f"Generated from `{report['inputLedger']['path']}` (SHA-256 `{report['inputLedger']['sha256']}`). "
        "This is a reproducible fail-closed report, not a reconstruction or calibration claim.\n\n"
        "## Result classes\n\n"
        "| Observed | Proxy | Modeled | Unavailable |\n| ---: | ---: | ---: | ---: |\n"
        f"| {report['evidenceStatus']['observed']} | {report['evidenceStatus']['proxy']} | {report['evidenceStatus']['modeled']} | {report['evidenceStatus']['unavailable']} |\n\n"
        "## Scenario results\n\n"
        "| Scenario | Calibration | Result class | Like-for-like comparison |\n| --- | --- | --- | --- |\n"
        f"{rows}\n\n{report['conclusion']}\n\n"
        "## Citable topology context, not calibration evidence\n\n"
        f"`{report['topologyContext']['receipt']}` (SHA-256 `{report['topologyContext']['receiptSha256']}`) records: "
        f"{report['topologyContext']['citation']}. {report['topologyContext']['mappingLimit']}\n\n"
        "## Per-result limits\n\n"
        f"{limits}\n"
    )


def write_report(
    ledger_path: Path, json_out: Path, markdown_out: Path, *, repo_root: Path = ROOT
) -> dict[str, Any]:
    report = build_report(
        load_ledger(ledger_path), ledger_path=ledger_path, repo_root=repo_root
    )
    json_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_out.write_text(render_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT)
    parser.add_argument("--markdown-out", type=Path, default=DEFAULT_MARKDOWN_OUT)
    args = parser.parse_args()
    try:
        report = write_report(args.ledger, args.json_out, args.markdown_out)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(
        f"WROTE: {args.json_out} and {args.markdown_out}; unavailable={report['evidenceStatus']['unavailable']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
