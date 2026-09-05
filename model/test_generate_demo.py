import unittest
from generate_demo import DURATION_HOURS, result_payload
class DemoBundleTests(unittest.TestCase):
    def test_energy_is_derived_from_fixed_duration(self):
        for scenario in result_payload()["scenarios"].values(): self.assertEqual(scenario["shedMwh"],scenario["shedMw"]*DURATION_HOURS)
    def test_candidates_have_signed_deltas(self):
        scenarios=result_payload()["scenarios"]
        for key in ("a","b"): self.assertEqual(scenarios[key]["improvementMw"],scenarios["baseline"]["shedMw"]-scenarios[key]["shedMw"])
    def test_contract_is_synthetic_and_ingestion_ready(self):
        payload=result_payload(); self.assertEqual(payload["dataStatus"]["mode"],"synthetic"); self.assertIn("ingestion",payload["dataStatus"]["next"])
