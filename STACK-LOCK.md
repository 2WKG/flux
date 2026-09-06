# Flux demo stack lock

This hackathon demo is a static web app backed by precomputed local JSON.

> **Runtime contract decided (2WKG-300): static assets, no demo API.** The client bundles
> `data/demo/bundle.json` at build time and issues no runtime request; `web/server.mjs` serves the
> built `web/dist/` and exposes no API route. This resolves the contradiction previously recorded
> here and in `README.md` under 2WKG-296. The bundler is esbuild (`web/scripts/build.mjs`), not
> Vite — corrected here because the earlier "React + Vite" wording never matched the build.

## Chosen stack

| Layer | Choice |
| --- | --- |
| Web | React + esbuild + TypeScript |
| Map | MapLibre GL JS + deck.gl |
| Calculation | Python + pandapower |
| Result handoff | JSON files written to disk |
| Presentation | Built static assets served by a local static server through the existing `bouncepulse.com` Cloudflare Tunnel |

The web app reads saved result files only. Python is run before presentation and writes the final JSON bundle to disk for the web app to serve. There is no API, database, authentication, queue, live feed, or new deployment service.

## Runtime contract

- Pin the Node and Python package versions in the web and model manifests after their first successful build/import check.
- Keep the JSON bundle small and local. Copy the generated bundle into the web app's static assets as part of the export step.
- Serve the build output with a static server (`web/server.mjs`); it serves files only and must not gain an API route.
- Reuse the existing Cloudflare Tunnel and its configured local origin for `bouncepulse.com`; this task does not create or modify tunnel infrastructure.

## Optional GNN training stack

The GNN toolchain is opt-in: `uv sync --extra gnn` installs it for graph-model
training, while the demo, API, and ordinary pipeline environments omit it. GNN
callers must import `torch` and `torch_geometric` at the training entry point,
never from a module imported by those ordinary paths.

| Package | Pinned version | Verification |
| --- | --- | --- |
| `torch` | `2.7.1` | Imported successfully on macOS arm64 / Python 3.12.13; `torch.cuda.is_available()` was `False`. |
| `torch-geometric` | `2.6.1` | Imported successfully with the pinned Torch version on the same environment. |

The verified macOS wheel is CPU/MPS-capable and did not expose CUDA. No CUDA
index or accelerator package is configured in Flux; choose one explicitly for
any future Linux GPU environment rather than changing this optional baseline.

Verification recorded 2026-09-06:

```sh
uv sync --extra gnn
uv run --extra gnn python -c 'import torch, torch_geometric; print(torch.__version__, torch_geometric.__version__, torch.cuda.is_available())'
```

## Demo boundary

The app presents one fixed stress snapshot, baseline plus two 300 MW candidate additions, and signed saved comparisons. It does not perform live calculations or fetch data during the demo. The model is a synthetic-grid illustration, not a representation of a real grid.
