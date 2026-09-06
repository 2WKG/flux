# Static origin and tunnel inventory

Last checked: 2026-09-06, public edge re-measured the same day after the
connector came up (see *Update* below).

This is an inventory plus the recorded deployment command for the origin host.
It records checked-in configuration, host checks, and a public, read-only tunnel
check; it intentionally contains no credentials, connector IDs, tunnel UUIDs, or
private hostnames.

## Current status

> **Superseded later the same day.** A connector is now running and
> `bouncepulse.com` serves both the SPA and the FastAPI read paths; jump to
> *Update — the route went live later on 2026-09-06* for the measured state. The
> paragraph and table below record the earlier situation.

**No connector is installed, running, or credentialed on the origin host — but
a tunnel route may already exist in the Cloudflare account.** The earlier tasks
assumed a connector was configured here; it is not. What the host checks prove
is host-local absence only. The public check proves the opposite of absence at
the edge: `https://bouncepulse.com/` returns HTTP `530` with the body
`error code: 1033`, which is Cloudflare's *tunnel* error — the hostname is
already routed to a Tunnel that has no active connector. Checks on the intended
origin host (`WYZWORKSTATION`, user `willi`) on 2026-09-06:

| Check | Command | Result |
| --- | --- | --- |
| Public hostname | `Invoke-WebRequest -Uri https://bouncepulse.com/ -Method Head` | HTTP `530` |
| Public hostname body | `curl.exe https://bouncepulse.com/` | `error code: 1033` — Cloudflare Tunnel error: hostname routed to a tunnel with no active connector |
| DNS | `Resolve-DnsName bouncepulse.com -Type A` | `172.67.218.236`, `104.21.24.128` — Cloudflare proxy addresses |
| Connector binary | `Get-Command cloudflared` | not on `PATH` |
| Connector service | `Get-Service *cloudflare*` | none installed |
| Connector process | `Get-Process *cloudflared*` | none running |
| Connector credentials | `Test-Path $env:USERPROFILE\.cloudflared` | `False` |
| Tracked config | repository grep for `cloudflare`/`tunnel` | docs only; no config, service definition, or credential |

`bouncepulse.com` is proxied by Cloudflare (the zone exists). The host checks
prove only that no connector had ever been registered *from `WYZWORKSTATION`*;
they say nothing about the Cloudflare account. The `1033` body said the zone
still had a hostname-to-tunnel route, so **a tunnel may already exist in the
account and must be inspected before a new one is created**: after
`cloudflared tunnel login`, run `cloudflared tunnel list` and adopt the existing
tunnel rather than creating `flux-demo`, or the account ends up with two tunnels
competing for the same hostname.

### Update — the route went live later on 2026-09-06

The table above is the earlier measurement and is kept for the history. A
connector is now running and the hostname resolves to it. Measured from off the
origin host (`curl -s -o /dev/null -w '%{http_code} %{content_type}'`):

| URL | Result |
| --- | --- |
| `https://bouncepulse.com/` | `200 text/html` — the built SPA shell |
| `https://bouncepulse.com/api/demo` | `503 text/plain` — the static origin's own refusal, so `web/server.mjs` is what answers `/` |
| `https://bouncepulse.com/health` | `200 application/json`, body `{"ok":true,...}` from FastAPI |
| `https://bouncepulse.com/scenarios` | `503 application/json`, the shared `unavailable` envelope (`no_rows`) |
| `https://bouncepulse.com/layers/mn` | `404`-class `not_found` envelope from FastAPI |
| `https://bouncepulse.com/api/v1/grid/layers/mn` | `invalid_input` envelope from FastAPI |
| `https://bouncepulse.com/lines/top`, `/elements/critical`, `/predictions`, `/cascade` | FastAPI envelopes — **published, and wider than the allowlist below** |
| `GET https://bouncepulse.com/ask` | the SPA shell — not published at the edge |

So the deployed `config.yml` on the origin host is currently the *wide* rule:
it publishes four read paths (`/lines/top`, `/elements/critical`,
`/predictions`, `/cascade`) that `web/server.mjs`'s same-origin forward refuses,
and because the API rule precedes the static rule those four bypass that
allowlist entirely. `deploy/cloudflared/config.example.yml` in this repository is
now the narrow, derived rule (see *One allowlist, one place*). **The host's
`config.yml` has not been re-copied from the template**; until the owner does
that and restarts the connector, the live public surface is wider than the
checked-in one. This repository cannot verify or change the host's file.

## Static origin (authoritative)

| Item | Verified mapping |
| --- | --- |
| Process | Node/Express, started by `npm --prefix web run start` |
| Source/config | `web/server.mjs` is authoritative for origin routes and port loading; `web/package.json` defines the start/build scripts |
| Bind port | `PORT`, default `4173` (`server.mjs` calls `app.listen(port)`) |
| Bind address | Not explicitly configured in source; Node's default listen host is used. Do not assume a loopback or LAN bind without checking the connector host. |
| Static build | `web/dist/`, built by `npm --prefix web run build` |
| Demo data | `data/demo/bundle.json`, bundled into `web/dist/assets/app.js` at build time. The origin serves no API route (2WKG-300), so regenerating the bundle requires a rebuild. |
| Origin host | `WYZWORKSTATION` (this Windows 11 workstation) — the designated demo host; no other candidate host exists |
| Service owner | William Zhang, who keeps `WYZWORKSTATION` and the origin process running for the demo window |

