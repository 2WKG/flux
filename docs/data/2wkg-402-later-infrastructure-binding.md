# 2WKG-402 later-infrastructure runtime binding

The published `flux-grid-runtime-v1-20260906` release is reusable geometry.
It was downloaded fresh from the release attachment, checked against archive
SHA-256 `44ed49bd7e2a8392765825fdfc164e01061e7701befd8b89eaf38ac9ecc45d78`,
extracted, and its `manifest.json` checked against
`068ca96a44b9730f3d59ab55c454cf5a8959b285db62625bbd2bcad57afd067b`.

Install from a fresh extraction with:

```sh
node scripts/install_flux_grid_pack.mjs \
  /path/to/flux-grid-runtime-v1-20260906T103700Z \
  /path/to/flux-grid-runtime-v1-20260906T103700Z.zip
```

The installer verifies the archive and complete package, then writes its 96
files under `web/public/assets/flux-grid/`. It does not create Minnesota
locations or enable a scene layer.

[`data/3d/receipts/minnesota-later-infrastructure-binding-v1.json`](../../data/3d/receipts/minnesota-later-infrastructure-binding-v1.json)
records the four requested archetypes. Each is a `catalog_preview` with an
`unavailable` label because the exact-base Minnesota inventory has no accepted
placement-capable facility artifact. A web mount must wait for an accepted
server artifact with provenance, an available manifest, permitted point
placement, and an accepted coordinate/identity envelope; it must not infer a
facility, coordinates, topology, flow, or status from this asset pack.
