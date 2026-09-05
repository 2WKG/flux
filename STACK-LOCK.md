# Flux demo stack lock

This hackathon demo is a static web app backed by precomputed local JSON.

## Chosen stack

| Layer | Choice |
| --- | --- |
| Web | React + Vite + TypeScript |
| Map | MapLibre GL JS + deck.gl |
| Calculation | Python + pandapower |
| Result handoff | JSON files written to disk |
| Presentation | Built Vite assets served by a local static server through the existing `bouncepulse.com` Cloudflare Tunnel |

The web app reads saved result files only. Python is run before presentation and writes the final JSON bundle to disk for the web app to serve. There is no API, database, authentication, queue, live feed, or new deployment service.

## Runtime contract

- Pin the Node and Python package versions in the web and model manifests after their first successful build/import check.
- Keep the JSON bundle small and local. Copy the generated bundle into the web app's static assets as part of the export step.
- Serve the Vite build output with a static server; do not use Vite's preview server as the judge-facing origin.
- Reuse the existing Cloudflare Tunnel and its configured local origin for `bouncepulse.com`; this task does not create or modify tunnel infrastructure.

## Demo boundary

The app presents one fixed stress snapshot, baseline plus two 300 MW candidate additions, and signed saved comparisons. It does not perform live calculations or fetch data during the demo. The model is a synthetic-grid illustration, not a representation of the real Texas grid.
