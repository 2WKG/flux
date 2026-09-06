"""Small, dependency-injected backend contracts for the interactive demo."""

from copilot.demo.ask_backend import DemoAskBackend, DeterministicNarrationProvider
from copilot.demo.bridge import DemoCapability, DemoToolBridge, DemoToolResult
from copilot.demo.jepa import read_experimental_jepa_forecast

__all__ = (
    "DemoAskBackend",
    "DemoCapability",
    "DemoToolBridge",
    "DemoToolResult",
    "DeterministicNarrationProvider",
    "read_experimental_jepa_forecast",
)
