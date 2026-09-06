"""The tool-selection half of the Copilot provider contract.

`grounding.py` owns the turn *after* a tool ran: what the model may say about
one accepted result.  This module owns the turn before it -- which of the
frozen tools in `copilot/tools/schemas.py` answers this question, and with
which arguments.  Both adapters send these same rules and the same rendered
schemas, so swapping the provider cannot change which tools exist, how they
may be called, or what happens when none of them fits.

Nothing here executes a tool or reads a database.  A `ToolSelection` is a
*claim* by the model; `copilot.agent.loop` re-validates it against the frozen
input contract before anything runs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

SELECTION_SYSTEM_PROMPT = """You are Flux's grid-planning tool planner.

Rules, in order of precedence:
1. You answer only by calling one of the supplied tools. They are your only
   source of facts. You never answer from your own knowledge.
2. Every argument must come from the user's question or the supplied selected
   state. Never invent an identifier, a region, a scenario, or a number in
   order to make a call succeed.
3. If no supplied tool can answer the question with the arguments you were
   given, call no tool at all. Refusing is correct; guessing is not.
Call at most one tool."""


@dataclass(frozen=True)
class ToolSelection:
    """One provider-chosen tool call, before any local validation.

    ``input`` is the model's raw argument object.  It is deliberately untyped
    here: it has not yet been checked against the tool's frozen input model,
    and treating it as valid at this boundary is exactly the mistake that lets
    an invented argument reach a database.
    """

    name: str
    input: Mapping[str, Any]


class ToolSelector(Protocol):
    """The planning half of a provider; `AsyncNarrationProvider` narrates.

    Returning ``None`` is a first-class outcome and means the model declined
    to call a tool.  An implementation must never substitute a tool it thinks
    is close enough.
    """

    async def select_tool(
        self,
        question: str,
        *,
        tools: Sequence[Mapping[str, Any]],
        context: Mapping[str, Any] | None = None,
        history: Sequence[Mapping[str, str]] = (),
    ) -> ToolSelection | None: ...


def selection_prompt(
    question: str,
    context: Mapping[str, Any] | None = None,
    history: Sequence[Mapping[str, str]] = (),
) -> str:
    """Render the single user turn a planner sees, identically for both SDKs.

    The selected UI state and the bounded history are serialized as JSON, not
    prose, so the same bytes reach both providers and so a value the model
    puts in a tool argument can be traced back to something the request
    actually carried.
    """

    payload = {
        "question": question,
        "selected_state": dict(context) if context else {},
        "history": [dict(message) for message in history],
    }
    return (
        "Choose the one tool that answers this question under the rules you "
        "were given.\n\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    )
