# 2WKG-84 local static-origin readiness

**Checked:** 2026-09-06 (local-only)

This is local readiness evidence for the existing tunnel handoff. It does not
claim that `bouncepulse.com` is mapped to this origin or that a public demo is
available.

## Current artifact and origin

- Base revision: `489552e16cef6df0ec24cc6953ef37ddf852fa1c` (`origin/master`).
- Build and origin: `npm --prefix web run build`, then
  `PORT=4273 npm --prefix web run start`.
- The current static server serves `web/dist/`. The React bundle carries the
  checked-in synthetic fixture and has no runtime fetch or API requirement.
- The optional FastAPI application is a separate local process and was not
  started or exposed for this check.

## Evidence

From an isolated worktree, the following commands passed:

```text
npm --prefix web ci
npm --prefix web run test:static-demo   # 3 passed
npm --prefix web run test:rehearsal     # 2 passed
```

With the locally owned origin listening only for this check on port 4273:

```text
GET /                 -> 200 text/html
GET /assets/app.js    -> 200 text/javascript
GET /judge/rehearsal  -> 200 text/html, byte-identical SPA shell to /
GET /api/demo         -> 200 text/html, byte-identical SPA shell to /
```

Headless Chrome loaded both `/` and `/judge/rehearsal` after `networkidle` with
title `Flux | Resilience desk` and no console or page errors. The page visibly
labels itself as a bundled synthetic fixture with no API required. Selecting
the Candidate A card changed the rendered view to `NETWORK STATE · CANDIDATE
A` without browser errors. The local screenshot is retained only as ephemeral
verification evidence at `/tmp/2wkg-84-local-readiness.png`.

## Public deployment remains blocked

At the time of this check, `https://bouncepulse.com` returned Cloudflare HTTP
530. The checkout contains no Cloudflare connector configuration or credential,
and the connector host, target port, owner, and approved restart command are
unknown. Do not use the stale process on port 4188: it belongs to an old,
detached checkout with a retired JSON demo route.

Once the existing connector owner supplies the approved target, build this
current revision on that host, start this static origin at the approved port,
and verify that the public hostname serves the same static artifact before
performing the external-device checks in 2WKG-85.
