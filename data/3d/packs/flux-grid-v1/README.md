# Flux grid visual pack v1

Eighteen generic infrastructure shapes, each with three measured detail levels,
neutral status material and a distinct 24–32px category pictogram. Hospital
crosses and a nuclear containment/hall/cooling-tower silhouette remain recognizable
at LOD2. Graphite shells, transparency and cyan emissive edges are presentation
styling, never an operational claim.

This is a **namespaced alternative visual pack**, not a replacement for the
existing per-archetype authors' generators under `data/3d/assets/`. It follows
the unchanged [shared model contract](../../../../docs/design/3d-asset-contract.md).
No geography, server response, accepted placement or application scene is added.
The four runtime modules are reusable components; this PR does not mount them in
the current product UI or map synthetic fixture coordinates onto geography.

## Binary download and build-copy

`archive.json` pins the public distribution: **24,713,909 bytes**, SHA-256
`ee032fe57c2cb61495271d6387a24f3acf9abd68e84e3b5dd2546ab90d45b39c`.
Its publication status and download URL are explicit; a null URL means the
binary attachment is still pending, not an available remote download.

The archive contains 54 GLBs, 18 transparent previews, the PNG sprite atlases,
two editable Blender masters, final renders, offline catalogue viewer and
verification evidence. All GLBs and Blender masters match the approved local
handoff byte-for-byte. Public preparation normalized detailed audit-report
paths and removed three superseded receipts; the original local archive is
unchanged. Ordinary author-home metadata remains embedded in the Blender files.

Once downloaded from the stated publication location:

```sh
shasum -a 256 flux-grid-assets-public.zip
# Compare the full digest above before extracting.
unzip flux-grid-assets-public.zip -d /path/to/asset-workspace
node scripts/install_flux_grid_pack.mjs /path/to/asset-workspace/flux-grid-assets
```

Run the installer from this checkout. It verifies every runtime file against
the **reviewed archive inventory**, checks that the manifest is identical,
rejects source/destination symlinks and differing existing files before copying,
then adds only assets to `web/public/assets/flux-grid/`. A repeat is idempotent.
It does not replace source modules, edit package configuration, enable a layer,
or fetch anything. The entire generated runtime directory stays gitignored.

`package.SHA256SUMS` is the inventory of the downloaded **complete package**, not
an assertion that the source-only Git tree contains its binary files. Model
hashes, byte sizes, triangles and runtime sprite hashes are in `manifest.json`.
The attachment is a distribution download, **not a runtime CDN**. Static build
owners must copy the installed asset directory into their output and serve it
at the same-origin `/assets/flux-grid/` path; this PR does not modify the current
build's network boundary or deployment workflow. Cross-origin CORS delivery is
not exercised or required by this same-origin path.

## Runtime wiring after accepted placements exist

`web/src/map/FluxAssetOverlay.tsx` wraps `ScenegraphLayer` and the category
`IconLayer` in an interleaved MapLibre overlay. The host supplies a stable
`placements` array with accepted artifact ID, identity, longitude/latitude,
altitude in metres, heading, readable label and exact server status token.
Missing/failed states produce no fallback geometry. Mounting is intentionally
left to the existing scene/placement owner after its acceptance boundary.

The default zoom bands are symbols below 12, LOD2 at 12–15, LOD1 at 15–17 and
LOD0 at 17+. Category signs persist at LOD2 and do not communicate status.
`MAT_STATUS` alone is recolored in verified in-memory GLB copies; other materials
and geometry bytes remain unchanged. The host inspector must show the supplied
artifact, scope and readable status, in addition to the overlay's text/glyph.

Models use metres, glTF Y-up, -Z-forward and ground-centred origins.
`gltfToMapMatrix` converts once to east/north/up, then applies clockwise heading:
zero faces north, 90° east. Do not add a second axis rotation or infer terrain
height. Connectors are geometric attachment points, never network assertions.

`FluxMapboxOverlay.ts` contains a version-bounded deck 9.3 / MapLibre 6 instance
compatibility facade for the removed private transform property. It uses public
height/elevation APIs, preserves/restores descriptors and does not mutate any
prototype or dependency. Retest and remove it when upstream compatibility lands.
The native MapLibre symbol alternative is `layers/fluxMapLibreSymbols.ts`;
register the secondary sprite as `flux-grid` after the verified build-copy.

## Rebuild and verify

The portable Blender Python source is tracked under `source/`; rendered model
binaries and `.blend` masters are never committed. Rebuild outside the checkout:

```sh
blender --background --factory-startup --python data/3d/packs/flux-grid-v1/source/pipeline/build_pack.py -- --output /path/to/asset-build
uv run --extra dev python data/3d/packs/flux-grid-v1/validation/validate_pack.py --root /path/to/asset-build
uv run --extra dev python -m unittest discover -s data/3d/packs/flux-grid-v1/validation -p 'test_validate_pack.py'
cd web
npm ci
npm run typecheck
npm run build
node --test src/map/flux-grid-assets.test.mjs test/flux-grid-install.test.mjs
```

Non-Blender Python checks use the repository's Python 3.12 environment
(`uv sync --frozen --extra dev`); do not substitute macOS's older system Python.

Measured one-of-each totals: 253,521 LOD0 triangles; 37,330 LOD1; 7,288 LOD2.
All 54 GLBs total 15,170,916 bytes. The full distribution's browser report covers
all 54 exact models in interleaved deck 9.3.11 / MapLibre 6.7.0, heading/pitch,
material isolation and eighteen 24/32px signs. Each model-pixel comparison hides
only ScenegraphLayer, leaving badges and labels present in both frames.
These are software-WebGL compatibility checks, not a hardware FPS benchmark,
terrain acceptance or statewide scene-performance claim. The typed source port
uses ES2020-compatible own-property checks without changing the app's target.

Original models are CC0; symbol provenance and ISC/MIT/CC0 notices are under
`assets/symbols/`. The binary package includes viewer dependency notices.