The static server's only environment variable is `PORT`; no value is recorded
here. It loads it directly from the process environment when it starts, so there
is no checked-in environment file or wrapper that overrides it.

## Route ownership

| Host and path | Current owner | Local target | Status |
| --- | --- | --- | --- |
| local `GET /` and SPA client routes | `web/server.mjs` | `web/dist/` on a Node/Express static process | Verified; requires a built `web/dist/` |
| local `GET /api/demo` | No owner | — | Removed by 2WKG-300. `web/server.mjs` exposes no API route of its own, and since `0240db1` it refuses API-shaped paths outright rather than serving the shell: `GET /api/demo` returns `503`, `content-type: text/plain`, body `The static Flux demo does not serve API routes.` (verified 2026-09-06 against `node web/server.mjs`; pinned by `web/test/static-demo.test.mjs`). Only non-`/api` unknown paths fall back to the SPA shell. |
| `https://bouncepulse.com/` and static assets | Cloudflare public edge | Node/Express on `127.0.0.1:4173` | Connector must be running; the static rule is the fallback after the API read rule below |
| `https://bouncepulse.com/health` and read paths | Cloudflare public edge | `copilot.app:app` on `127.0.0.1:8000` | Live at the edge (measured 2026-09-06, see the update above), but routed by the host's own `config.yml`, **not** by anything in this repository. `deploy/cloudflared/config.example.yml` is a template: copying it is configured-but-not-routed until an operator installs it and restarts the connector. The template publishes exactly `/health`, `/layers/<name>`, `/api/v1/grid/layers/<layer>`, `/scenarios`, `/scenarios/<id>`; the live host currently publishes four more. Cloudflared filters paths, not methods, and FastAPI rejects unsupported methods |
| `https://bouncepulse.com/ask`, `/site-score`, `/compare` | No public tunnel owner | — | Explicitly excluded from ingress. `POST /ask` is forwarded by `web/server.mjs` on the local origin but is deliberately absent from the edge rule: cloudflared filters paths, not methods, so an `/ask` rule would publish the Copilot ask surface to the public internet. |
| `https://bouncepulse.com/lines/top`, `/elements/critical`, `/predictions`, `/cascade` | Cloudflare public edge (live), no template owner | `copilot.app:app` on `127.0.0.1:8000` | Reachable in public right now, but **not** in the checked-in template: they are outside `web/server.mjs`'s forward allowlist, and because the API ingress rule precedes the static rule they bypass it. The template no longer carries them. Re-copying the template narrows the live surface to match; that is the intended direction, and it is the owner's call. |

### One allowlist, one place

There are two programs that can publish an API path — the Cloudflare edge and
`web/server.mjs`'s same-origin forward — and cloudflared evaluates its API rule
*before* the static rule, so anything the edge admits never reaches `server.mjs`
at all. They therefore get one definition, not two: the `PROXIED` table in
`web/server.mjs` is the source, its GET half is exported as
`INGRESS_PATH_PATTERN`, and the `path:` line in
`deploy/cloudflared/config.example.yml` must be that string verbatim.
`web/test/ingress-allowlist.test.mjs` reads both files and fails when either
side drifts (it runs in `gate/web`). To change the public surface, change
`PROXIED` and regenerate:

```
node -e 'import("./web/server.mjs").then(m=>console.log(m.INGRESS_PATH_PATTERN))'
```

### What a routed path returns when the API is down

`deploy/tunnel.ps1` only guards connector *start*; it does not watch the API at
runtime. If the ingress rule is live and `127.0.0.1:8000` stops answering,
cloudflared returns **its own `502 Bad Gateway`** for `/health` and every routed
read path — not the shared `unavailable` envelope, and not the SPA shell. Do not
tell an operator to expect either of those. A `502` on a read path means the
FastAPI process is down behind a working connector; a `530` / `error code: 1033`
on any path means the connector itself is not running.

The FastAPI paths are implemented for local use but are not evidence of a
running API or a public mapping. `POST /ask` starts only the injected local SSE
transport; without an injected backend it reports unavailable and it does not
contact a provider. The specifications name `ANTHROPIC_API_KEY`,
`VOYAGE_API_KEY`, `DUCKDB_PATH`, and `COPILOT_MODEL`, but none is read by the
checked-in static server. The connector configuration recorded below reads no
environment variables; its mapping lives entirely in `config.yml` on the host.

## Minnesota demo scope

The Minnesota demonstration is a separate scope with its own planning authority
([`docs/specs/10-minnesota-demo.md`](../specs/10-minnesota-demo.md)). It does not
create a Minnesota fixture or topology, and it does not reuse the Texas
ACTIVSg2000 adapter. Its API/SSE routing contract is not yet implemented or
tunnel-mapped.

