"""Export the Copilot tool contracts to JSON Schema and TypeScript declarations.

``copilot/tools/schemas.py`` is the only source of truth for the tool
contracts, and ``pipelines/labels.py`` for the node-annotation vocabularies.
This script writes ``web/src/contracts/copilot-tools.schema.json``,
``web/src/contracts/copilot-tools.d.ts`` and
``web/src/contracts/node-annotations.json`` deterministically (sorted keys, 2-space
indent, trailing newline) so ``gate/contract-drift`` can prove the committed
copies match. Run it with::

    uv run --extra dev python scripts/ci/export_tool_contracts.py

The TypeScript generator has no npm dependency and only handles the JSON Schema
subset pydantic emits for ``schemas.py``; it fails loudly on anything else.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
# pyproject sets package=false, so mirror pytest's pythonpath=["."] here.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from copilot.tools import schemas
from pipelines.labels import (
    BINDING_RECEIPT_ABSENT,
    BINDING_RECEIPT_MISSING,
    FIELD_PROVENANCE_TOKENS,
    NODE_ROLES,
    SYNTHETIC_TOPOLOGY_LABEL,
)

OUT_DIR = REPO_ROOT / "web" / "src" / "contracts"
SCHEMA_PATH = OUT_DIR / "copilot-tools.schema.json"
TS_PATH = OUT_DIR / "copilot-tools.d.ts"
NODE_ANNOTATIONS_PATH = OUT_DIR / "node-annotations.json"
REGENERATE = "uv run --extra dev python scripts/ci/export_tool_contracts.py"


def public_models() -> list[type[BaseModel]]:
    found = [
        obj
        for name, obj in inspect.getmembers(schemas, inspect.isclass)
        if issubclass(obj, BaseModel)
        and obj.__module__ == schemas.__name__
        and not name.startswith("_")
    ]
    return sorted(found, key=lambda model: model.__name__)


def build_schema_document() -> dict[str, Any]:
    defs: dict[str, Any] = {}
    for model in public_models():
        schema = model.model_json_schema(ref_template="#/$defs/{model}")
        nested = schema.pop("$defs", {})
        for name, definition in nested.items():
            previous = defs.get(name)
            if previous is not None and previous != definition:
                raise SystemExit(f"conflicting $defs for {name}")
            defs[name] = definition
        defs[model.__name__] = schema
    tools = {
        tool.name: {
            "description": tool.description,
            "input": f"#/$defs/{tool.input_model.__name__}",
            "output": [f"#/$defs/{model.__name__}" for model in tool.output_model],
        }
        for tool in schemas.TOOL_REGISTRY
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "flux://copilot/tools",
        "title": "Flux Copilot tool contracts",
        "description": f"Generated from copilot/tools/schemas.py by {REGENERATE}",
        "$defs": defs,
        "tools": tools,
    }


def build_node_annotation_document() -> dict[str, Any]:
    """The vocabularies `GET /layers/buses` annotations use, for the browser.

    `docs/specs/05-copilot.md` declares them; `pipelines/labels.py` holds them.
    Browser code imports this file instead of restating the strings, so a fork
    is a `gate/contract-drift` failure rather than a silent divergence.
    """
    return {
        "$id": "flux://layers/node-annotations",
        "description": (
            "Vocabularies for GET /layers/buses node annotations. "
            f"Generated from pipelines/labels.py by {REGENERATE}"
        ),
        "binding_receipt_absent": BINDING_RECEIPT_ABSENT,
        "binding_receipt_missing": BINDING_RECEIPT_MISSING,
        "field_provenance_tokens": list(FIELD_PROVENANCE_TOKENS),
        "node_roles": list(NODE_ROLES),
        "synthetic_topology_label": SYNTHETIC_TOPOLOGY_LABEL,
    }


def ts_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value)


def ts_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "oneOf" in schema:
        variants = " | ".join(ts_type(item) for item in schema["oneOf"])
        if schema.get("type") == "object" or "properties" in schema:
            return f"{ts_object(schema)} & ({variants})"
        return variants
    if "const" in schema:
        return ts_literal(schema["const"])
    if "enum" in schema:
        return " | ".join(ts_literal(item) for item in schema["enum"])
    if "anyOf" in schema:
        members = [ts_type(item) for item in schema["anyOf"]]
        return " | ".join(dict.fromkeys(members))  # dedupe, keep order
    if "properties" in schema:
        return ts_object(schema)
    kind = schema.get("type")
    if kind is None:
        return "unknown"
    if isinstance(kind, list):
        return " | ".join(ts_type({**schema, "type": item}) for item in kind)
    if kind == "string":
        return "string"
    if kind in ("number", "integer"):
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"
    if kind == "array":
        items = schema.get("items", {})
        if "prefixItems" in schema:
            raise SystemExit("tuple schemas are not supported by the TS generator")
        inner = ts_type(items)
        return f"Array<{inner}>" if " " in inner else f"{inner}[]"
    if kind == "object":
        extra = schema.get("additionalProperties", True)
        return (
            "Record<string, unknown>"
            if extra is True
            else f"Record<string, {ts_type(extra)}>"
        )
    raise SystemExit(f"unsupported JSON Schema type: {kind!r}")


def ts_object(schema: dict[str, Any]) -> str:
    return "{ " + " ".join(ts_members(schema)) + " }"


def ts_members(schema: dict[str, Any]) -> list[str]:
    required = set(schema.get("required", ()))
    members = []
    for name in sorted(schema.get("properties", {})):
        suffix = "" if name in required else "?"
        members.append(f"{name}{suffix}: {ts_type(schema['properties'][name])};")
    return members


def render_ts(document: dict[str, Any]) -> str:
    lines = [
        "// GENERATED FILE - DO NOT EDIT.",
        f"// Source: copilot/tools/schemas.py. Regenerate: {REGENERATE}",
        "",
    ]
    for name in sorted(document["$defs"]):
        definition = document["$defs"][name]
        if (
            definition.get("type") == "object"
            and "properties" in definition
            and "oneOf" not in definition
        ):
            lines.append(f"export interface {name} {{")
            lines.extend(f"  {member}" for member in ts_members(definition))
            lines.append("}")
        else:
            lines.append(f"export type {name} = {ts_type(definition)};")
        lines.append("")
    tools = document["tools"]
    lines.append(
        "export type ToolName = " + " | ".join(json.dumps(n) for n in tools) + ";"
    )
    lines.append("")
    lines.append("export interface ToolContracts {")
    for name, tool in tools.items():
        output = " | ".join(ref.rsplit("/", 1)[-1] for ref in tool["output"])
        lines.append(
            f"  {name}: {{ input: {tool['input'].rsplit('/', 1)[-1]}; output: {output} }};"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    document = build_schema_document()
    outputs = {
        SCHEMA_PATH: json.dumps(document, indent=2, sort_keys=True) + "\n",
        TS_PATH: render_ts(document),
        NODE_ANNOTATIONS_PATH: json.dumps(
            build_node_annotation_document(), indent=2, sort_keys=True
        )
        + "\n",
    }
    drifted = [
        p for p, text in outputs.items() if not p.exists() or p.read_text() != text
    ]
    if check:
        for path in drifted:
            print(
                f"drift: {path.relative_to(REPO_ROOT)} (regenerate with `{REGENERATE}`)"
            )
        return 1 if drifted else 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, text in outputs.items():
        path.write_text(text)
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
