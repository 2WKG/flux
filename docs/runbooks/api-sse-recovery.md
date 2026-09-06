# API/SSE outage recovery runbook

Use this runbook when the external Copilot API or its SSE stream is unavailable.
It preserves the static demo and separates what a presenter can say from the
diagnostics an operator can perform. It does not provision a tunnel, disclose
configuration values, or substitute polling for SSE.

## User-visible response

1. Keep the static scenario demo open. It uses the checked-in synthetic fixture,
   bundled into the client at build time; it makes no runtime request at all, so
   it does not require the Copilot API or SSE.
2. Do not claim that the Ask/Copilot interaction is connected. State that the
   interactive Copilot service is temporarily unavailable and continue with
   the static demo.
3. Do not display a guessed answer, cached analytical result, or a polling
   substitute as though it were an SSE response.

This checkout has no deployed UI implementation of a Copilot unavailable
message yet. The presenter instruction above is therefore an operational
fallback, not a claim of an automatically rendered state.

## Detection and triage

Record only the UTC time, public route, HTTP status, and redacted header/event
types. Never include connector credentials, environment values, request text,
or model output in an incident note.

| Symptom | Meaning | Immediate action |
| --- | --- | --- |
| Public route returns Cloudflare `530` | The public edge cannot reach its connector/origin. | Keep the static demo; request the tunnel-owner handoff below. |
| Public API returns a valid failure envelope | The API answered, but its artifact or service is unavailable. | Show the user-safe unavailable state when the API UI is deployed; retain request id only for operator correlation. |
| SSE connects but has no terminal event | Stream lifecycle failure. | Stop the client, save redacted event ids/types, and escalate to the API owner. Do not retry as polling. |
| Local static origin fails | Static build/process failure. | Use the local fallback drill below before involving the tunnel owner. |

## Controlled static-fallback drill

Performed on 2026-09-05 from this checkout with no API or SSE service started:

```bash
cd web
npm ci
npm run build
PORT=4317 npm run start
```

In a second shell, the observed results were:

```text
GET  http://127.0.0.1:4317/          -> 200 text/html
GET  http://127.0.0.1:4317/api/demo  -> checked-in fixture (schemaVersion: 1)
POST http://127.0.0.1:4317/ask       -> 404
```

The 404 is expected for the current static origin and proves that it did not
pretend to provide an SSE or polling fallback. Stop the local process after the
check. Use a different free port if `4317` is occupied.

That `/api/demo` line records what was observed on 2026-09-05 and is kept as
evidence. It is no longer current: 2WKG-300 settled the runtime contract as
static assets only and removed the route, so the same request now returns the
SPA shell.

For every local rehearsal, run the repeatable contract check before presenting:

```bash
npm --prefix web run test:rehearsal
```

It starts the checked-in static origin on an ephemeral loopback port, verifies
the shell and bundled application, cross-checks the fixture's values, lineage,
units, and limitations, and asserts that the origin neither returns a demo API
payload nor impersonates an SSE endpoint. It does not test the public tunnel
or a deployed API.

## Local recovery order

1. Build and start the static origin as above. Verify `/` and
   `/assets/app.js` locally before considering external routing.
2. If a deployed Copilot API is available, use its owner-documented startup
   procedure and non-secret configuration names. Verify its documented
   `/health` response locally. Do not infer a database path or API key.
3. Run one documented fixture/stub `POST /ask` locally. Confirm
   `text/event-stream`, ordered lifecycle events, and exactly one terminal
   event. Exercise disconnect and server-error behavior separately.
4. Only after local API/SSE verification succeeds, ask the tunnel owner to use
   the connector host's approved status/restart procedure. This repository has
   no connector service name, configuration path, credential, or approved
   command.
5. Recheck the public static route, then repeat the fixture SSE check from a
   separate network/device. Record event ids/types and headers, not content.

## Current external blocker and escalation

The most recent read-only public checks (2026-09-05 19:31 UTC) found HTTP 530
at the public root, `/api/demo`, and safe `OPTIONS /ask`. `cloudflared` was not
available on the verification host. The detailed redacted record is in the
2WKG-152 evidence PR; no external stream was claimed.

External recovery is blocked until these owners provide their approved inputs:

1. **Tunnel owner / connector-host administrator:** connector host, approved
   status/restart procedure, and public host/path-to-origin mapping (2WKG-149).
2. **API owner:** a deployed health route plus the deterministic fixture SSE
   lifecycle and error behavior (2WKG-126 and 2WKG-127).
3. **Verification operator:** a separate network/device for the final external
   event-order, disconnect, and terminal-error observation (2WKG-152).

Until this handoff, do not install or restart `cloudflared`, modify DNS, or
claim that the public hostname serves the static origin, API, or SSE stream.
