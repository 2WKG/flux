---
title: "Workspace build and deployment handoff"
status: draft — deployment and external routing are not established
issue: 2WKG-353
base: a9d7e0142bbc1e5887684fdfa752a4e9d9d3eccf
depends_on:
  - "2WKG-352 / draft PR #204"
  - "external routing ownership and verified deployment handoff"
---

# Workspace build and deployment handoff

## Scope and readiness boundary

This runbook hands off a local build and verification procedure. It does not
publish a host, configure a tunnel or connector, assert a public endpoint, or
authorize a live provider. The default explorer is a static, bundled synthetic
fixture. The FastAPI/Copilot path is optional and separately configured.

The source-receipt inventory is evidence metadata. Its seven receipts do not
by themselves provide a renderable geometry, topology, placement, allocation,
or model result. The browser must continue to render an explicit unavailable
state when the required server artifact is absent.

Where an artifact is rendered, use only the frozen 3D UI states
`source_supported`, `source_screened`, `hypothetical`, `synthetic`,
`unavailable`, and `request_failed`. A source receipt alone cannot promote an
object to `source_supported`, and the browser must not invent an
`illustrative` status.

## Exact build inputs

This document was prepared on `a9d7e0142bbc1e5887684fdfa752a4e9d9d3eccf`.
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
this handoff does not amend either runbook.

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
| Static request boundary | required | required for static mode | browser monitoring shows no unapproved API/SSE dependency |
| `/health` | not applicable | required before availability is claimed | documented health response confirms the configured local service; otherwise report unavailable |
| SSE | not applicable | required only for a configured live-agent rehearsal | stream events and terminal/unavailable behavior are observed through the configured route; do not infer either from a build |
| Connector routing/restart | blocked | blocked | only owner-supplied host, route, restart, and rollback instructions count as evidence |

For local static checks, start the built server after the build and use its
reported local origin. Verify a root route and one direct client route in the
same browser profile. Observe the browser request log during the unavailable
Ask flow before declaring the static path self-contained.

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
| Full Texas 3D coverage | unmet — no claim made |
| Live provider and SSE | optional, configuration-dependent, and unverified externally |
| Public deployment / connector | blocked pending owner-provided routing and restart evidence |
| Issue status | keep 2WKG-353 In Progress until 2WKG-352 and the external handoff are complete |
