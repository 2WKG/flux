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

The assembler refuses a partial or failed GLB audit, and it refuses an audit
that does not describe the build it was handed. `--audit` is a separate file, so
before anything is copied every GLB, metadata record and preview the audit names
is re-hashed out of `--build` and compared against the `sha256`/`bytes` the audit
recorded, and the audit's `contract_id` is compared against `--catalog`; the same
binding runs again on the copied tree. A model replaced after the audit ran is
named and rejected, and no output directory is left behind. Its `manifest.json`
maps all 18 archetypes to three measured LODs and pins SHA-256 and byte size for
the 54 models. Its `package.SHA256SUMS` covers every served file. The ZIP is a
portable release artifact; it is not a runtime CDN and it carries no placement
or topology claims.

## What this rebuild does and does not reproduce

Measured by building twice from one checkout on Blender 5.2.1 LTS / macOS 26.6.2
arm64; the full receipt is `rebuild-determinism.json`.

| output | two builds, same machine | reproduces the committed pins |
|---|---|---|
| 54 GLBs | byte-identical | **no** |
| 18 `*.meta.json` | byte-identical | n/a (committed, re-hashed by CI) |
| 18 preview PNGs | **byte-different**, pixel-identical | **no** |
| `flux_grid_assets.blend` | **byte-different** | n/a (never committed) |

The previews differ only in Blender's embedded `tEXt` render metadata (`Date`,
`RenderTime`, `cycles.ViewLayer.*_time`); their decompressed pixel streams are
identical. That is enough to make `package.SHA256SUMS` different on every run,
so **this pack's binary inventory is not a reproducibility claim**. The
committed digests are one machine's receipts, and the pack records no Blender
version, exporter version or OS for them, so the toolchain that produced them
cannot now be identified. An independent review of PR #255 rebuilt on Blender
5.2.1 and found all 54 triangle counts identical but 16 of 54 GLB digests
different, and `scripts/install_flux_grid_pack.mjs` rejecting the rebuilt
package at `assets/battery_storage/battery_storage.glb`.

The consequence is stated plainly rather than worked around: with
`archive.json.download_url` still `null` (see its `publication_blocker`), and a
rebuild that cannot satisfy the committed inventory, **no consumer can obtain an
installable pack today**. What a rebuilder can verify is the pack their own
build produced, against the audit that build produced — which is exactly the
binding above. Verifying against someone else's committed inventory requires the
archive to be published first.
