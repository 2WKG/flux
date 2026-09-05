"""Focused semantic checks for scenario-config-v1 JSON documents."""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


def is_finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"JSON non-finite numeric value is not allowed: {value}")


def load_config(path: Path) -> dict:
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_non_finite_json_constant,
    )


def parse_utc(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError(f"{label} must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} is not a real UTC timestamp: {value}") from exc


def object_keys(value: object, label: str, required: set[str]) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = set(value) - required
    missing = required - set(value)
    if unknown:
        raise ValueError(f"{label} has unknown field(s): {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"{label} is missing field(s): {', '.join(sorted(missing))}")
    return value


def validate_provenance(value: object, label: str) -> None:
    provenance = object_keys(value, label, {"source_id", "url", "retrieved_at_utc", "scope"})
    if not all(isinstance(provenance[key], str) and provenance[key] for key in ("source_id", "scope")):
        raise ValueError(f"{label}.source_id and scope must be non-empty strings")
    parsed_url = urlparse(provenance["url"])
    if not parsed_url.scheme or not parsed_url.netloc:
        raise ValueError(f"{label}.url must be an absolute URL")
    parse_utc(provenance["retrieved_at_utc"], f"{label}.retrieved_at_utc")


def validate_reference(value: object, label: str, *, time_series: bool, start: datetime | None = None, end: datetime | None = None) -> None:
    keys = {"artifact_id", "status", "provenance"}
    if time_series:
        keys |= {"unit", "time_basis", "samples"}
    reference = object_keys(value, label, keys)
    if reference["status"] not in {"supported", "unavailable"}:
        raise ValueError(f"{label}.status must be supported or unavailable")
    artifact = reference["artifact_id"]
    if reference["status"] == "supported" and (not isinstance(artifact, str) or not artifact):
        raise ValueError(f"{label}.artifact_id must identify supported input")
    if reference["status"] == "unavailable" and artifact is not None:
        raise ValueError(f"{label}.artifact_id must be null when unavailable")
    if time_series:
        if not isinstance(reference["unit"], str) or not reference["unit"]:
            raise ValueError(f"{label}.unit is required")
        if reference["time_basis"] != "UTC":
            raise ValueError(f"{label}.time_basis must be UTC")
        if not isinstance(reference["samples"], list):
            raise ValueError(f"{label}.samples must be an array")
        if reference["status"] == "supported" and not reference["samples"]:
            raise ValueError(f"{label}.samples are required for supported input")
        if reference["status"] == "unavailable" and reference["samples"]:
            raise ValueError(f"{label}.samples must be empty when unavailable")
        for index, sample in enumerate(reference["samples"]):
            sample = object_keys(sample, f"{label}.samples[{index}]", {"ts_utc", "value"})
            timestamp = parse_utc(sample["ts_utc"], f"{label}.samples[{index}].ts_utc")
            if start is not None and end is not None and not start <= timestamp < end:
                raise ValueError(f"{label}.samples[{index}] falls outside the scenario window")
            if not is_finite_number(sample["value"]):
                raise ValueError(f"{label}.samples[{index}].value must be a finite number")
    validate_provenance(reference["provenance"], f"{label}.provenance")


def validate_quantity(value: object, label: str, unit: str) -> None:
    quantity = object_keys(value, label, {"value", "unit", "status", "provenance"})
    if quantity["unit"] != unit:
        raise ValueError(f"{label}.unit must be {unit}")
    if quantity["status"] not in {"supported", "unsupported"}:
        raise ValueError(f"{label}.status must be supported or unsupported")
    if quantity["status"] == "unsupported" and quantity["value"] is not None:
        raise ValueError(f"{label} must be null when unsupported")
    if quantity["status"] == "supported" and not is_finite_number(quantity["value"]):
        raise ValueError(f"{label}.value must be a finite number when supported")
    if quantity["status"] == "supported" and quantity["value"] < 0:
        raise ValueError(f"{label}.value cannot be negative")
    if unit == "fraction" and quantity["status"] == "supported" and quantity["value"] > 1:
        raise ValueError(f"{label}.value must be at most 1")
    validate_provenance(quantity["provenance"], f"{label}.provenance")


def validate(config: dict) -> None:
    config = object_keys(config, "config", {"schema_version", "scenario", "static_context", "time_series", "resources", "provenance", "uncertainty"})
    if config["schema_version"] != 1:
        raise ValueError("schema_version must be 1")
    scenario = object_keys(config["scenario"], "scenario", {"id", "label", "class", "execution_status", "time_window"})
    if not isinstance(scenario["id"], str) or not re.fullmatch(r"[a-z][a-z0-9_]*", scenario["id"]):
        raise ValueError("scenario.id must use lowercase letters, digits, and underscores")
    if not isinstance(scenario["label"], str) or not scenario["label"]:
        raise ValueError("scenario.label must be a non-empty string")
    if scenario["class"] not in {"historical_weather_stress", "historical_operating_condition", "synthetic_stress", "forecast"}:
        raise ValueError("scenario.class is invalid")
    if scenario["execution_status"] not in {"example_only", "ready_for_adapter", "unavailable"}:
        raise ValueError("scenario.execution_status is invalid")
    window = object_keys(scenario["time_window"], "scenario.time_window", {"start_utc", "end_utc", "interval_minutes"})
    start = parse_utc(window.get("start_utc"), "scenario.time_window.start_utc")
    end = parse_utc(window.get("end_utc"), "scenario.time_window.end_utc")
    if end <= start:
        raise ValueError("scenario.time_window.end_utc must follow start_utc")
    if isinstance(window.get("interval_minutes"), bool) or not isinstance(window.get("interval_minutes"), int) or window["interval_minutes"] < 1:
        raise ValueError("scenario.time_window.interval_minutes must be a positive integer")

    static_context = object_keys(config["static_context"], "static_context", {"geography", "network"})
    references = []
    for name, reference in static_context.items():
        validate_reference(reference, f"static_context.{name}", time_series=False)
        references.append(reference)
    time_series = object_keys(config["time_series"], "time_series", {"demand", "weather", "outage", "availability"})
    for name, reference in time_series.items():
        validate_reference(reference, f"time_series.{name}", time_series=True, start=start, end=end)
        references.append(reference)

    resources = object_keys(config["resources"], "resources", {"generation", "storage"})
    if not all(isinstance(resources[group], list) for group in resources):
        raise ValueError("resources.generation and resources.storage must be arrays")
    quantities = []
    for index, generator in enumerate(resources["generation"]):
        generator = object_keys(generator, f"resources.generation[{index}]", {"resource_id", "fuel", "ramp_mw_per_min"})
        if not all(isinstance(generator[field], str) and generator[field] for field in ("resource_id", "fuel")):
            raise ValueError(f"resources.generation[{index}] resource_id and fuel must be non-empty strings")
        validate_quantity(generator["ramp_mw_per_min"], f"resources.generation[{index}].ramp_mw_per_min", "MW/min")
        quantities.append(generator["ramp_mw_per_min"])
    for index, storage in enumerate(resources["storage"]):
        storage = object_keys(storage, f"resources.storage[{index}]", {"resource_id", "power_mw", "energy_mwh", "state_of_charge"})
        if not isinstance(storage["resource_id"], str) or not storage["resource_id"]:
            raise ValueError(f"resources.storage[{index}].resource_id must be a non-empty string")
        validate_quantity(storage["power_mw"], f"resources.storage[{index}].power_mw", "MW")
        validate_quantity(storage["energy_mwh"], f"resources.storage[{index}].energy_mwh", "MWh")
        validate_quantity(storage["state_of_charge"], f"resources.storage[{index}].state_of_charge", "fraction")
        quantities.extend((storage["power_mw"], storage["energy_mwh"], storage["state_of_charge"]))
    if scenario["execution_status"] == "ready_for_adapter" and (
        any(reference["status"] != "supported" for reference in references)
        or any(quantity["status"] != "supported" for quantity in quantities)
    ):
        raise ValueError("ready_for_adapter cannot activate unavailable inputs or unsupported resource capabilities")
    validate_provenance(config["provenance"], "provenance")
    uncertainty = object_keys(config["uncertainty"], "uncertainty", {"level", "notes"})
    if uncertainty["level"] not in {"low", "medium", "high"} or not isinstance(uncertainty["notes"], list) or not uncertainty["notes"] or not all(isinstance(note, str) and note for note in uncertainty["notes"]):
        raise ValueError("uncertainty must have a level and at least one note")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_scenario_config.py PATH", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        config = load_config(path)
        validate(config)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"VALID: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
