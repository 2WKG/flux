"""Provider-agnostic, bounded execution of the Copilot tool contract.

Providers choose a declared function; this module never infers a tool from a
question.  It validates every provider argument before invoking a registered
handler and gives the provider only immutable context plus prior tool results.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from pydantic import BaseModel, ValidationError

from copilot.tools.schemas import (
    TOOL_REGISTRY,
    ArtifactRef,
    BalanceInput,
    InteractiveCascadeInput,
    InteractiveData,
    RedundancyInput,
    ScenarioEditInput,
    unavailable_output,
    validate_tool_input,
)

MAX_TOOL_TURNS = 4


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    arguments: Mapping[str, object]
    result: Mapping[str, object]


@dataclass(frozen=True)
class AssistantText:
    text: str


class ToolCallingProvider(Protocol):
    """Common projection of Claude/Gemini function-call responses."""

    async def next_action(
        self,
        *,
        question: str,
        history: Sequence[Mapping[str, str]],
        context: Mapping[str, object],
        tools: Sequence[Mapping[str, object]],
        results: Sequence[ToolResult],
    ) -> ToolCall | AssistantText: ...


ToolHandler = Callable[
    [BaseModel, Mapping[str, object]], Awaitable[Mapping[str, object]]
]


class ToolDispatcher:
    """Closed registry with a bounded provider-controlled execution loop."""

    def __init__(
        self, handlers: Mapping[str, ToolHandler], *, max_turns: int = MAX_TOOL_TURNS
    ) -> None:
        expected = {item.name for item in TOOL_REGISTRY}
        supplied = set(handlers)
        if supplied != expected:
            raise ValueError(
                "tool handler registry must cover exactly the frozen tool contract; "
                f"missing={sorted(expected - supplied)!r}, extra={sorted(supplied - expected)!r}"
            )
        if not 1 <= max_turns <= MAX_TOOL_TURNS:
            raise ValueError(f"max_turns must be from 1 to {MAX_TOOL_TURNS}")
        self._handlers = dict(handlers)
        self._max_turns = max_turns

    @property
    def tools(self) -> tuple[Mapping[str, object], ...]:
        from copilot.tools.schemas import TOOL_SCHEMAS

        return tuple(MappingProxyType(dict(item)) for item in TOOL_SCHEMAS)

    async def run(
        self,
        provider: ToolCallingProvider,
        *,
        question: str,
        history: Sequence[Mapping[str, str]],
        context: Mapping[str, object],
    ) -> tuple[tuple[ToolResult, ...], str]:
        frozen_context = MappingProxyType(dict(context))
        results: list[ToolResult] = []
        for _ in range(self._max_turns):
            action = await provider.next_action(
                question=question,
                history=tuple(MappingProxyType(dict(item)) for item in history),
                context=frozen_context,
                tools=self.tools,
                results=tuple(results),
            )
            if isinstance(action, AssistantText):
                if not action.text:
                    raise ValueError("provider returned empty assistant text")
                return tuple(results), action.text
            result = await self._execute(action, frozen_context)
            results.append(result)
        raise ValueError("provider exceeded the bounded tool-call loop")

    async def _execute(
        self, call: ToolCall, context: Mapping[str, object]
    ) -> ToolResult:
        try:
            payload = validate_tool_input(call.name, dict(call.arguments))
        except (ValidationError, ValueError) as exc:
            raise ValueError(f"invalid arguments for tool {call.name!r}") from exc
        result = await self._handlers[call.name](payload, context)
        if not isinstance(result, Mapping):
            raise TypeError(f"tool {call.name!r} returned a non-mapping result")
        definition = next(item for item in TOOL_REGISTRY if item.name == call.name)
        try:
            validated = _validate_tool_result(definition.output_model, result)
        except ValidationError as exc:
            raise TypeError(f"tool {call.name!r} returned an invalid result") from exc
        output = validated.model_dump(mode="json")
        if (
            call.name in {"scenario_edit", "cascade"}
            and output["status"] == "available"
        ):
            output["scene_action"] = _scene_action(call, output)
        return ToolResult(
            call.call_id,
            call.name,
            MappingProxyType(dict(call.arguments)),
            MappingProxyType(output),
        )


def _validate_tool_result(
    models: tuple[type[BaseModel], type[BaseModel]], result: Mapping[str, object]
) -> BaseModel:
    """Accept only one declared Pydantic output shape from a registered handler."""

    errors: list[ValidationError] = []
    for model in models:
        try:
            return model.model_validate(result)
        except ValidationError as exc:
            errors.append(exc)
    raise errors[-1]


def _scene_action(call: ToolCall, output: Mapping[str, object]) -> dict[str, object]:
    """Attach the one additive browser action shape to its observed tool call."""

    data = output.get("data")
    values = data if isinstance(data, Mapping) else {}
    key = "edit_hash" if call.name == "scenario_edit" else "run_id"
    value = values.get(key)
    action: dict[str, object] = {
        "action_id": f"{call.name}:{call.call_id}",
        "kind": call.name,
        "tool_call_id": call.call_id,
        "reversible": True,
        "status": "available",
    }
    if isinstance(value, str) and value:
        action["edit_hash" if call.name == "scenario_edit" else "cascade_id"] = value
    return action


def interactive_tool_handlers(service: object) -> dict[str, ToolHandler]:
    """Return all 13 handlers with live calls for the four interactive tools.

    The historical nine-tool implementations are deployment-owned. Until a
    deployment supplies them, they answer typed `unsupported_request` results
    rather than guessing from the question or making a network call.
    """

    async def unavailable(
        _: BaseModel, __: Mapping[str, object]
    ) -> Mapping[str, object]:
        return unavailable_output(
            "unsupported_request",
            "This deployment has not registered that tool implementation.",
        ).model_dump(mode="json")

    handlers = {definition.name: unavailable for definition in TOOL_REGISTRY}

    async def scenario_edit(
        payload: BaseModel, _: Mapping[str, object]
    ) -> Mapping[str, object]:
        from copilot.interactive_routes import EditOperation, ScenarioEditRequest

        value = ScenarioEditInput.model_validate(payload)
        response = await service.scenario_edit(  # type: ignore[attr-defined]
            ScenarioEditRequest(
                base_scenario_id=value.base_scenario_id,
                ops=[EditOperation(**item.model_dump()) for item in value.ops],
                hour=value.hour,
                seed=value.seed,
            )
        )
        return _interactive_output(response)

    async def cascade(
        payload: BaseModel, _: Mapping[str, object]
    ) -> Mapping[str, object]:
        from copilot.interactive_routes import CascadeRequest

        value = InteractiveCascadeInput.model_validate(payload)
        response = await service.cascade(  # type: ignore[attr-defined]
            CascadeRequest(**value.model_dump())
        )
        return _interactive_output(response)

    async def balance(
        payload: BaseModel, _: Mapping[str, object]
    ) -> Mapping[str, object]:
        value = BalanceInput.model_validate(payload)
        response = await service.balance(  # type: ignore[attr-defined]
            **value.model_dump()
        )
        return _interactive_output(response)

    async def redundancy(
        payload: BaseModel, _: Mapping[str, object]
    ) -> Mapping[str, object]:
        value = RedundancyInput.model_validate(payload)
        response = await service.redundancy(  # type: ignore[attr-defined]
            **value.model_dump()
        )
        return _interactive_output(response)

    handlers.update(
        {
            "scenario_edit": scenario_edit,
            "cascade": cascade,
            "balance": balance,
            "redundancy": redundancy,
        }
    )
    return handlers


def _interactive_output(response: object) -> dict[str, object]:
    """Add explicit simulated provenance before the registry validates it."""

    if not isinstance(response, Mapping):
        raise TypeError("interactive service returned a non-mapping response")
    value = dict(response)
    value.update(
        {
            "status": "available",
            "provenance": [
                ArtifactRef(
                    artifact_id="tx:synthetic:interactive-service",
                    artifact_version="current",
                    source_kind="simulated",
                    source_ref="copilot.interactive_routes.InteractiveService",
                ).model_dump(mode="json")
            ],
        }
    )
    # The service envelope uses arbitrary JSON only inside its `data` member;
    # validate that concrete envelope before returning a handler mapping.
    return InteractiveData.model_validate(value).model_dump(mode="json")
