---
title: "Workspace build and deployment handoff"
status: draft — deployment and external routing are not established
issue: 2WKG-353
base: fedcf18e167491c02462df978bec1f2a7cc46ba3
depends_on:
  - "2WKG-352 / draft PR #204"
  - "external routing ownership and verified deployment handoff"
---

# Workspace build and deployment handoff

## Scope and readiness boundary

This runbook hands off a local build and verification procedure. It does not
publish a host, configure a tunnel or connector, assert a public endpoint, or
authorize a live provider. Its analysis UI is a static, bundled synthetic
fixture. The FastAPI/Copilot path is optional and separately configured. The
renderer additionally has the narrow basemap network boundary described below;
static analysis behavior is not a promise of a wholly offline browser session.

The source-receipt inventory
[`data/sources/texas-p0-inventory.json`](../../data/sources/texas-p0-inventory.json)
is evidence metadata. Its eleven records — of which exactly one,
`activsg2000-current`, carries a `checked_in_receipt` — do not by themselves
provide a renderable geometry, topology, placement, allocation, or model
result. The browser must continue to render an explicit unavailable
state when the required server artifact is absent.

Where an artifact is rendered, use only the frozen 3D UI states
`source_supported`, `source_screened`, `hypothetical`, `synthetic`,
`unavailable`, and `request_failed`. A source receipt alone cannot promote an
object to `source_supported`, and the browser must not invent an
`illustrative` status.

### Minnesota restatement (2WKG-407)

This runbook was written for the Texas line and is restated here for Minnesota.
`docs/specs/10-minnesota-demo.md` supersedes the Texas geography, ERCOT,
Uri/Beryl/Helene scenarios, ACTIVSg2000 topology, and Texas/NY site framing
wherever they govern the Minnesota demo, so read every Texas-era sentence in
this document as build-and-verification procedure only, never as accepted
geography or data.

- **Aggregate only; no topology.** The network decision gate in spec 10 has not
  produced an accepted source decision record, so aggregate mode is what this
  handoff may hand off: one named regional stress metric with its formula,
  units, regional allocation assumptions, and source/synthetic status. It must
  not emit or imply bus flows, line ratings or loading, DC power flow, or N-1
  conclusions, and topology-mode implementation stays blocked until that record
  is accepted.
- **No relabelling.** The five-bus fixture this runbook builds and serves is
  synthetic. Do not call it Minnesota, Texas, ERCOT, MISO, or an actual
  interconnection model, and do not relabel ACTIVSg2000 as Minnesota.
- **Texas-era evidence stays Texas-era.**
  [`data/sources/texas-p0-inventory.json`](../../data/sources/texas-p0-inventory.json)
  is the Texas source-receipt inventory. It establishes nothing about Minnesota
  geography, topology, allocation, or model results; the Minnesota source basis
  is the table in `docs/specs/10-minnesota-demo.md`.
- **The 3D asset gate is unchanged and unmet.** Nothing below establishes
  Minnesota 3D coverage, and no Minnesota placement may be rendered until a
  server artifact supplies its WGS84 position, identity, provenance, and frozen
  status.

## Exact build inputs

This document was prepared on `a9d7e0142bbc1e5887684fdfa752a4e9d9d3eccf` and
its runnable claims were re-checked on `fedcf18e167491c02462df978bec1f2a7cc46ba3`
(the merge-target head at the time of this revision): the lockfile digest below,
`npm ci`, `npm run build`, `npm run start`, the root and deep-refresh routes, and
`uv sync --frozen --extra dev` all behaved as documented there.
The static build is locked by `web/package-lock.json` SHA-256:

```
806c3be47486c9d388dd33068c7aaeeb739c8f704966aff3f44e0646d03ecdba
```

Use the lockfile; do not substitute `npm install` for reproducible verification.
The package-root scripts at this revision are:

```sh
cd web
npm ci
npm run build       # lint, TypeScript no-emit check, then scripts/build.mjs
npm run start       # local Node static origin
```

The repository's standard local start/stop instructions remain
[`local-startup.md`](local-startup.md). Its static-origin and tunnel material is
owned elsewhere in [`static-origin-and-tunnel.md`](static-origin-and-tunnel.md);
this handoff does not amend either runbook. Read that second document with one
caveat: its `GET /api/demo` rows predate 2WKG-300 (`db53a83`), which deleted the
route, so its instruction to `curl` `/api/demo` and expect JSON from
`data/demo/bundle.json` is stale — the static origin answers every unmatched
path, `/api/demo` included, with the SPA shell (`200 text/html`, confirmed
against `web/server.mjs` on the pinned revision). `local-startup.md` is
authoritative for the static origin's routes.

## Deck.gl and MapLibre renderer readiness

The approved renderer foundation is deck.gl 9.3.11 over MapLibre GL 6.7.0,
using `react-map-gl/maplibre` 8.1.3 and an interleaved `MapboxOverlay` from
`@deck.gl/mapbox`. It is renderer infrastructure, not an acceptance of a
feature layer, state geography, topology, placement, or asset. Its initial
render may therefore contain **zero accepted feature layers** and must show an
explicit provenance/status disclosure that those data are unavailable.

