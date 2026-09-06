# Commercial buildings

`commercial_buildings` is neutral reusable office, storefront, and everyday-business massing. It is not a Minnesota placement or an identified customer/load.

The scene is authored in the contract frame (metres, Y up, `-Z` forward, pivot on
the ground at the footprint centre) as the `SCENE_NODES` and `CONNECTORS` tables
in `commercial_buildings.blender.py`. `contract_to_blender()` converts each
coordinate exactly once into Blender's Z-up world, and the glTF export runs with
`export_yup=True`, which converts it back; the two compose to the identity, so the
exported GLB carries the coordinates the meta declares.

Inspect the geometry without Blender — this prints the derived bounds, per-node
boxes, and connector position that `scripts/validate_commercial_buildings_kit.py`
checks the meta against:

```sh
python commercial_buildings.blender.py -- --dry-run
```

Build the handoff artifacts with Blender:

```sh
blender --background --python commercial_buildings.blender.py -- /tmp/flux-assets
```

Blender is not part of this repository's toolchain, so the build/preview command
above is not exercised by the test suite or CI: the checks that do run are the
`--dry-run` manifest, the kit validator, and `tests/test_commercial_buildings_kit.py`.

The handoff contains the GLB, 512px preview, and metadata. Do not commit generated binaries: 2WKG-374 owns storage, import, placement, and accepted-artifact binding. `.gitignore` and `scripts/validate_asset_archetypes.py` both cover this directory, so a stray binary is ignored and reported rather than committed.

`triangles_lod0/1/2` in the meta are the shared catalog's budgets for this
archetype, not measurements: this source builds a single LOD0 mesh, and no
lod1/lod2 geometry is produced here. Decimation is 2WKG-374's pipeline step.
