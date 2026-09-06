from __future__ import annotations

import copy
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "scenario_validator", ROOT / "scripts" / "validate_scenario_config.py"
)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validator)
EXAMPLE = json.loads(
    (
        ROOT / "configs" / "scenarios" / "examples" / "mn_evening_net_load_stress.json"
    ).read_text(encoding="utf-8")
)


class ScenarioConfigValidationTests(unittest.TestCase):
    def test_example_is_valid(self):
        validator.validate(EXAMPLE)

    def test_rejects_invalid_utc_calendar_value(self):
        config = copy.deepcopy(EXAMPLE)
        config["scenario"]["time_window"]["start_utc"] = "2023-02-30T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "real UTC"):
            validator.validate(config)

    def test_rejects_value_marked_unsupported(self):
        config = copy.deepcopy(EXAMPLE)
        config["resources"]["storage"][0]["power_mw"]["value"] = 10
        with self.assertRaisesRegex(ValueError, "must be null"):
            validator.validate(config)

    def test_rejects_unknown_field_and_supported_missing_artifact(self):
        config = copy.deepcopy(EXAMPLE)
        config["time_series"]["demand"]["typo"] = True
        with self.assertRaisesRegex(ValueError, "unknown field"):
            validator.validate(config)
        config = copy.deepcopy(EXAMPLE)
        config["time_series"]["demand"]["status"] = "supported"
        config["time_series"]["demand"]["artifact_id"] = None
        with self.assertRaisesRegex(ValueError, "must identify"):
            validator.validate(config)

    def test_rejects_activation_with_unsupported_capabilities(self):
        config = copy.deepcopy(EXAMPLE)
        config["scenario"]["execution_status"] = "ready_for_adapter"
        with self.assertRaisesRegex(ValueError, "cannot activate"):
            validator.validate(config)

    def test_rejects_schema_incompatible_values(self):
        config = copy.deepcopy(EXAMPLE)
        config["scenario"]["id"] = "not-valid"
        with self.assertRaisesRegex(ValueError, "scenario.id"):
            validator.validate(config)
        config = copy.deepcopy(EXAMPLE)
        config["scenario"]["time_window"]["interval_minutes"] = True
        with self.assertRaisesRegex(ValueError, "positive integer"):
            validator.validate(config)

    def test_rejects_non_finite_samples_and_resource_quantities(self):
        for value in (math.nan, math.inf, -math.inf):
            config = copy.deepcopy(EXAMPLE)
            config["time_series"]["demand"]["samples"][0]["value"] = value
            with self.assertRaisesRegex(ValueError, "finite number"):
                validator.validate(config)

            config = copy.deepcopy(EXAMPLE)
            ramp = config["resources"]["generation"][0]["ramp_mw_per_min"]
            ramp["status"] = "supported"
            ramp["value"] = value
            with self.assertRaisesRegex(ValueError, "finite number"):
                validator.validate(config)

    def test_rejects_non_finite_json_tokens_at_parse_time(self):
        for token in ("NaN", "Infinity", "-Infinity"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                path.write_text('{"value": ' + token + "}", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "non-finite numeric"):
                    validator.load_config(path)
