# Texas asset taxonomy and placement policy

This is the machine-checkable companion to the legacy Texas P0 source
inventory. It maps every reusable 3D archetype to candidate source records and
states what a Texas placement may claim. It is not a Texas demo plan, source
download, raw-data receipt, or approval of a real-grid model.

The crosswalk is [`data/sources/texas-asset-taxonomy-v1.json`](../../data/sources/texas-asset-taxonomy-v1.json).
It is tied to the shared geometry contract in
[`data/3d/asset-archetypes-v1.json`](../../data/3d/asset-archetypes-v1.json)
without modifying that contract.

## Evidence boundary

The corresponding source ledger remains
[`texas-p0-inventory.json`](../../data/sources/texas-p0-inventory.json). It
records the source URL, vintage, licence/access, coverage, CRS/units,
destination tables, evidence status, and any tracked receipt. A raw path is a
declared intake location, not proof that the file exists on a developer's
machine.

At this revision, only the ACTIVSg2000 receipt is validated. Its coordinate
contract is EPSG:4326, but its topology and geometry are synthetic and are not
the real ERCOT network. All other candidate public source records are either
`unavailable` because no checked-in receipt and curated artifact exist, or
`excluded` by a documented P0 scope decision. In particular, source geometry,
nearest-bus matching, and a line drawn between asset connectors never establish
a real electrical connection or service relationship.

## Truth-label policy

The crosswalk adopts the labels asserted by the merged shared 3D contract:
`source_supported`, `source_screened`, `hypothetical`, `synthetic`,
`unavailable`, and `request_failed`. The validator does not keep its own copy of
that list. It reads `statusMaterials.allowedLabels` out of
[`data/3d/asset-archetypes-v1.json`](../../data/3d/asset-archetypes-v1.json) at
run time and fails when the crosswalk disagrees with it, or when the contract
declares no labels at all. Rewriting `allowedLabels` in the catalog therefore
turns this validator red rather than leaving it silently green.

The older word `illustrative` is prose, not a truth label. An analytical
alternative can be `hypothetical` only when a server artifact says so and
retains its scope and limitations. Where required evidence is missing, the
placement is `unavailable`; it must not be made to look supported by a generic
mesh.

## Topology provenance

Every entry carries an explicit `topology_source`. Only two values are legal.
An entry that cites the `activsg2000-current` record must declare
`synthetic (ACTIVSg2000)`; every other entry must declare `none`, because the
remaining P0 records are siting, hazard, or aggregate context and assert no
electrical connectivity. The validator enforces that binding in both directions,
so a Texas placement cannot quietly borrow topology it does not have, and the
synthetic case cannot be laundered into looking like measured network data.

The Minnesota-era five-bus preview fixture is **not** a Texas source. It
represents no state, it appears in no record of
[`texas-p0-inventory.json`](../../data/sources/texas-p0-inventory.json), and the
crosswalk's `five_bus_fixture_policy` says so; the validator requires that
statement to be present, and the `topology_source` enum makes naming the fixture
as a Texas topology a validation error.

## What the validator checks

The JSON contains exactly one entry for each of the eighteen archetypes. Each
entry names its candidate P0 records (if any), its `topology_source`, and its
binding placement policy. The validator checks the crosswalk's own identity
(`schema_version` 1, `taxonomy_id` `texas-asset-taxonomy-v1`), that the
canonical labels match the shared contract read from disk, that
`illustrative_wording_policy` still says `illustrative` is not a truth label,
that the five-bus disclaimer is present, that every entry carries exactly the
four expected keys, that the archetype IDs match the shared catalog exactly
once each, that candidate records exist in the inventory, that
`topology_source` agrees with the cited records, and that every entry has a
non-empty policy. `main()` prints a `{"passed": ..., "errors": [...]}` envelope
and exits 1 on any error; `tests/test_texas_asset_taxonomy.py` asserts that exit
code against both the committed files and deliberately violating ones.

```sh
uv run --extra dev python scripts/validate_texas_asset_taxonomy.py
uv run --extra dev pytest tests/test_texas_asset_taxonomy.py -q
```

This legacy Texas evidence artifact does not change the Minnesota demo
authority, Minnesota schema, or source-decision gates.
