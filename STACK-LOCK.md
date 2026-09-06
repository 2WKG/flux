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

## Optional GNN toolchain (2WKG-488)

- `gnn` is a separate optional extra; `stretch` contains only `grid2op`.
- On Windows with Python 3.12.10, `uv sync --extra gnn` completed successfully with `torch==2.14.0` and `torch-geometric==2.8.0.post1`.
- Verified imports: `torch.__version__ == "2.14.0+cpu"` and `torch_geometric.__version__ == "2.8.0.post1"`. `torch.cuda.is_available()` is `False`, `torch.version.cuda` is `None`, and a default tensor uses `cpu`.

## Demo boundary

The app presents one fixed stress snapshot, baseline plus two 300 MW candidate additions, and signed saved comparisons. It does not perform live calculations or fetch data during the demo. The model is a synthetic-grid illustration, not a representation of a real grid.
