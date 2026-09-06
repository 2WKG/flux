# Hospital

Neutral reusable hospital massing with one geometric `CONN_MV_FEED_0` attachment.
It carries no Minnesota placement identity and must not be read as a claim about
service level, beds, backup generation, or outage impact.

The scene is authored in the contract frame (metres, Y up, `-Z` forward, pivot on
the ground at the footprint centre) as the `SCENE_NODES` and `CONNECTORS` tables
in `hospital.blender.py`. `contract_to_blender()` converts each coordinate exactly
once into Blender's Z-up world, and the glTF export runs with `export_yup=True`,
which converts it back; the two compose to the identity, so the exported GLB
carries the coordinates the meta declares.

Inspect the geometry without Blender — this prints the derived bounds, per-node
boxes, and connector position that `scripts/validate_hospital_kit.py` checks the
meta against:

```sh
python hospital.blender.py -- --dry-run
```

Build the handoff artifacts with Blender:

```sh
blender --background --python hospital.blender.py -- /tmp/flux-assets
```

Blender is not part of this repository's toolchain, so the build/preview command
above is not exercised by the test suite or CI: the checks that do run are the
`--dry-run` manifest, the kit validator, and `tests/test_hospital_kit.py`.

The generated `hospital.glb` and 512px preview are handed to 2WKG-374 rather
than committed to Git. `.gitignore` and `scripts/validate_asset_archetypes.py`
both cover this directory, so a stray binary is ignored and reported rather than
committed.

`triangles_lod0/1/2` in the meta are the shared catalog's budgets for this
archetype, not measurements: this source builds a single LOD0 mesh, and no
lod1/lod2 geometry is produced here. Decimation is 2WKG-374's pipeline step.
