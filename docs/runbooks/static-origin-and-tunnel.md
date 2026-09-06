# Static origin and tunnel inventory

Last checked: 2026-09-05

This is an inventory, not a provisioning guide. It records only checked-in
configuration and a public, read-only tunnel check; it intentionally contains no
credentials, connector IDs, or private hostnames.

## Current status

`https://bouncepulse.com` is served by Cloudflare, but a header check on
2026-09-05 returned HTTP `530`. The tunnel connector is therefore not reachable
at the time of this inventory. `cloudflared` is not on this Windows machine's
`PATH`.

The checkout has no tracked Cloudflare Tunnel configuration, service definition,
or connector credential. The local static origin is fully identified below; the
public hostname-to-origin mapping is not.

## Static origin (authoritative)

| Item | Verified mapping |
| --- | --- |
| Process | Node/Express, started by `npm --prefix web run start` |
| Source/config | `web/server.mjs` is authoritative for origin routes and port loading; `web/package.json` defines the start/build scripts |
| Bind port | `PORT`, default `4173` (`server.mjs` calls `app.listen(port)`) |
| Bind address | Not explicitly configured in source; Node's default listen host is used. Do not assume a loopback or LAN bind without checking the connector host. |
| Static build | `web/dist/`, built by `npm --prefix web run build` |
| Demo data | `data/demo/bundle.json`, bundled into `web/dist/assets/app.js` at build time. The origin serves no API route (2WKG-300), so regenerating the bundle requires a rebuild. |
| Service owner | Not recorded in this checkout |

The static server's only environment variable is `PORT`; no value is recorded
here. It loads it directly from the process environment when it starts, so there
is no checked-in environment file or wrapper that overrides it.

## Route ownership

| Host and path | Current owner | Local target | Status |
| --- | --- | --- | --- |
| local `GET /` and SPA client routes | `web/server.mjs` | `web/dist/` on a Node/Express static process | Verified; requires a built `web/dist/` |
| local `GET /api/demo` | No owner | — | Removed by 2WKG-300. The origin serves static assets only; this path now falls back to the SPA shell like any unknown path. |
| `https://bouncepulse.com/*` | Cloudflare public edge | Unknown connector/origin mapping | Public check returns `530`; no route can be attributed to the local origin yet |
| optional `GET /health` | `copilot.app:app` | FastAPI on port `8000` | Implemented; see `docs/runbooks/local-startup.md`. Not tunnel-mapped. |
| optional `POST /ask` (SSE) | `copilot.app:app` | FastAPI on port `8000` | Implemented as an injected local transport; the default backend emits explicit unavailable SSE. It is not tunnel-mapped. |

The FastAPI paths are implemented for local use but are not evidence of a
running API or a public mapping. `POST /ask` starts only the injected local SSE
transport; without an injected backend it reports unavailable and it does not
contact a provider. The specifications name `ANTHROPIC_API_KEY`,
`VOYAGE_API_KEY`, `DUCKDB_PATH`, and `COPILOT_MODEL`, but none is read by the
checked-in static server. The tunnel's own environment-variable names are
unknown because its configuration is not available in the repository.

## Minnesota demo scope

The Minnesota demonstration is a separate scope with its own planning authority
([`docs/specs/10-minnesota-demo.md`](../specs/10-minnesota-demo.md)). It does not
create a Minnesota fixture or topology, and it does not reuse the Texas
ACTIVSg2000 adapter. Its API/SSE routing contract is not yet implemented or
tunnel-mapped.

The Texas-first shared overview ([`docs/specs/00-overview.md`](../specs/00-overview.md))
remains the primary reference for the repository's routing, API, and tunnel
contract. The Minnesota demo inherits neutral engineering patterns only after
its own source and model gates are accepted; until then, no Minnesota-specific
route, fixture, or tunnel mapping is claimed in this inventory.

## Start and verify the static origin

From the repository root on the machine that will run the origin:

```powershell
npm --prefix web ci
npm --prefix web run build
$env:PORT = 4173 # omit to use the default
npm --prefix web run start
```

In another shell, verify the SPA shell and the built client asset:

```powershell
curl.exe -I http://127.0.0.1:4173/
curl.exe -I http://127.0.0.1:4173/assets/app.js
```

Both should return `200`; the first is the built HTML and the second the bundled
client, which already contains the demo fixture. Restart the static origin by
stopping that Node process and rerunning `npm --prefix web run start` with the
intended `PORT`.

After the connector owner restores a mapping to this origin, verify the public
route without exposing configuration values:

```powershell
curl.exe -I https://bouncepulse.com/
```

It should return the same built HTML as the local root, not HTTP `530`. Do not restart
or install `cloudflared` on this laptop as a substitute for the missing owner
configuration.

## Tunnel blocker and handoff

The Cloudflare Tunnel service owner and connector host are unknown. The person
with Cloudflare Zero Trust Tunnel access **and** administrator access to the
machine that runs the connector must provide these non-secret facts before the
mapping can be completed:

1. The connector host and the person responsible for keeping it online.
2. Whether the authoritative mapping is managed in the Cloudflare dashboard or a
   connector configuration file, plus that configuration file's path.
3. The public-hostname path rules and each local service/port they target,
   including any future API/SSE rule.
4. The service-manager name and its approved restart/status commands.

Until that handoff is available, `bouncepulse.com` cannot be assigned to a local
port, and no API/SSE public routing should be claimed. This is the concrete
blocker for the follow-up external-health and SSE verification work.
