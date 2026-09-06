# Deploying the demo to bouncepulse.com

Origin host: `WYZWORKSTATION`. Owner: William Zhang, who keeps the host and both
processes running for the demo window.

The full inventory, verified facts, and the one-time setup sequence are in
[`docs/runbooks/static-origin-and-tunnel.md`](../docs/runbooks/static-origin-and-tunnel.md).
This directory is the checked-in scaffolding that sequence uses.

| File | Purpose |
| --- | --- |
| `serve.ps1` | Builds `web/dist/` and serves it at `http://127.0.0.1:4173` |
| `tunnel.ps1` | Preflights the host, then runs the Cloudflare connector |
| `cloudflared/config.example.yml` | Ingress template to copy to `%USERPROFILE%\.cloudflared\config.yml` |

## One-time setup (owner, interactive)

Not yet done — no tunnel exists yet. `cloudflared tunnel login` opens a browser,
so only the Cloudflare account owner can run this:

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel login                   # select the bouncepulse.com zone
cloudflared tunnel create flux-demo        # prints the credentials file path
cloudflared tunnel route dns flux-demo bouncepulse.com
copy deploy\cloudflared\config.example.yml $env:USERPROFILE\.cloudflared\config.yml
# then edit that copy: set credentials-file to the path just printed
```

## Every deploy

Two shells from the repository root:

```powershell
./deploy/serve.ps1        # shell 1: build + static origin on :4173
./deploy/tunnel.ps1       # shell 2: preflight + connector
```

`./deploy/serve.ps1 -SkipBuild` reuses an existing `web/dist/`.
`./deploy/tunnel.ps1 -CheckOnly` runs the preflight without starting anything.

Verify the public route:

```powershell
curl.exe -I https://bouncepulse.com/
```

Expect `200` and the same built HTML as `http://127.0.0.1:4173/`. HTTP `530`
means no connector is running; `502` means the connector is up but the origin
is not.

## Boundaries

- Only the static origin is routed. The FastAPI copilot on port `8000` has no
  ingress rule; do not add one without verifying that service first.
- Credentials, the tunnel UUID, and the filled-in `config.yml` live on the host
  and are gitignored. Never commit them.
- `tunnel.ps1` starts an existing tunnel. It never creates one, logs in, or
  changes DNS.
