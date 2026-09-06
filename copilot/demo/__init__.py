"""Small, dependency-injected backend contracts for the interactive demo."""

from copilot.demo.ask_backend import (
    CoreCascadeEvidence,
    DemoAskBackend,
    DeterministicNarrationProvider,
)
from copilot.demo.bridge import DemoCapability, DemoToolBridge, DemoToolResult
from copilot.demo.jepa import read_experimental_jepa_forecast
from copilot.demo.runtime import CoreCascadeRunner, build_demo_ask_backend

__all__ = (
    "CoreCascadeEvidence",
    "CoreCascadeRunner",
    "DemoAskBackend",
    "DemoCapability",
    "DemoToolBridge",
    "DemoToolResult",
    "DeterministicNarrationProvider",
    "build_demo_ask_backend",
    "read_experimental_jepa_forecast",
)
