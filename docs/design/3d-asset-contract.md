# Shared 3D visual and model-production contract

**Contract:** `flux:3d-asset-archetypes:v1`
**Machine-readable catalog:** [`data/3d/asset-archetypes-v1.json`](../../data/3d/asset-archetypes-v1.json)
**Checked by:** `scripts/validate_asset_archetypes.py`, `tests/test_asset_archetypes.py`

**Status:** Gate 0 production contract for **2WKG-365** (Minnesota) and its Texas
twin **2WKG-311**. This is a specification for producing models. It is not a
model, a placement, an approval of Minnesota coverage, or a claim that any
depicted facility exists.

**Authoritative inputs.** The [Minnesota demo contract](../specs/10-minnesota-demo.md)
governs geography, model eligibility, and claims. The
[shared overview](../specs/00-overview.md) governs the browser/server boundary:
the browser renders server artifacts and never invents a value or a label. The
[narrative and information architecture](minnesota-demo-narrative-ia.md) owns
the status-label vocabulary this contract binds materials to.

## The one rule everything else follows from

**An archetype is a shape. A placement is an identity. They never merge.**

A model in this catalog carries no place, owner, operator, capacity, or measured
value. Those arrive with a server artifact at placement time. This keeps the
same eighteen models reusable across the Texas and Minnesota scenes without ever
letting a Texas identity, or the ACTIVSg2000 synthetic Texas case, leak into a
Minnesota claim.

## Runtime and import invariants

| Decision | Value | Why this one |
| --- | --- | --- |
| Container | `.glb` (glTF 2.0 binary) | One file per archetype, no sidecar fetches, loadable by the deck.gl/loaders.gl stack already in the web bundle (`@deck.gl/mesh-layers`, `@loaders.gl/gltf`), and checksum-pinnable as a single artifact. three.js is **not** a current dependency; adopting it would be a new one and a separate decision |
| Length unit | metre, unit scale `1.0` | A mixed-unit import is the most common cause of a scene that silently renders at 1/100 scale |
| Up axis | `Y` | glTF's own convention; converting at load time is a per-asset correction waiting to be forgotten |
| Forward axis | `-Z` | Placement applies yaw; a model must not bake a site rotation |
| Handedness | right | Matches glTF |
| Pivot | `ground_center` — origin on the ground plane, centred on the footprint | A floating or bbox-centred pivot cannot be dropped on terrain without per-asset fixes |
| Textures | KTX2/Basis preferred, PNG acceptable, ≤ 2048 px | Bounded VRAM at statewide zoom |

`validate_asset_archetypes.py` rejects a catalog that drifts on unit, axis, or
pivot, so these are enforced rather than merely written down.

## Footprints and connectors

**Footprint** is an axis-aligned rectangle in metres: `length` along `-Z`,
`width` along `X`, at author orientation. It is the selection and collision
proxy for picking (2WKG-372 Minnesota / 2WKG-318 Texas). Rendered geometry must
fit inside it within 5%. It is nominal author geometry — **not a surveyed
parcel, lease, or property boundary**.

**Connectors** are named empty nodes marking where a line or feeder attaches,
named `CONN_<role>_<index>`:

| Role | Meaning |
| --- | --- |
| `HV_IN` / `HV_OUT` | High-voltage attachment, incoming / outgoing side |
| `MV_FEED` | Medium-voltage feeder attachment |
| `NONE` | Archetype exposes no electrical attachment point |

A connector is **a geometric attachment point only**. It asserts no
connectivity, rating, phase, or energisation. Drawing a line between two
connectors is scene furniture; it is not a circuit, and it never implies a
Minnesota network. Topology scenes stay disabled until the
`10-minnesota-demo.md` network decision gate accepts a solver-complete source.

## Status materials

Every archetype ships **neutral** and exposes one shared material slot,
`MAT_STATUS`, which the runtime tints from the label carried by the placement's
artifact. A model must never bake a status colour.

The bound labels are exactly those the server asserts:
`source_supported`, `source_screened`, `hypothetical`, `synthetic`,
`unavailable`, `request_failed`.

There is deliberately **no decorative or "illustrative" state**. The
narrative-IA contract removed that label because nothing on `master` produces it,
and a label the browser invents would breach the `00-overview.md` boundary. The
validator fails a catalog that adds one back.

Colour never carries the claim alone: every state pairs with a readable text
label and a glyph or pattern, meeting text-contrast requirements.

## Budgets

| Budget | Value |
| --- | --- |
| Triangles, LOD0, per archetype | 40 000 |
| File size, per archetype | 3 MiB |
| Texture | ≤ 2048 px |
| Scene ceiling (shared) | 4 000 000 triangles |
| LOD1 | ≤ 40% of LOD0 |
| LOD2 | ≤ 12% of LOD0, still recognisable in silhouette at statewide zoom |