The Texas-first shared overview ([`docs/specs/00-overview.md`](../specs/00-overview.md))
remains the primary reference for the repository's routing, API, and tunnel
contract. Gate 0 is accepted
([`docs/design/minnesota-gate-0-approval.md`](../design/minnesota-gate-0-approval.md)),
which freezes an aggregate-mode boundary only; the network/topology decision gate
in `10-minnesota-demo.md` is still open. Either way, no Minnesota-specific route,
fixture, or tunnel mapping is claimed in this inventory.

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

A bare `200` on the asset proves nothing: `server.mjs` answers every unmatched
path with the SPA shell, so `curl.exe -I .../assets/DOES-NOT-EXIST.js` also
returns `200`. Check the fields that can actually fail — the content type and
the fixture hash carried inside the bundle:

```powershell
curl.exe -I http://127.0.0.1:4173/assets/app.js   # expect: Content-Type: text/javascript
curl.exe -s http://127.0.0.1:4173/assets/app.js | Select-String -SimpleMatch f5b2c271416b
# f5b2c271416b is the `fixtureHash` field of data/demo/bundle.json; re-read it
# from that file if the fixture is regenerated.
```

Verified 2026-09-06 on this tree: `/` → `200 text/html`, 360 bytes;
`/assets/app.js` → `200 text/javascript`, 1113568 bytes, containing the
`fixtureHash` `f5b2c271416b`; `/api/demo` and `/assets/DOES-NOT-EXIST.js` →
`200 text/html`, the same 360-byte shell, with no `fixtureHash` in the body.

After the connector owner establishes a mapping to this origin, verify the public
route without exposing configuration values:

```powershell
curl.exe -I https://bouncepulse.com/
```

It should return the same built HTML as the local root, not HTTP `530`.

## Which tunnel the account actually has (resolved 2026-09-06)

`cloudflared tunnel list` has since been run by the owner, which settles the
`1033` question above. The account holds three tunnels (UUIDs deliberately not
recorded here):

| Tunnel | Connections | Disposition |
| --- | --- | --- |
| `flux-demo` | none | Created 2026-09-06 for this demo. **Use this one.** |
| `pulse-prod` | none | Created 2026-05-02; the stale route behind the `1033`. Serving nothing. |
| `pairperks-pi` | 4 active | **Unrelated and live. Do not touch it.** |

So no tunnel needs adopting: the hostname's existing route points at
`pulse-prod`, which has had no connector for months. `--overwrite-dns` repoints
the apex to `flux-demo` and leaves `pulse-prod` idle; deleting it afterwards is
optional cleanup, not a deploy step. Every command below names `flux-demo` and
`bouncepulse.com` explicitly, so `pairperks-pi` is never affected.

## Deployment command (recorded, not yet run)

The checked-in scaffolding for these steps is [`deploy/`](../../deploy/README.md):
`deploy/serve.ps1` (build plus static origin), `deploy/tunnel.ps1` (preflight
plus connector), and `deploy/cloudflared/config.example.yml` (ingress template).

No connector exists on this host, so one must be attached from here. These are
the commands the owner runs on `WYZWORKSTATION`. **None of them has been run
yet** — `cloudflared tunnel login` opens a browser for Cloudflare account
authentication, so the owner must run this sequence interactively.

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel login                   # browser auth; select the bouncepulse.com zone
cloudflared tunnel list                    # done: see the table above; nothing to adopt
cloudflared tunnel create flux-demo        # done 2026-09-06; writes credentials to $env:USERPROFILE\.cloudflared
cloudflared tunnel route dns --overwrite-dns flux-demo bouncepulse.com
```

`--overwrite-dns` is required here, not optional. The apex already carries the
two proxied Cloudflare A records recorded above, and `cloudflared tunnel route
dns` defaults to `--overwrite-dns=false` (`cloudflared tunnel route dns --help`:
"Overwrites existing DNS records with this hostname (default: false)"). Without
the flag the step fails with a "record with that host already exists" error
instead of routing anything. Passing it replaces the existing apex records, so
confirm with the zone owner first.

Known failure branches for this sequence:

| Symptom | Cause | Exit |
| --- | --- | --- |
| `route dns` reports an existing record | the apex A records above | re-run with `--overwrite-dns`, after confirming with the zone owner |
| `tunnel login` offers the wrong zone | multiple zones on the account | re-run `cloudflared tunnel login` and pick `bouncepulse.com`; the cert it writes is per-zone |
| `tunnel list` already shows a tunnel for this hostname | the `1033` case | resolved: the stale route is `pulse-prod`, which serves nothing; overwrite it. Never repoint `pairperks-pi`. |
| public route returns `200` but a 360-byte shell for every path | `web/dist/` was never built | run `npm --prefix web run build` and re-check with the fixture-hash probe above |

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

The checked-in ingress template routes only `/health` and the API's read-path
surface to `127.0.0.1:8000`; the static rule remains the fallback for every
other path. Cloudflared selects by path rather than HTTP method, so FastAPI
still rejects an unsupported method at an otherwise routed read path. The
template intentionally does not publish `/ask`, `/site-score`, or `/compare`.
Start the API before the connector; `deploy/tunnel.ps1` preflights `/health`
and accepts its documented unavailable `503` response when no local database
is present.
