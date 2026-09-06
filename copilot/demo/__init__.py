"""Small, dependency-injected backend contracts for the interactive demo."""

from copilot.demo.ask_backend import (
    CoreCascadeEvidence,
    DemoAskBackend,
    DeterministicNarrationProvider,
)
from copilot.demo.bridge import DemoCapability, DemoToolBridge, DemoToolResult
from copilot.demo.data import create_demo_data_router
from copilot.demo.interactive import (
    InteractiveAskBackend,
    InteractiveEvidence,
    InteractiveToolBridge,
)
from copilot.demo.jepa import read_experimental_jepa_forecast
from copilot.demo.model import create_demo_model_router
from copilot.demo.runtime import CoreCascadeRunner, build_demo_ask_backend

__all__ = (
    "CoreCascadeEvidence",
    "CoreCascadeRunner",
    "DemoAskBackend",
    "DemoCapability",
    "DemoToolBridge",
    "DemoToolResult",
    "DeterministicNarrationProvider",
    "InteractiveAskBackend",
    "InteractiveEvidence",
    "InteractiveToolBridge",
    "build_demo_ask_backend",
    "create_demo_data_router",
    "create_demo_model_router",
    "read_experimental_jepa_forecast",
)