The LOD chain is validated, so an "LOD" that does not actually reduce is a test
failure rather than a runtime discovery. Streaming, culling, and instancing
belong to 2WKG-371; the scene ceiling is stated here only so an archetype author
knows the budget they share.

## Deliverables per archetype

- `<archetype_id>.glb`
- `<archetype_id>.preview.png` (512 px)
- `<archetype_id>.meta.json` — `archetype_id`, `contract_id`, triangle counts per
  LOD, `footprint_m`, `connectors`, `author`, `license`, `source_of_shape`

Every model states a licence permitting redistribution here. A model derived
from a third-party asset names that asset and its licence in `source_of_shape`.

**Binaries are not committed to Git.** This contract governs their shape; the
asset pipeline (2WKG-374 Minnesota / 2WKG-320 Texas) produces, stores, and
verifies them. The boundary is enforced two ways rather than described, on both
scanned trees: `data/3d/**` and `web/public/**` `.glb`/`.gltf` are git-ignored,
and `tests/test_asset_archetypes.py` asserts `git ls-files` tracks no `.glb` or
`.gltf` at all — so committing one (which takes a deliberate `git add -f`) turns
the suite red. Presence is reported separately and without judgement:
`validate_asset_archetypes.py` *derives* `modelFilesPresent` by walking `data/`
and `web/` for `.glb`/`.gltf` and lists every hit in the report's `modelFiles`,
so a model the pipeline writes locally is visible in the report while a
developer's suite stays green, exactly as it does in CI.

## The eighteen archetypes

Each is claimed by exactly one Texas and one Minnesota work item; the validator
rejects a catalog where a work item is claimed twice or an archetype is missing.

| Archetype | Category | Connectors | Texas | Minnesota |
| --- | --- | --- | --- | --- |
| Transmission towers and line segments | network | HV_IN, HV_OUT | 2WKG-322 | 2WKG-376 |
| Substation and transformer yard | network | HV_IN, HV_OUT, MV_FEED | 2WKG-323 | 2WKG-377 |
| Military base | critical_load | MV_FEED | 2WKG-324 | 2WKG-378 |
| Hospital | critical_load | MV_FEED | 2WKG-325 | 2WKG-379 |
| Water treatment plant | critical_load | MV_FEED | 2WKG-326 | 2WKG-380 |
| Coal plant and retiring plant site | generation | HV_OUT | 2WKG-327 | 2WKG-381 |
| New nuclear and SMR module | generation | HV_OUT | 2WKG-328 | 2WKG-382 |
| Data center campus | load | MV_FEED | 2WKG-329 | 2WKG-383 |
| Residential neighborhood | load | MV_FEED | 2WKG-330 | 2WKG-384 |
| Commercial buildings | load | MV_FEED | 2WKG-331 | 2WKG-385 |
| Factory and industrial facility | load | MV_FEED | 2WKG-332 | 2WKG-386 |
| Natural-gas power plant | generation | HV_OUT | 2WKG-333 | 2WKG-387 |
| Wind turbines | generation | MV_FEED | 2WKG-334 | 2WKG-388 |
| Solar arrays | generation | MV_FEED | 2WKG-335 | 2WKG-389 |
| Battery storage | storage | MV_FEED | 2WKG-336 | 2WKG-390 |
| Warehouse and logistics center | load | MV_FEED | 2WKG-337 | 2WKG-391 |
| EV charging station | load | MV_FEED | 2WKG-338 | 2WKG-392 |
| School and emergency-services building | critical_load | MV_FEED | 2WKG-339 | 2WKG-393 |

The catalog carries a per-archetype `limit` stating what that model does **not**
assert — a wind turbine's rotor animation is decorative and is never driven by a
generation value; a battery's container count implies no MWh, duration, or state
of charge, because the demo has no stateful storage model; a data centre's hall
count implies no MW. The validator requires the field to be non-empty.

## Cross-project reuse, and the line it must not cross

Geometry is shared. Identity is not.

- The same `archetype_id` may be instanced in both the Texas and Minnesota
  scenes.
- A Minnesota placement takes its id, coordinates, coverage, provenance, and
  status label from an **accepted Minnesota server artifact**. It never inherits
  a Texas placement's identity, and ACTIVSg2000 — Texas-shaped synthetic
  topology — is never relabelled as Minnesota.
- Until accepted Minnesota coverage exists (2WKG-364 inventory, 2WKG-367
  adapter), an archetype may be shown in a catalogue or preview view but **must
  not be positioned as Minnesota infrastructure**.

## What this contract does not do

It does not model anything, place anything, or approve anything. No `.glb`
exists in this repository yet, and this document does not assert that any of the
eighteen models has been produced. It defines the shape those models must take
so that when they arrive — from either project — they import consistently, pick
by footprint and connector, and respond to one shared status material without
any of them inventing a claim the server never made.

## Verification

```
python scripts/validate_asset_archetypes.py    # exits non-zero on any violation
python -m pytest tests/test_asset_archetypes.py -q
```
