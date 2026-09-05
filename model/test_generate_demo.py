from __future__ import annotations

import copy
import hashlib
import json
import unittest

from model.generate_demo import (
    INPUT,
    OUTPUT,
    artifact_hash,
    execute_scenario,
    load_inputs,
    result_payload,
)


class DemoBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = load_inputs()

    def test_energy_is_derived_from_shared_duration(self) -> None:
        duration = self.inputs["assumptions"]["durationHours"]
        for scenario in result_payload(self.inputs)["scenarios"].values():
            self.assertEqual(
                scenario["metrics"]["shedMwh"], scenario["metrics"]["shedMw"] * duration
            )

    def test_interventions_and_baseline_have_identical_assumptions(self) -> None:
        payload = result_payload(self.inputs)
        self.assertEqual(
            {item["assumptionSetId"] for item in payload["scenarios"].values()},
            {payload["execution"]["assumptionSetId"]},
        )

    def test_output_is_derived_from_the_source_backed_input(self) -> None:
        changed = copy.deepcopy(self.inputs)
        changed["interventions"][0]["modeledContributionMw"] = 100
        scenario = execute_scenario(changed, changed["interventions"][0])
        self.assertEqual(scenario["metrics"]["shedMw"], 88)
        self.assertEqual(scenario["provenance"]["artifactId"], changed["artifactId"])
        self.assertEqual(scenario["units"]["shedMwh"], "MWh")

    def test_fixture_remains_explicitly_synthetic(self) -> None:
        payload = result_payload(self.inputs)
        self.assertEqual(
            payload["execution"]["modelMode"], "synthetic_power_balance_preview"
        )
        self.assertTrue(
            any(
                "not a grid-flow" in item
                for item in payload["execution"]["limitations"]
            )
        )

    def test_improvement_is_baseline_shed_minus_candidate_shed(self) -> None:
        payload = result_payload(self.inputs)
        baseline_shed = payload["scenarios"]["baseline"]["metrics"]["shedMw"]
        self.assertEqual(
            payload["scenarios"]["baseline"]["metrics"]["improvementMw"], 0
        )
        for scenario_id, scenario in payload["scenarios"].items():
            if scenario_id == "baseline":
                continue
            metrics = scenario["metrics"]
            self.assertEqual(
                metrics["improvementMw"], baseline_shed - metrics["shedMw"]
            )
            self.assertGreater(metrics["improvementMw"], 0, scenario_id)

        changed = copy.deepcopy(self.inputs)
        changed["interventions"][0]["modeledContributionMw"] = 100
        scenario = execute_scenario(changed, changed["interventions"][0])
        self.assertEqual(scenario["metrics"]["improvementMw"], 100)

    def test_every_scenario_carries_units_provenance_and_limitations(self) -> None:
        payload = result_payload(self.inputs)
        expected_units = {
            "shedMw": "MW",
            "shedMwh": "MWh",
            "availableGenerationMw": "MW",
            "demandMw": "MW",
            "improvementMw": "MW",
            "lineLoading": "%",
        }
        self.assertEqual(
            len(payload["scenarios"]), 1 + len(self.inputs["interventions"])
        )
        for scenario_id, scenario in payload["scenarios"].items():
            self.assertEqual(scenario["units"], expected_units, scenario_id)
            self.assertEqual(
                scenario["limitations"], self.inputs["limitations"], scenario_id
            )
            self.assertTrue(scenario["limitations"], scenario_id)
            self.assertEqual(
                scenario["provenance"]["artifactId"], self.inputs["artifactId"]
            )
            self.assertEqual(
                scenario["provenance"]["inputHash"], payload["fixtureHash"]
            )
            self.assertRegex(scenario["provenance"]["inputHash"], r"^[0-9a-f]{12}$")

    def test_line_loadings_apply_candidate_multipliers(self) -> None:
        lines = {
            line["id"]: line["baselineLoadingPct"]
            for line in self.inputs["network"]["lines"]
        }
        baseline = execute_scenario(self.inputs, None)["metrics"]["lineLoadings"]
        self.assertEqual(baseline, lines)

        intervention = self.inputs["interventions"][0]
        expected = {
            line_id: round(base * intervention["lineLoadingMultipliers"][line_id])
            for line_id, base in lines.items()
        }
        self.assertEqual(
            execute_scenario(self.inputs, intervention)["metrics"]["lineLoadings"],
            expected,
        )

        changed = copy.deepcopy(self.inputs)
        changed["interventions"][0]["lineLoadingMultipliers"]["w-n"] = 0.5
        loadings = execute_scenario(changed, changed["interventions"][0])["metrics"][
            "lineLoadings"
        ]
        self.assertEqual(loadings["w-n"], round(lines["w-n"] * 0.5))
        self.assertNotEqual(loadings["w-n"], expected["w-n"])
        self.assertEqual(
            {k: v for k, v in loadings.items() if k != "w-n"},
            {k: v for k, v in expected.items() if k != "w-n"},
        )

    def test_committed_bundle_matches_generator_output(self) -> None:
        committed = json.loads(OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(committed, result_payload())

    def test_input_hash_is_sha256_of_canonical_json_not_file_bytes(self) -> None:
        canonical = json.dumps(
            self.inputs, sort_keys=True, separators=(",", ":")
        ).encode()
        expected = hashlib.sha256(canonical).hexdigest()[:12]
        self.assertEqual(artifact_hash(self.inputs), expected)
        payload = result_payload(self.inputs)
        self.assertEqual(payload["fixtureHash"], expected)
        self.assertEqual(payload["execution"]["provenance"]["inputHash"], expected)
        # Documented choice: the pretty-printed committed file hashes differently.
        self.assertNotEqual(
            expected, hashlib.sha256(INPUT.read_bytes()).hexdigest()[:12]
        )
