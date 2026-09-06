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
`unavailable`, and `request_failed`.

The older word `illustrative` is prose, not a truth label. An analytical
alternative can be `hypothetical` only when a server artifact says so and
retains its scope and limitations. Where required evidence is missing, the
placement is `unavailable`; it must not be made to look supported by a generic
mesh.

The JSON contains exactly one entry for each of the eighteen archetypes. Each
entry names its candidate P0 records (if any) and gives its binding placement
policy. The validator checks that the archetype IDs match the shared catalog,
candidate records exist in the inventory, and every entry has a non-empty
policy.

```sh
uv run --extra dev python scripts/validate_texas_asset_taxonomy.py
uv run --extra dev pytest tests/test_texas_asset_taxonomy.py -q
```

This legacy Texas evidence artifact does not change the Minnesota demo
authority, Minnesota schema, or source-decision gates.
