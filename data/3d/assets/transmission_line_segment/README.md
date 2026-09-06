# Transmission tower and line segment

This is the neutral reusable shape for `transmission_line_segment`; it is not a
Minnesota placement. The two named connector empties are geometric attachment
points only and do not describe a circuit or energisation.

The scene is authored in the contract frame (metres, Y up, `-Z` forward, pivot on
the ground at the footprint centre) as the `SCENE_NODES` and `CONNECTORS` tables
in `transmission_line_segment.blender.py`. `contract_to_blender()` converts each
coordinate exactly once into Blender's Z-up world, and the glTF export runs with
`export_yup=True`, which converts it back; the two compose to the identity, so
the exported GLB carries the coordinates the meta declares.

Inspect the geometry without Blender — this prints the derived bounds, per-node
boxes, and connector positions that `scripts/validate_transmission_line_kit.py`
checks the meta against:

```sh
python transmission_line_segment.blender.py -- --dry-run
```

Build the handoff artifacts with Blender:

```sh
blender --background --python transmission_line_segment.blender.py -- /tmp/flux-assets
```

Blender is not part of this repository's toolchain, so the build/preview command
above is not exercised by the test suite or CI: the checks that do run are the
`--dry-run` manifest, the kit validator, and `tests/test_transmission_line_kit.py`.

Handoff must contain `transmission_line_segment.glb` and its 512px preview
beside `transmission_line_segment.meta.json`. Do not commit the generated GLB:
2WKG-374 owns binary storage, import, placement, and accepted-artifact binding.
`.gitignore` and `scripts/validate_asset_archetypes.py` both cover this
directory, so a stray binary is ignored and reported rather than committed.

`triangles_lod0/1/2` in the meta are the shared catalog's budgets for this
archetype, not measurements: this source builds a single LOD0 mesh, and no
lod1/lod2 geometry is produced here. Decimation is 2WKG-374's pipeline step.
