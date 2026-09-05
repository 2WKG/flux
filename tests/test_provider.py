import unittest

from copilot.provider import (
    MAX_RETRIES,
    MODEL_ID,
    REQUEST_TIMEOUT_S,
    ProviderState,
    availability,
)


class ProviderAvailabilityTests(unittest.TestCase):
    def test_missing_credentials_is_unavailable(self):
        status = availability({})
        self.assertEqual((status.state, status.code), (ProviderState.UNAVAILABLE, "missing_credentials"))

    def test_unknown_model_is_unavailable(self):
        status = availability({"ANTHROPIC_API_KEY": "test", "COPILOT_MODEL": "unknown"})
        self.assertEqual((status.state, status.code), (ProviderState.UNAVAILABLE, "unsupported_model"))

    def test_quota_is_unavailable(self):
        status = availability({"ANTHROPIC_API_KEY": "test"}, "quota")
        self.assertEqual((status.state, status.code), (ProviderState.UNAVAILABLE, "quota_exhausted"))

    def test_provider_error_is_explicit(self):
        status = availability({"ANTHROPIC_API_KEY": "test"}, "network")
        self.assertEqual((status.state, status.code), (ProviderState.ERROR, "provider_error"))

    def test_policy_is_bounded(self):
        self.assertEqual(MODEL_ID, "claude-opus-5")
        self.assertEqual(REQUEST_TIMEOUT_S, 30)
        self.assertEqual(MAX_RETRIES, 0)
