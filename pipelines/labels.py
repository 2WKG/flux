"""Truth labels shared by the pipelines and the routes that serve them.

The synthetic-topology label had several independent definitions.  The
surfaces listed in ``TOPOLOGY_LABEL_IMPORTERS`` below now read this module, and
``pipelines/tests/test_label_vocabulary.py`` fails if any of them stops agreeing
with ``SYNTHETIC_TOPOLOGY_LABEL``, so relabelling the model is a single edit
*for those surfaces*.  It is **not** yet true of the whole repository:
``copilot/routes/model_geometry.py``, ``pipelines/graph_export.py`` and
``scripts/`` still spell the string themselves, and the browser copy in
``web/src/scene/minnesota-adapter.ts`` stays separate because it is the client's
own frozen contract.
"""

from __future__ import annotations

from typing import Final, Literal

#: The only topology string any Flux route may emit for the ACTIVSg2000 model.
#: ``SyntheticTopologyLabel`` is the type spelling of the same value; annotating
#: the constant with it makes the two provably equal to a type checker, and
#: ``test_the_literal_alias_and_the_constant_are_the_same_string`` proves it at
#: runtime, so a relabel cannot leave the type behind.
SyntheticTopologyLabel = Literal["synthetic (ACTIVSg2000)"]
SYNTHETIC_TOPOLOGY_LABEL: Final[SyntheticTopologyLabel] = "synthetic (ACTIVSg2000)"

#: The modules that must derive the topology label from this one, checked by
#: ``pipelines/tests/test_label_vocabulary.py``.  Adding a surface here without
#: making it import the constant turns that test red.
TOPOLOGY_LABEL_IMPORTERS: Final = (
    "copilot.routes.scenarios",
    "twin.contracts",
)

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