The current synthetic fixture remains a screen-space Cartesian preview. It
must never be converted to WGS84, drawn as a MapLibre feature, or used to
choose a map camera, placement, or source-backed status. A MapLibre mount and
deck.gl overlay do not change that fact.

When a networked basemap is configured, spec 06's current default is
OpenFreeMap dark:

```
https://tiles.openfreemap.org/styles/dark
```

Leave MapLibre's attribution control enabled; do not set
`attributionControl: false`. The configured style provides the required
OpenFreeMap/OpenMapTiles/OpenStreetMap attribution. An unavailable basemap is
a separate renderer/network condition from unavailable feature data. A
foundation that deliberately avoids a remote basemap fetch must disclose that
it has not exercised external tiles, glyphs, or attribution delivery.

### Approved basemap network boundary

The static analysis interface may load its own same-origin built assets and
MapLibre workers, plus only the configured OpenFreeMap resources: the dark
style at `https://tiles.openfreemap.org/styles/dark`, its `planet` TileJSON and
tile resources on `https://tiles.openfreemap.org`, glyphs at
`https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf`, and sprite
resources under `https://tiles.openfreemap.org/sprites/`. That is online
basemap access, separate from the static analysis fixture. It does not permit a
model fetch, a provider connection, `/ask`, or `/api` request.

Treat a style, tile, or glyph failure as a basemap-renderer condition, never as
evidence about feature data or a reason to substitute geographic geometry. The
renderer must preserve its explicit unavailable provenance/status disclosure.
The renderer owner confirmed at `47c7918` that a browser test aborts
`https://tiles.openfreemap.org/**`, displays `Basemap unavailable: {MapLibre
error.message}` in the Map and renderer status notice, and can still select
Candidate A in the synthetic fixture. Its network allowlist permits same-origin
static assets/workers and only `tiles.openfreemap.org` paths `/styles/`,
`/planet`, `/fonts/`, and `/sprites/`; it prohibits `/ask` and `/api`. This is
local browser evidence, not an external deployment or source-geometry claim.

For the interleaved overlay, attach `MapboxOverlay({interleaved: true})` with
`useControl`, update it with the layer list, and choose `beforeId` from the
loaded style's first `symbol` layer at runtime. The OpenFreeMap dark style's
known default is `water_name`, but style identifiers vary; do not hard-code a
label id as a general contract. If no symbol layer exists, record the overlay
mode and label-order limitation instead of pretending labels were preserved.

### Later 3D asset gate

The frozen asset contract remains authoritative: a deliverable is a neutral
`.glb` with metre unit scale 1.0, Y-up, −Z-forward, right-handed coordinates,
and a `ground_center` pivot. `ScenegraphLayer` is the intended deck.gl layer
only after a server artifact supplies a placement's WGS84 position, identity,
provenance, and frozen status. Its `scenegraph` URL/promise, `getPosition`,
`getOrientation`, `getScale`, and `pickable` behavior must be exercised with a
neutral test asset before accepting a real asset path.

Binary `.glb`/`.gltf` files are deliberately untracked. Before a static build
can render one, an asset owner must provide its immutable URL or build-copy
step, SHA-256, licence metadata, loader/CORS behavior, and a load failure that
renders `unavailable` without fallback geometry. Asset axes must be proven in
the actual ScenegraphLayer adapter; do not assume a glTF's local Y-up/−Z axes
are automatically the same as a map placement's world axes.

`MAT_STATUS` is also a proof obligation. The frozen contract requires a
status material slot, while ScenegraphLayer's documented `getColor` is used
only when no texture is present. A textured glTF therefore needs a verified
material-tint adapter or a separate contract-compliant status presentation;
do not claim that `getColor` alone tints a named material slot.

Keep renderer data references stable and use deck.gl update triggers for
selection/status changes so those changes do not rebuild geometry buffers.
That is an implementation readiness rule, not a performance result; no
accepted 3D performance budget exists yet.

## Two operating modes

| Mode | What it serves | Required inputs | What it does not prove |
| --- | --- | --- | --- |
| Default static explorer | Bundled synthetic fixture through the Node web server | `web/package-lock.json`, `npm ci`, successful build | an API, live agent, source-backed geometry, a state topology, or a public deployment |
| Optional configured FastAPI/Copilot | Local API and, only when separately configured, provider-backed responses | frozen Python environment, explicit database/configuration, provider credentials in their native environment | that the static explorer depends on it, or that a public SSE route exists |

For the optional path, prepare the supported Python environment first:

```sh
uv sync --frozen --extra dev
```

Run the API only with its documented configuration and data artifact. Check
`/health` before presenting it as available. A missing configuration, database,
provider, or eligible artifact is an unavailable result, never permission to
replace it with static values. The response behavior and recovery procedure are
owned by [`api-sse-recovery.md`](api-sse-recovery.md).

