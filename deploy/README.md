# Deploying the demo to bouncepulse.com

Origin host: `WYZWORKSTATION`. Owner: William Zhang, who keeps the host and both
processes running for the demo window.

The full inventory, verified facts, and the one-time setup sequence are in
[`docs/runbooks/static-origin-and-tunnel.md`](../docs/runbooks/static-origin-and-tunnel.md).
This directory is the checked-in scaffolding that sequence uses.

The tunnel maps only the API's health and read-path surface to `127.0.0.1:8000`.
It does not publish `/ask`, `/site-score`, or `/compare`; Cloudflared matches
paths rather than HTTP methods, so FastAPI remains responsible for rejecting an
unsupported method on a routed read path.

| File | Purpose |
| --- | --- |
| `serve.ps1` | Builds `web/dist/` and serves it at `http://127.0.0.1:4173` |
| `tunnel.ps1` | Preflights the host, then runs the Cloudflare connector |
| `cloudflared/config.example.yml` | Ingress template to copy to `%USERPROFILE%\.cloudflared\config.yml` |

## One-time setup (owner, interactive)

Not yet done — no connector exists on this host. `cloudflared tunnel login`
opens a browser, so only the Cloudflare account owner can run this:

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel login                   # select the bouncepulse.com zone
cloudflared tunnel list                    # done: nothing to adopt, see the runbook
cloudflared tunnel create flux-demo        # done 2026-09-06; prints the credentials file path
cloudflared tunnel route dns --overwrite-dns flux-demo bouncepulse.com
copy deploy\cloudflared\config.example.yml $env:USERPROFILE\.cloudflared\config.yml
# then edit that copy: set credentials-file to the path just printed
```

`https://bouncepulse.com/` answers HTTP `530` with the body `error code: 1033` —
a Cloudflare *Tunnel* error meaning the hostname is already routed to a tunnel
with no live connector. `tunnel list` (run 2026-09-06) identified that as
`pulse-prod`, which has no connections and serves nothing, so there is nothing
worth adopting and `flux-demo` is the tunnel to use. The account's third tunnel,
`pairperks-pi`, is unrelated and live — never repoint it. `route dns`
defaults to `--overwrite-dns=false` and the apex already carries two proxied A
records, so without the flag that step fails with a "record already exists"
error. See
[`docs/runbooks/static-origin-and-tunnel.md`](../docs/runbooks/static-origin-and-tunnel.md)
for the evidence and the failure branches.

## Every deploy

Three shells from the repository root:

```powershell
./deploy/serve.ps1        # shell 1: build + static origin on :4173
uv run uvicorn copilot.app:app --port 8000 # shell 2: API health + read paths
./deploy/tunnel.ps1       # shell 3: preflight + connector
```

`./deploy/serve.ps1 -SkipBuild` reuses an existing `web/dist/`.
`./deploy/tunnel.ps1 -CheckOnly` runs the preflight without starting anything.

Verify the public route:

```powershell
curl.exe -I https://bouncepulse.com/
```

Expect `200` and the same built HTML as `http://127.0.0.1:4173/`. HTTP `530`
with body `error code: 1033` means the hostname is routed to a tunnel but no
connector is running; `502` means the connector is up but the origin is not.
A `200` alone is not proof the demo is served — the origin answers every
unmatched path with the 360-byte SPA shell, so also check that
`https://bouncepulse.com/assets/app.js` comes back as `text/javascript`.

The configured API read routes reach FastAPI, not the SPA shell:

```powershell
curl.exe -i https://bouncepulse.com/health
curl.exe -i https://bouncepulse.com/scenarios
```

`/health` returns `200` with a prepared database or its documented `503`
unavailable envelope without one. The same is true for read routes whose
required artifact is unavailable. `/ask`, `/site-score`, and `/compare` are
not public tunnel routes.

## Boundaries

- The FastAPI ingress is limited by path to `/health` and its read routes.
  `/ask`, `/site-score`, and `/compare` remain unrouted. Cloudflared does not
  filter HTTP methods; FastAPI rejects unsupported methods on the routed paths.
- Credentials, the tunnel UUID, and the filled-in `config.yml` live on the host
  and are gitignored. Never commit them.
- `tunnel.ps1` starts an existing tunnel. It never creates one, logs in, or
  changes DNS.
