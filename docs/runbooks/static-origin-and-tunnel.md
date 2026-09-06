# Static origin and tunnel inventory

Last checked: 2026-09-06

This is an inventory plus the recorded deployment command for the origin host.
It records checked-in configuration, host checks, and a public, read-only tunnel
check; it intentionally contains no credentials, connector IDs, tunnel UUIDs, or
private hostnames.

## Current status

**There is no existing Cloudflare Tunnel to reuse.** The earlier tasks assumed
one was already configured; it is not. Checks on the intended origin host
(`WYZWORKSTATION`, user `willi`) on 2026-09-06:

| Check | Command | Result |
| --- | --- | --- |
| Public hostname | `Invoke-WebRequest -Uri https://bouncepulse.com/ -Method Head` | HTTP `530` |
| DNS | `Resolve-DnsName bouncepulse.com -Type A` | `172.67.218.236`, `104.21.24.128` — Cloudflare proxy addresses |
| Connector binary | `Get-Command cloudflared` | not on `PATH` |
| Connector service | `Get-Service *cloudflare*` | none installed |
| Connector process | `Get-Process *cloudflared*` | none running |
| Connector credentials | `Test-Path $env:USERPROFILE\.cloudflared` | `False` |
| Tracked config | repository grep for `cloudflare`/`tunnel` | docs only; no config, service definition, or credential |

`bouncepulse.com` is proxied by Cloudflare (the zone exists), but HTTP `530`
with no connector anywhere on this host means no tunnel origin has ever been
registered from here. The local static origin is fully identified below; the
public hostname-to-origin mapping does not exist yet.

## Static origin (authoritative)

| Item | Verified mapping |
| --- | --- |
| Process | Node/Express, started by `npm --prefix web run start` |
| Source/config | `web/server.mjs` is authoritative for origin routes and port loading; `web/package.json` defines the start/build scripts |
| Bind port | `PORT`, default `4173` (`server.mjs` calls `app.listen(port)`) |
| Bind address | Not explicitly configured in source; Node's default listen host is used. Do not assume a loopback or LAN bind without checking the connector host. |
| Static build | `web/dist/`, built by `npm --prefix web run build` |
| Demo data | `data/demo/bundle.json`, read directly by the Express route `GET /api/demo`. The file is also bundled into `web/dist/assets/app.js` at build time. |
| Origin host | `WYZWORKSTATION` (this Windows 11 workstation) — the designated demo host; no other candidate host exists |
| Service owner | William Zhang, who keeps `WYZWORKSTATION` and the origin process running for the demo window |

The static server's only environment variable is `PORT`; no value is recorded
here. It loads it directly from the process environment when it starts, so there
is no checked-in environment file or wrapper that overrides it.

## Route ownership

| Host and path | Current owner | Local target | Status |
| --- | --- | --- | --- |
| local `GET /` and SPA client routes | `web/server.mjs` | `web/dist/` on a Node/Express static process | Verified; requires a built `web/dist/` |
| local `GET /api/demo` | `web/server.mjs` | Node/Express on `PORT` (default `4173`) | Verified; reads `data/demo/bundle.json` on every request. The built client does not call it. |
| `https://bouncepulse.com/*` | Cloudflare public edge | No connector registered | Public check returns `530`; the intended target is `http://127.0.0.1:4173` on `WYZWORKSTATION` once the tunnel below is created |
| optional `GET /health` | `copilot.app:app` | FastAPI on port `8000` | Implemented; see `docs/runbooks/local-startup.md`. Not tunnel-mapped. |
| optional `POST /ask` (SSE) | `copilot.app:app` | FastAPI on port `8000` | Implemented as an injected local transport; the default backend emits explicit unavailable SSE. It is not tunnel-mapped. |

The FastAPI paths are implemented for local use but are not evidence of a
running API or a public mapping. `POST /ask` starts only the injected local SSE
transport; without an injected backend it reports unavailable and it does not
contact a provider. The specifications name `ANTHROPIC_API_KEY`,
`VOYAGE_API_KEY`, `DUCKDB_PATH`, and `COPILOT_MODEL`, but none is read by the
checked-in static server. The connector configuration recorded below reads no
environment variables; its mapping lives entirely in `config.yml` on the host.

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

It should return the same built HTML as the local root, not HTTP `530`.

## Deployment command (recorded, not yet run)

The checked-in scaffolding for these steps is [`deploy/`](../../deploy/README.md):
`deploy/serve.ps1` (build plus static origin), `deploy/tunnel.ps1` (preflight
plus connector), and `deploy/cloudflared/config.example.yml` (ingress template).

Because no tunnel exists to reuse, one must be created from this host. These are
the commands the owner runs on `WYZWORKSTATION`. **None of them has been run
yet** — `cloudflared tunnel login` opens a browser for Cloudflare account
authentication, so the owner must run this sequence interactively.

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel login                   # browser auth; select the bouncepulse.com zone
cloudflared tunnel create flux-demo        # writes credentials to $env:USERPROFILE\.cloudflared
cloudflared tunnel route dns flux-demo bouncepulse.com
```

Then copy `deploy/cloudflared/config.example.yml` to
`%USERPROFILE%\.cloudflared\config.yml`, which is the authoritative
hostname-to-origin mapping, and fill in the credentials path that
`tunnel create` printed:

```yaml
tunnel: flux-demo
credentials-file: C:\Users\willi\.cloudflared\<TUNNEL-UUID>.json
ingress:
  - hostname: bouncepulse.com
    service: http://127.0.0.1:4173
  - service: http_status:404
```

After that one-time setup, every deploy is two shells from the repository root:

```powershell
./deploy/serve.ps1        # shell 1: build + static origin on 127.0.0.1:4173
./deploy/tunnel.ps1       # shell 2: preflight + cloudflared tunnel run flux-demo
```

`tunnel.ps1` refuses to start unless `cloudflared`, the credentials, the
`config.yml`, and a responding local origin are all present; `-CheckOnly` runs
that preflight alone. It starts an existing tunnel and never creates one, logs
in, or changes DNS.

Run it in the foreground for the demo and stop it with Ctrl+C. Installing it as
a Windows service (`cloudflared service install`) is optional and needs an
elevated shell; the foreground form is the simpler default and is what the owner
will use. Verify with the `curl.exe -I https://bouncepulse.com/` check above.

The credentials file and the tunnel UUID stay on the host and out of Git; the
`.cloudflared` directory must never be committed.

### Ownership record

| Fact | Value |
| --- | --- |
| Connector host | `WYZWORKSTATION` |
| Keeps the host and processes running | William Zhang |
| Authoritative mapping | `%USERPROFILE%\.cloudflared\config.yml` on that host (not the Cloudflare dashboard) |
| Local origin target | `http://127.0.0.1:4173` (Node/Express, `web/server.mjs`) |
| Start/stop | `cloudflared tunnel run flux-demo` in the foreground; Ctrl+C to stop |

Only the static origin is routed. No public rule targets the FastAPI copilot on
port `8000`; API/SSE public routing must not be claimed until a second ingress
rule is added and verified.
