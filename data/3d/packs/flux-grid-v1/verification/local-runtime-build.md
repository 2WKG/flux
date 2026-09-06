# Local runtime asset build

This is the reproducible delivery path for the generated browser assets. It
keeps generated GLBs out of Git while producing a self-contained, checksum
pinned package that a renderer can serve at `/assets/flux-grid/`.

Run from the repository root on macOS with Blender installed:

```sh
ARTIFACT_ROOT=/Users/joshua/flux-artifacts
PACK=$ARTIFACT_ROOT/flux-grid-v1
RUNTIME=$ARTIFACT_ROOT/flux-grid-runtime-v1

/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
  --python data/3d/packs/flux-grid-v1/source/pipeline/build_pack.py -- \
  --output "$PACK" --catalog "$PWD/data/3d/asset-archetypes-v1.json"
uv run --extra dev python data/3d/packs/flux-grid-v1/validation/validate_pack.py \
  --root "$PACK" --catalog data/3d/asset-archetypes-v1.json \
  --output "$PACK/validation/independent-audit.json"
mkdir -p "$PACK/symbols"
sips -s format png data/3d/packs/flux-grid-v1/assets/symbols/flux-grid.svg \
  --out "$PACK/symbols/flux-grid.png"
sips -z 192 384 -s format png data/3d/packs/flux-grid-v1/assets/symbols/flux-grid.svg \
  --out "$PACK/symbols/flux-grid@2x.png"
cp data/3d/packs/flux-grid-v1/assets/symbols/{flux-grid.json,flux-grid@2x.json,deck-icon-mapping.json} "$PACK/symbols/"
uv run --extra dev python data/3d/packs/flux-grid-v1/source/pipeline/assemble_runtime_pack.py \
  --build "$PACK" --audit "$PACK/validation/independent-audit.json" --symbols "$PACK/symbols" \
  --output "$RUNTIME" --zip "$ARTIFACT_ROOT/flux-grid-runtime-v1.zip"
```

The assembler refuses a partial or failed GLB audit. Its `manifest.json` maps
all 18 archetypes to three measured LODs and pins SHA-256 and byte size for the
54 models. Its `package.SHA256SUMS` covers every served file. The ZIP is a
portable release artifact; it is not a runtime CDN and it carries no placement
or topology claims.
