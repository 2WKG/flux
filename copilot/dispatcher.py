"""Provider-agnostic, bounded execution of the Copilot tool contract.

Providers choose a declared function; this module never infers a tool from a
question.  It validates every provider argument before invoking a registered
handler and gives the provider only immutable context plus prior tool results.
"""

from __future__ import annotations

import re
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

#: Words that name Minnesota in a question.  The interactive tools are backed
#: only by the Texas synthetic ACTIVSg2000 topology, so a Minnesota question
#: must be refused rather than answered with Texas numbers wearing a Minnesota
#: label.  Ported from the #254 Minnesota-intent guard.
_MINNESOTA_WORDS = ("minnesota", "mn", "xcel", "miso")


class ToolLoopOverrun(RuntimeError):
    """The provider kept calling tools past the bounded loop.

    Distinct from an invalid tool argument: the caller must be able to tell an
    unbounded provider apart from a malformed call, so `/ask` maps this to its
    own error message rather than the shared invalid-tool-action text.
    """


def mentions_minnesota(text: str) -> bool:
    """Whole-word match, so "mnemonic" and "amiso" are not Minnesota."""

    lowered = text.lower()
    return any(
        re.search(rf"\b{re.escape(word)}\b", lowered) for word in _MINNESOTA_WORDS
    )


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
        # The question travels with the context so a handler can refuse a
        # request whose geography its data cannot answer (Minnesota).  It is
        # never used to *infer* a tool: the provider still chooses.
        frozen_context = MappingProxyType({**dict(context), "question": question})
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
        raise ToolLoopOverrun(
            f"provider exceeded the bounded tool-call loop of {self._max_turns} turns"
        )

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
    key = "edit_hash" if call.name == "scenario_edit" else "cascade_id"
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


_TEXAS_ONLY_REFUSAL = (
    "The interactive simulation tools are backed only by the Texas synthetic "
    "ACTIVSg2000 topology; there is no Minnesota topology to run them against."
)


def _refuse_minnesota(context: Mapping[str, object]) -> Mapping[str, object] | None:
    """Refuse a Minnesota question rather than answering it with Texas data."""

    question = context.get("question")
    if isinstance(question, str) and mentions_minnesota(question):
        return unavailable_output(
            "unsupported_request", _TEXAS_ONLY_REFUSAL
        ).model_dump(mode="json")
    return None


async def _guarded(
    call: Callable[[], Awaitable[Mapping[str, object]]],
) -> Mapping[str, object]:
    """Turn the interactive service's typed refusals into tool results.

    Without this, a missing simulation core escapes to `copilot/routes/ask.py`'s
    blanket handler and `/ask` reports "The answer provider is unavailable" --
    blaming a provider that was never called.  The named refusal belongs in the
    tool result, exactly as the HTTP half returns it.
    """

    from copilot.api import InvalidInputError, NotFoundError, UnavailableError

    try:
        return await call()
    except UnavailableError as exc:
        reason = "synthetic_core_unavailable"
        details = getattr(exc, "details", None)
        if isinstance(details, Mapping):
            reason = str(details.get("reason", reason))
        return unavailable_output(
            "artifact_unavailable",
            f"The synthetic interactive simulation core is unavailable ({reason}).",
        ).model_dump(mode="json")
    except NotFoundError:
        return unavailable_output(
            "artifact_unavailable",
            "The requested interactive edit is not available.",
        ).model_dump(mode="json")
    except InvalidInputError as exc:
        raise ValueError(f"invalid interactive request: {exc}") from exc


def interactive_tool_handlers(
    service: object, *, historical_handlers: Mapping[str, ToolHandler] | None = None
) -> dict[str, ToolHandler]:
    """Compose the nine persisted and four static-interactive tool bindings.

    The production app supplies the concrete persisted handlers.  The optional
    fallback keeps this helper usable in narrow interactive-only harnesses,
    where an unregistered historical capability still reports typed
    unavailability rather than inventing a result.
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
        payload: BaseModel, context: Mapping[str, object]
    ) -> Mapping[str, object]:
        from copilot.interactive_routes import EditOperation, ScenarioEditRequest

        refusal = _refuse_minnesota(context)
        if refusal is not None:
            return refusal
        value = ScenarioEditInput.model_validate(payload)
        response = await _guarded(
            lambda: service.scenario_edit(  # type: ignore[attr-defined]
                ScenarioEditRequest(
                    base_scenario_id=value.base_scenario_id,
                    ops=[EditOperation(**item.model_dump()) for item in value.ops],
                    hour=value.hour,
                    seed=value.seed,
                )
            )
        )
        if response.get("status") == "unavailable":
            return response
        return _interactive_output(response)

    async def cascade(
        payload: BaseModel, context: Mapping[str, object]
    ) -> Mapping[str, object]:
        from copilot.interactive_routes import CascadeRequest

        refusal = _refuse_minnesota(context)
        if refusal is not None:
            return refusal
        value = InteractiveCascadeInput.model_validate(payload)
        response = await _guarded(
            lambda: service.cascade(  # type: ignore[attr-defined]
                CascadeRequest(**value.model_dump())
            )
        )
        if response.get("status") == "unavailable":
            return response
        return _interactive_output(response)

    async def balance(
        payload: BaseModel, context: Mapping[str, object]
    ) -> Mapping[str, object]:
        refusal = _refuse_minnesota(context)
        if refusal is not None:
            return refusal
        value = BalanceInput.model_validate(payload)
        response = await _guarded(
            lambda: service.balance(**value.model_dump())  # type: ignore[attr-defined]
        )
        if response.get("status") == "unavailable":
            return response
        return _interactive_output(response)

    async def redundancy(
        payload: BaseModel, context: Mapping[str, object]
    ) -> Mapping[str, object]:
        refusal = _refuse_minnesota(context)
        if refusal is not None:
            return refusal
        value = RedundancyInput.model_validate(payload)
        response = await _guarded(
            lambda: service.redundancy(**value.model_dump())  # type: ignore[attr-defined]
        )
        if response.get("status") == "unavailable":
            return response
        return _interactive_output(response)

    handlers.update(
        {
            "scenario_edit": scenario_edit,
            "cascade": cascade,
            "balance": balance,
            "redundancy": redundancy,
        }
    )
    if historical_handlers is not None:
        interactive_names = {"scenario_edit", "cascade", "balance", "redundancy"}
        expected_historical = {item.name for item in TOOL_REGISTRY} - interactive_names
        supplied = set(historical_handlers)
        if supplied != expected_historical:
            raise ValueError(
                "historical handler registry must cover exactly the nine persisted "
                f"tools; missing={sorted(expected_historical - supplied)!r}, "
                f"extra={sorted(supplied - expected_historical)!r}"
            )
        handlers.update(historical_handlers)
    return handlers


def _interactive_output(response: object) -> dict[str, object]:
    """Add explicit simulated provenance before the registry validates it."""

    if not isinstance(response, Mapping):
        raise TypeError("interactive service returned a non-mapping response")
    from copilot.interactive_routes import INTERACTIVE_LABELS

    flat = dict(response)
    # The HTTP body is unwrapped (envelope.py); the *tool* contract
    # (`InteractiveData`) nests the payload under `data`, so re-nest here
    # rather than making the HTTP surface carry a bespoke success wrapper.
    value = {name: flat.pop(name) for name in INTERACTIVE_LABELS if name in flat}
    value["data"] = flat
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