## Confirmed 2WKG-352 browser-proof intake

2WKG-352 is the dependency for this handoff. Its current work is draft PR
[#204](https://github.com/2WKG/flux/pull/204), head `753427c`. The confirmed
local composition is the frozen UI base `53cfafc`, its owner repair
`cc57ecc` cherry-picked as `8786c34`, and proof commits `eb1cf2a` and
`753427c`. The inherited UI leaves are PRs #183 (chat), #185 (inspector),
#186 (results), #189 (run trace), and #191 (shell).

When that composition is checked out, its portable browser proof is:

```sh
cd web
npm ci
npm run test:e2e
```

That script exists only on PR #204's head `753427c`, whose `web/package-lock.json`
is `57fbad158ac0c457a6791af3f33a52cfa86d9345f26a5c24ae7273b4797ac506` (it adds
`@playwright/test`) and is therefore **not** covered by the `806c3be4…` digest
pinned above; on the merge target `npm run test:e2e` exits 1 with
`npm error Missing script: "test:e2e"`.

The test runner prefers system Chrome through its environment executable; when
that is unavailable, install Playwright Chromium explicitly:

```sh
npx playwright install chromium
```

The 2WKG-352 owner confirmed five passing Chrome cases: selection/inspector;
unavailable Ask with trace/results; edit then collapse/reopen persistence and
candidate scenario/revision changes; modal keyboard/focus; and no desktop,
laptop, or mobile overflow after fonts load. Its request monitor observed no
`/ask` or `/api` request in the static run. Local supporting checks reported by
that owner were typecheck/lint, data (33), rehearsal (2), and static-demo (3).
That PR #204 observation predates the approved MapLibre mount, so it supports
only the absence of `/ask` and `/api` in that earlier static run; it does not
prove the current basemap network boundary or basemap-unavailable behavior.

Those are dependency evidence, not a deployment certificate. They do **not**
establish 3D geometry, source-backed geometry, live provider/SSE behavior,
external rehearsal, an accepted performance budget, or public availability.

## Preflight and operational verification

Run the checks that apply to the selected mode and record the actual result.

| Check | Static explorer | Optional FastAPI/Copilot | Pass condition |
| --- | --- | --- | --- |
| Root route | required | required when a web origin is served | root returns the built application shell |
| Deep refresh | required | required when a web origin is served | a direct refresh of a client route remains in the application shell, not a server 404 |
| Browser/device | required | required | keyboard focus and desktop/laptop/mobile layouts are usable; record viewport and browser |
| Static request boundary | required | required for static mode | browser monitoring permits same-origin built assets/workers and configured OpenFreeMap `/styles/`, `/planet`, `/fonts/`, and `/sprites/` resources only; it observes no model/provider, `/ask`, or `/api` request |
| `/health` | not applicable | required before availability is claimed | documented health response confirms the configured local service; otherwise report unavailable |
| SSE | not applicable | required only for a configured live-agent rehearsal | stream events and terminal/unavailable behavior are observed through the configured route; do not infer either from a build |
| Connector routing/restart | blocked | blocked | only owner-supplied host, route, restart, and rollback instructions count as evidence |

For local static checks, start the built server after the build and use its
reported local origin. Verify a root route and one direct client route in the
same browser profile. Observe the browser request log during the unavailable
Ask flow: distinguish allowed OpenFreeMap basemap requests from prohibited
model/provider, `/ask`, and `/api` requests. Do not call the whole browser
session offline while the configured basemap is reachable over the network.

For configured API checks, make the `/health` request against the locally
started service and exercise both the intended SSE interaction and the
unavailable-provider path. Record the exact endpoint, command, configuration
source, and observed event/result; no generic endpoint, host, or restart
command is supplied here because none has been verified for external use.

## External handoff blockers

External deployment is not ready to claim. The known blockers are:

- historic public access failure reported as Cloudflare 530;
- no confirmed connector owner, mapping, externally reachable route, restart
  procedure, rollback procedure, or status endpoint; and
- no verified external SSE trace.

Before any external rehearsal, the routing owner must provide a reviewable
handoff containing the public origin, exact route mapping, service owner,
start/restart and rollback commands, health check, expected SSE behavior, and
a real external trace. Until then, use local static verification only and call
all external/API-live behavior unavailable.

## Handoff record

| Item | Current state |
| --- | --- |
| Static build | locally reproducible from the lockfile; verify on the checkout being presented |
| 2WKG-352 browser proof | dependency evidence from draft PR #204; final integration/merge remains pending |
| Full Texas 3D coverage | unmet — no claim made; superseded for the Minnesota line by `docs/specs/10-minnesota-demo.md` |
| Minnesota coverage | aggregate mode only, and not yet built; no Minnesota topology, geometry, placement, or 3D coverage is claimed |
| Live provider and SSE | optional, configuration-dependent, and unverified externally |
| Public deployment / connector | blocked pending owner-provided routing and restart evidence |
| Issue status | keep 2WKG-353 In Progress until 2WKG-352 and the external handoff are complete |
