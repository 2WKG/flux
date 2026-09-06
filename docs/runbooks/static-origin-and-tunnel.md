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
| Demo data | `data/demo/bundle.json`, read directly by the Express route `GET /api/demo`. The file is also bundled into `web/dist/assets/app.js` at build time. |
| Service owner | Not recorded in this checkout |

The static server's only environment variable is `PORT`; no value is recorded
here. It loads it directly from the process environment when it starts, so there
is no checked-in environment file or wrapper that overrides it.

## Route ownership

| Host and path | Current owner | Local target | Status |
| --- | --- | --- | --- |
| local `GET /` and SPA client routes | `web/server.mjs` | `web/dist/` on a Node/Express static process | Verified; requires a built `web/dist/` |
| local `GET /api/demo` | `web/server.mjs` | Node/Express on `PORT` (default `4173`) | Verified; reads `data/demo/bundle.json` on every request. The built client does not call it. |
| `https://bouncepulse.com/*` | Cloudflare public edge | Unknown connector/origin mapping | Public check returns `530`; no route can be attributed to the local origin yet |
| optional `GET /health` | `copilot.app:app` | FastAPI on port `8000` | Implemented; see `docs/runbooks/local-startup.md`. Not tunnel-mapped. |
| optional `POST /ask` (SSE) | No current runtime in this checkout | Planned FastAPI process on port `8000` | Specification only; not deployed or tunnel-mapped |

The FastAPI paths and port are a future contract in
`docs/specs/00-overview.md` and `docs/specs/05-copilot.md`; they are not evidence
of a running API. Those specs name `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`,
`DUCKDB_PATH`, and `COPILOT_MODEL`, but none is read by the checked-in static
server. The tunnel's own environment-variable names are unknown because its
configuration is not available in the repository.

## Start and verify the static origin

From the repository root on the machine that will run the origin:

```powershell
npm --prefix web ci
npm --prefix web run build
$env:PORT = 4173 # omit to use the default
npm --prefix web run start
```

In another shell, verify the SPA shell, the demo route, and the built client asset:

```powershell
curl.exe -I http://127.0.0.1:4173/
curl.exe http://127.0.0.1:4173/api/demo
curl.exe -I http://127.0.0.1:4173/assets/app.js
```

The first should return `200` (built HTML), the second JSON from `data/demo/bundle.json`, and the third the bundled client. Restart the static origin by
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
