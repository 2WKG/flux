"""The declared label vocabularies must equal what the producer actually emits.

Before this file the vocabularies were *exported* but never *checked*: appending
a phantom role to ``NODE_ROLES`` left the whole annotation suite green and
``gate/contract-drift`` clean, because that gate regenerates
``web/src/contracts/`` **from** ``pipelines/labels.py`` and so only proves the
export was re-run, never that the list describes reality.  The closure
assertions below are equalities, not subset checks, so a declared value nothing
emits is as red as an emitted value nothing declares.
"""

from __future__ import annotations

import importlib
import typing

import duckdb

from pipelines.labels import (
    FIELD_PROVENANCE_TOKENS,
    NODE_ROLES,
    SYNTHETIC_TOPOLOGY_LABEL,
    TOPOLOGY_LABEL_IMPORTERS,
    SyntheticTopologyLabel,
)
from pipelines.node_annotations import read_node_annotations
from pipelines.tests.test_node_annotations import _fixture, _schema


def _literal_strings(annotation: object) -> set[str]:
    """The string values a possibly-Optional ``Literal`` annotation permits.

    ``get_type_hints`` hands back ``Optional[Literal["x"]]``, whose ``get_args``
    is ``(Literal["x"], NoneType)`` -- the literal is one level down, so it has
    to be unwrapped rather than compared directly.
    """
    values: set[str] = set()
    for arg in typing.get_args(annotation):
        if typing.get_origin(arg) is typing.Literal:
            values |= set(typing.get_args(arg))
    return values


def _annotations():
    con = duckdb.connect(":memory:")
    _schema(con)
    _fixture(con)
    return read_node_annotations(con)


def test_the_declared_role_vocabulary_is_exactly_what_the_producer_emits() -> None:
    """RED on a phantom role: the fixture covers all four roles by design."""
    emitted = {node.role for node in _annotations()}

    assert emitted == set(NODE_ROLES), (
        "NODE_ROLES and the roles read_node_annotations emits have diverged; "
        f"declared-but-unemitted={sorted(set(NODE_ROLES) - emitted)}, "
        f"emitted-but-undeclared={sorted(emitted - set(NODE_ROLES))}"
    )


def test_the_declared_provenance_vocabulary_is_exactly_what_the_producer_emits() -> (
    None
):
    """RED on a bogus token, and on quietly dropping a real one.

    ``source_backed`` is the one declared token this producer must never emit:
    every value it serves is either synthetic, derived from synthetic
    coordinates, absent, or a broken reference.  That exclusion is the point of
    2WKG-427, so it is asserted rather than subtracted silently.
    """
    annotations = _annotations()
    emitted = {
        token for node in annotations for token in node.field_provenance.values()
    }

    assert "source_backed" not in emitted
    assert emitted == set(FIELD_PROVENANCE_TOKENS) - {"source_backed"}, (
        "FIELD_PROVENANCE_TOKENS and the tokens read_node_annotations emits have "
        f"diverged; declared-but-unemitted="
        f"{sorted(set(FIELD_PROVENANCE_TOKENS) - {'source_backed'} - emitted)}, "
        f"emitted-but-undeclared={sorted(emitted - set(FIELD_PROVENANCE_TOKENS))}"
    )


def test_the_literal_alias_and_the_constant_are_the_same_string() -> None:
    """A relabel that edits one spelling and not the other is RED."""
    assert typing.get_args(SyntheticTopologyLabel) == (SYNTHETIC_TOPOLOGY_LABEL,)


def test_every_declared_importer_derives_the_topology_label() -> None:
    """RED when a listed surface goes back to spelling the label itself.

    Checked two ways, because a module can drift in two places: the runtime
    constant it re-exports, and the ``Literal`` it annotates with.
    """
    for module_name in TOPOLOGY_LABEL_IMPORTERS:
        module = importlib.import_module(module_name)
        assert module.SYNTHETIC_TOPOLOGY_LABEL == SYNTHETIC_TOPOLOGY_LABEL, (
            f"{module_name} no longer derives the topology label from pipelines.labels"
        )

    scenarios = importlib.import_module("copilot.routes.scenarios")

    # The response model's declared field (was scenarios.py:67).
    field = typing.get_type_hints(scenarios.ScenarioProvenance)["topology"]
    assert _literal_strings(field) == {SYNTHETIC_TOPOLOGY_LABEL}, (
        "ScenarioProvenance.topology pins a topology string that is not "
        f"SYNTHETIC_TOPOLOGY_LABEL: {field!r}"
    )
    assert type(None) in typing.get_args(field), "topology must stay optional"

    # The deriver's return annotation (was scenarios.py:115).
    returned = typing.get_type_hints(scenarios._derive_labels)["return"]
    topology_position = typing.get_args(returned)[1]
    assert _literal_strings(topology_position) == {SYNTHETIC_TOPOLOGY_LABEL}, (
        "_derive_labels declares a topology string that is not "
        f"SYNTHETIC_TOPOLOGY_LABEL: {topology_position!r}"
    )

    # ...and what it actually returns agrees with what it declares.
    _, topology = scenarios._derive_labels("ACTIVSg2000 case", "activsg2000")
    assert topology == SYNTHETIC_TOPOLOGY_LABEL


def test_the_critical_facility_id_type_is_pinned_to_what_the_client_expects() -> None:
    """The facility ``id`` type is a cross-repo contract, so it is pinned here.

    2WKG-427's review found this unpinned and read it as a break: it recorded
    that #285 declared ``id: string`` and guarded ``typeof item.id ===
    "string"``, so an integer would fail the guard and turn the whole Texas node
    layer into ``request_failed``.  That was true of the head it read.

    It is **not** true of #285 today (head ``db40bd77``, 2026-09-06T17:44Z),
    which now declares ``id: number``, guards ``if (!number(id)) return null``,
    and feeds ``{ id: 7, ... }`` from its own fixtures -- and additionally
    asserts that the older ``{ cl_id: 7 }`` shape is refused.  Server and client
    therefore **agree on a JSON number right now**, and stringifying the column
    would create exactly the breakage the review wanted to prevent.

    So this test pins the agreement rather than changing it.  If either side
    should move to a string, both must move in the same change, and this
    assertion is the one that makes the other side's silence impossible.
    """
    facilities = [
        facility for node in _annotations() for facility in node.critical_loads
    ]

    assert facilities, "the fixture must attach at least one critical facility"
    for facility in facilities:
        assert isinstance(facility["id"], int) and not isinstance(
            facility["id"], bool
        ), (
            "critical-load facility id must stay an integer while "
            "web/src/texas-nodes/adapter.ts guards on `number(id)`; got "
            f"{type(facility['id']).__name__} ({facility['id']!r})"
        )
    # ``ORDER BY c.cl_id`` is numeric, so the ids arrive in numeric order.
    assert [facility["id"] for facility in facilities] == [2, 9]
