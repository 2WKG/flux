from __future__ import annotations

import copy
import unittest

from model.generate_demo import execute_scenario, load_inputs, result_payload


class DemoBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = load_inputs()

    def test_energy_is_derived_from_shared_duration(self) -> None:
        duration = self.inputs["assumptions"]["durationHours"]
        for scenario in result_payload(self.inputs)["scenarios"].values():
            self.assertEqual(scenario["metrics"]["shedMwh"], scenario["metrics"]["shedMw"] * duration)

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
        self.assertEqual(payload["execution"]["modelMode"], "synthetic_power_balance_preview")
        self.assertTrue(any("not a grid-flow" in item for item in payload["execution"]["limitations"]))
