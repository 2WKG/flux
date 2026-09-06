"""Truth labels shared by the pipelines and the routes that serve them.

The synthetic-topology label had four independent definitions (two Python
routes, one TypeScript adapter, one spec table).  The Python copies now read
this module so a single edit moves every server-side surface at once; the
browser copy in ``web/src/scene/minnesota-adapter.ts`` stays separate because it
is the client's own frozen contract.
"""

from __future__ import annotations

from typing import Final

#: The only topology string any Flux route may emit for the ACTIVSg2000 model.
SYNTHETIC_TOPOLOGY_LABEL: Final = "synthetic (ACTIVSg2000)"

#: The node-role vocabulary produced by ``pipelines.node_annotations``.
#: Declared in ``docs/specs/05-copilot.md`` and exported for the browser to
#: ``web/src/contracts/node-annotations.json`` by
#: ``scripts/ci/export_tool_contracts.py``; nothing may fork this list.
NODE_ROLES: Final = ("both", "consumer", "producer", "transmission")

#: The per-field truth tokens ``NodeAnnotation.field_provenance`` may carry.
#: ``synthetic`` covers a value the synthetic model produced *and* a value whose
#: binding to this bus was derived from synthetic coordinates; ``source_backed``
#: is reserved for a value that is source-backed all the way to this bus.
FIELD_PROVENANCE_TOKENS: Final = (
    "source_backed",
    "synthetic",
    "derived",
    "unavailable",
    "broken_reference",
)

#: Why a critical-load facility carries no spatial-join receipt.
BINDING_RECEIPT_ABSENT: Final = "receipt_table_absent"
BINDING_RECEIPT_MISSING: Final = "receipt_missing"
