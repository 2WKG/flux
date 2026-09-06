"""Small, dependency-injected backend contracts for the interactive demo."""

from copilot.demo.bridge import (
    DemoCapability,
    DemoToolBridge,
    DemoToolResult,
)

__all__ = ("DemoCapability", "DemoToolBridge", "DemoToolResult")
