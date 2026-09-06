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

The scenario explorer reads saved result files only: Python is run before presentation and writes the final JSON bundle to disk, which the web app bundles at build time. That half needs no API and is unchanged.

Since 2WKG-355 the same App also carries the evidence surfaces — chat, run trace, results, layers, inspector, and the physical-inventory map — and those **do** read the Copilot API, same-origin, at runtime (`docs/specs/spec-code-reconciliation.md`, D-10). This repository still adds no database, authentication, queue, or deployment service of its own: the API is the separate FastAPI service specs 05 describes, reached through the optional `FLUX_API_ORIGIN` seam below. With no API reachable, every one of those surfaces renders a named `unavailable`/`request_failed` state and the bundled scenario explorer is unaffected.

## Runtime contract

- Pin the Node and Python package versions in the web and model manifests after their first successful build/import check.
- Keep the JSON bundle small and local. Copy the generated bundle into the web app's static assets as part of the export step.
- Serve the build output with a static server (`web/server.mjs`); it serves files only and must not gain an API route of its own.
- **`FLUX_API_ORIGIN` (optional, unset by default).** Since 2WKG-355 the one App is server-backed
  (`docs/specs/spec-code-reconciliation.md`, D-10) and its own CSP is `connect-src 'self'`, so a
  demo deployed beside a live Copilot API needs that API on the same origin. When this variable
  names an origin, `web/server.mjs` forwards a **fixed allowlist of read paths** to it —
  `GET /api/v1/grid/layers/{layer}`, `GET /health`, `GET /layers/{name}`, `GET /scenarios`,
  `GET /scenarios/{id}` and `POST /ask` — with a 30-second deadline, streaming the response so an
  SSE answer is not buffered. Nothing else is forwarded, and an unreachable upstream answers in the
  shared failure-envelope shape rather than an HTML error page. With the variable unset every one
  of those paths falls through to the SPA shell and the page renders its named unavailable states.
  `FLUX_GRID_API_ORIGIN` is accepted as an alias for the name PR #245 used.
- Reuse the existing Cloudflare Tunnel and its configured local origin for `bouncepulse.com`; this task does not create or modify tunnel infrastructure.

## Demo boundary

The app presents one fixed stress snapshot, baseline plus two 300 MW candidate additions, and signed saved comparisons. **No live calculation is performed anywhere**: every route the browser reads is a persisted-artifact read, and the browser derives no label, geometry, or number of its own. That fixed snapshot is a synthetic-grid illustration, not a representation of a real grid, and it says so on the screen.

What the app *does* fetch at runtime, since 2WKG-355, is evidence: source-backed physical inventory, scenario provenance, layer statuses, and a Copilot answer stream. Each arrives labelled with one of the six frozen status tokens, and each is shown as unavailable by name when it does not arrive.
