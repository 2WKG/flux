"""Per-provider renderings of the one frozen tool contract.

`copilot.tools.schemas.TOOL_SCHEMAS` is the contract, already in Anthropic's
`ToolParam` shape.  Gemini declares the same tools as `FunctionDeclaration`
entries whose parameters are supplied as JSON Schema.  Only the wrapper differs:
the tool names, descriptions, and parameter schemas must stay identical, which
is what makes the two providers interchangeable behind one event contract.
"""

from __future__ import annotations

from typing import Any

from copilot.tools.schemas import TOOL_SCHEMAS


def anthropic_tools() -> list[dict[str, Any]]:
    """The frozen contract as Anthropic strict tools."""
    return [dict(schema) for schema in TOOL_SCHEMAS]


def gemini_tools() -> list[dict[str, Any]]:
    """The same contract as Gemini function declarations.

    `strict` has no Gemini equivalent; the schema keeps `additionalProperties`
    and an explicit `required` list, which is how the same closedness is stated
    there.  The declarations are returned as plain dicts so this module stays
    importable (and testable) without the provider SDK installed.
    """
    return [
        {
            "name": schema["name"],
            "description": schema["description"],
            "parameters_json_schema": schema["input_schema"],
        }
        for schema in TOOL_SCHEMAS
    ]
