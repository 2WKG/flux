"""The grounding contract shared by every Copilot provider adapter.

The system prompt and the evidence payload are written once here so that the
two adapters cannot drift into different rules.  An adapter's only job is to
express tool schemas in its provider's shape and to translate its streaming
response into text deltas; it must not add, relax, or restate a rule.
"""

from __future__ import annotations

import json

from copilot.narration import GroundedNarration

SYSTEM_PROMPT = """You are Flux's grid-planning copilot.

Rules, in order of precedence:
1. You narrate and plan. You never compute. Every number in your answer must
   appear verbatim in the tool evidence you were given.
2. Never derive a new quantity from the evidence: no sums, differences,
   ratios, or percentages. Report the numbers separately instead.
3. Every regulatory, legal, or physical claim must be supported by a supplied
   citation. Without one, say the claim is unverified.
4. Say when topology is synthetic if the evidence labels it so.
5. If a tool result is unavailable, say the answer is unavailable and why.
   Never substitute a plausible default for a missing value.
Answer in at most six sentences of plain prose."""


def narration_prompt(narration: GroundedNarration) -> str:
    """Render one accepted tool result as the single user turn for a provider.

    The evidence is serialized as JSON rather than prose so the same bytes
    reach both providers and the post-hoc verifier can match numbers exactly.
    """

    payload = {
        "summary": narration.text,
        "evidence": _jsonable(narration.evidence),
        "citations": [
            {
                "doc": hit.doc,
                "title": hit.title,
                "page": hit.page,
                "chunk_id": hit.chunk_id,
                "excerpt": hit.text,
            }
            for hit in narration.citations
        ],
        "limitations": list(narration.limitations),
    }
    return (
        "Report this tool result to the user under the rules you were given.\n\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    )


def _jsonable(value: object) -> object:
    """Thaw frozen evidence (read-only mappings, tuples) into JSON values."""
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _jsonable(item) for key, item in value.items()}  # type: ignore[union-attr]
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value
