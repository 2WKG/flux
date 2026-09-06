# Shared 3D visual and model-production contract

**Contract:** `flux:3d-asset-archetypes:v1`
**Machine-readable catalog:** [`data/3d/asset-archetypes-v1.json`](../../data/3d/asset-archetypes-v1.json)
**Checked by:** `scripts/validate_asset_archetypes.py`, `tests/test_asset_archetypes.py`
(catalog); `scripts/validate_asset_source.py`, `tests/test_asset_sources.py`
(committed source kits)

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

**The LOD1/LOD2 percentages above are a load-bearing *string*, not just prose.** The browser does
not hard-code 40% and 12%: `web/src/performance/archetype-catalog.ts:106-124` parses them out of
the sentence in `data/3d/asset-archetypes-v1.json` → `budgets.lodRule`
(`"lod1 <= 40% of lod0 triangles, lod2 <= 12%. …"`) with a regex, deliberately, so that it can
never fall back to shares the contract does not state — a rule string it cannot read is the named
rejection `invalid_lod_rule`, not a default. Two consequences: rewording that JSON sentence so the
`lodN <= NN%` pattern no longer matches makes the whole catalog rejected at load, and *changing the
numbers inside it silently changes the budget*. Edit the table above and `budgets.lodRule` together.

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

**The published runtime pack is committed to Git.** For each catalog identity,
`web/public/assets/flux-grid/<archetype_id>/` contains exactly
`<archetype_id>.glb`, `<archetype_id>.lod1.glb`, and
`<archetype_id>.lod2.glb`. `tests/test_asset_archetypes.py` derives those 54
allowed paths from the catalog and asserts that `git ls-files` contains exactly
that set. It therefore rejects a missing LOD, an orphaned or renamed runtime
model, and every other tracked `.glb` or `.gltf`, including anything under
`data/3d`. Source-side `data/3d/**` binaries remain git-ignored build outputs.

Presence is also reported from the working tree without judgement:
`validate_asset_archetypes.py` *derives* `modelFilesPresent` by walking `data/`
and `web/` for `.glb`/`.gltf` and lists every hit in the report's `modelFiles`.
That diagnostic inventory includes the committed pack as well as unexpected
local binaries.

### The source-kit tier (what *is* committed)

The three deliverables above are asset-**pipeline outputs** produced from a
source kit. The published Flux grid pack commits the runtime `.glb` variants
under `web/public/assets/flux-grid/`; the source-kit review material remains
under `data/3d/assets/<archetype_id>/`:

- `<archetype_id>.scene.json` — format `flux:3d-archetype-source:v1`: declared
  `bounds_m`, neutral materials, and the primitive nodes (including the
  connector empties) the model is built from. It is the reviewable statement of
  the geometry; the `.glb` is its export.
- `<archetype_id>.preview.svg` — the 512 px preview *source*, carrying
  `<title>`, `<desc>`, and `aria-labelledby` so the neutrality statement is in
  the accessible tree. The required `.preview.png` is its render.
- `<archetype_id>.meta.json` — the metadata deliverable itself, with every
  `deliverables.metaFields` key, plus `source_scene`, `export.preview_source`,
  and `export.pipeline_outputs` naming the `.glb`/`.png` the pipeline will
  produce. A meta file must not name a committed file that does not exist:
  `export.model_file` / `export.preview_file` at the top level are rejected
  precisely because they read as committed paths.

**Consumers.** Today the source kit is consumed by
`scripts/validate_asset_source.py` and `tests/test_asset_sources.py`, which walk
every directory under `data/3d/assets/` and check each kit against the catalog
row named by its **directory** — identity comes from the directory, never from
the metadata's own `archetype_id`. The SVG→PNG render and the scene→GLB export
belong to the asset pipeline (**2WKG-374** Minnesota / **2WKG-320** Texas); the
checked-in runtime pack is its published browser input, while the source kit
remains the reviewable specification of the model.

**Geometry is checked, not merely declared.** `validate_asset_source.py` derives
the axis-aligned bounds from `scene.nodes` and rejects geometry that overruns
the archetype's `footprint_m` beyond the 5% tolerance, that leaves the scene's
own `bounds_m`, or that does not sit on `y = 0` under the `ground_center` pivot.

**"Tier" here always means *delivery tier* (D-6.)** It is a Python-side, on-disk classification of
how an archetype's source is delivered, with three values (`source_kit`, `blender_kit`,
`flat_meta`) and one named refusal (`unknown_asset_tier`), all in
`scripts/validate_asset_source.py:56-60`. It is **unrelated** to the browser's *LOD level*
(`lod0`/`lod1`/`lod2`, `budgets.lodLevels` below, `web/src/performance/archetype-catalog.ts:27`,
`:236`), which also happens to number three and carries its own nine-value rejection vocabulary
(`archetype-catalog.ts:65-74`) that does not include `unknown_asset_tier`. Never call a LOD level a
tier; the browser has no delivery-tier concept and the validator has no LOD concept.

**Three delivery tiers live under `data/3d/assets/` at once, and the validator applies
exactly one of them per entry.** A directory holding `<archetype_id>.scene.json`
is a **source kit** and gets the rules above. A directory holding
`<archetype_id>.blender.py` is a **blender kit**: its geometry is authored in a
Blender build script rather than as scene data, so `validate_asset_source.py`
checks its README/script/meta file set, its catalog identity, its pinned
transform axes and neutral `MAT_STATUS` slot, its connectors, the `bounds_m` the
meta declares (against the same footprint tolerance and `y = 0` pivot rule), and
that no `.glb` or `.preview.png` build output was committed beside it. A bare
`<archetype_id>.meta.json` file directly under the asset root is a **flat meta**
delivery and is checked by `scripts/asset_contract_lib.py`'s
`validate_export_meta`. The tier is read from the entry's own contents, never
from a name list, and an entry that matches none of the three is refused by name
(`unknown_asset_tier`) rather than skipped — a directory nobody validates is
indistinguishable from one that passes.

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

It does not model anything, place anything, or approve anything. The published
runtime pack contains the eighteen catalog archetypes and their LOD variants;
that does not assert that any depicted facility exists. The contract defines the
shape those models take so they import consistently, pick by footprint and
connector, and respond to one shared status material without inventing a server
claim.

## Verification

```
python scripts/validate_asset_archetypes.py    # catalog; exits non-zero on any violation
python scripts/validate_asset_source.py        # committed source kits; same
python -m pytest tests/test_asset_archetypes.py tests/test_asset_sources.py -q
```
