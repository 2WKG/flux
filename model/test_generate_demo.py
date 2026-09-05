import unittest

from generate_demo import DURATION_HOURS, result_payload


class DemoBundleTests(unittest.TestCase):
    def test_energy_is_derived_from_fixed_duration(self):
        for scenario in result_payload()["scenarios"].values():
            self.assertEqual(scenario["shedMwh"], scenario["shedMw"] * DURATION_HOURS)

    def test_candidates_improve_or_tie_baseline_honestly(self):
        scenarios = result_payload()["scenarios"]
        for key in ("a", "b"):
            self.assertEqual(scenarios[key]["improvementMw"], scenarios["baseline"]["shedMw"] - scenarios[key]["shedMw"])

    def test_fixture_is_explicitly_synthetic(self):
        payload = result_payload()
        self.assertIn("synthetic", payload["generatedFrom"])
        self.assertEqual(len(payload["network"]["candidates"]), 2)


if __name__ == "__main__":
    unittest.main()
