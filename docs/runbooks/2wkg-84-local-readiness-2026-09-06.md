# 2WKG-84 local static-origin readiness — 2026-09-06

**Checked:** 2026-09-06, local only, on master
`489552e16cef6df0ec24cc6953ef37ddf852fa1c` (a fixed revision; not the moving
`origin/master` ref).

This is local readiness evidence for the existing tunnel handoff. It does not
claim that `bouncepulse.com` is mapped to this origin, or that a public demo is
available.

## Scope: this is not the Minnesota demo

The artifact verified here is the checked-in five-bus **synthetic** fixture
(`data/demo/bundle.json`), bundled into `web/dist/assets/app.js` at build time.
It represents no real state and no real grid. The Minnesota demo is **not**
served by this origin and is not part of this check; nothing below should be
read as Minnesota readiness.

## What this origin actually is

`web/server.mjs` serves `web/dist/` and **exposes no API route**. 2WKG-300
(`db53a83`) deleted `GET /api/demo`; the Express catch-all now returns the SPA
shell for every path. The optional FastAPI copilot is a separate process and was
not started or exposed for this check.

Runbook: [`local-startup.md`](local-startup.md). Origin/tunnel facts:
[`static-origin-and-tunnel.md`](static-origin-and-tunnel.md).

## The correction this receipt carries

Two documents claimed the deleted route still existed. Both are corrected in the
same commit as this receipt:

- `README.md` — "`web/server.mjs` still exposes `GET /api/demo` (validating
  `?scenario=`)" → the static origin returns the SPA shell for every path; there
  is no API route.
- `docs/runbooks/local-startup.md` — the Static demo section, the smoke block
  (which piped `/api/demo` into `json.load`), the quick-start checklist, and two
  troubleshooting rows.
- `docs/runbooks/static-origin-and-tunnel.md` carries the same stale claim and is
  being corrected separately in PR #167; it is deliberately untouched here.

## Evidence

Commands run in an isolated worktree, in this order:

```text
$ npm --prefix web ci                                            rc=0
$ npm --prefix web run build                                     rc=0
$ npm --prefix web run start &                                   pid saved; killed at the end
Flux is running at http://localhost:4173
```

Live responses from that origin (verbatim):

```text
$ curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://localhost:4173/
200 text/html; charset=utf-8
$ curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://localhost:4173/api/demo
200 text/html; charset=utf-8
$ curl -s http://localhost:4173/ | shasum -a 256
4c9dc8d4c80841e07b5fd7d0c2c63364d78193f1233299e307ff31cc2e7bccd5  -
$ curl -s http://localhost:4173/api/demo | shasum -a 256
4c9dc8d4c80841e07b5fd7d0c2c63364d78193f1233299e307ff31cc2e7bccd5  -
$ curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://localhost:4173/assets/app.js
200 text/javascript; charset=utf-8
$ grep -c "api/demo" web/dist/assets/app.js ; grep -c "fetch(" web/dist/assets/app.js
0 ; 0
```

The `/` and `/api/demo` digests are identical, which is the point: a `200` from
this origin proves the process is serving `web/dist/`, never that a route exists.

The old smoke command from the runbook, re-run against the same origin, is the
probe that fails today:

```text
$ curl -s http://localhost:4173/api/demo | uv run python -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='available'; print(d['selectedScenarioId'], d['data']['fixtureHash'])"
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

## Behavioural tests

The origin's contract is asserted by
[`web/test/rehearsal.test.mjs`](../../web/test/rehearsal.test.mjs), which starts
the real server and checks the shell, the referenced bundle, `/api/demo`, and
`POST /ask`. This receipt does not restate those assertions; run them:

```text
$ npm --prefix web run test:rehearsal
✔ the rehearsal artifact keeps displayed scenario balances internally consistent
✔ the rehearsal static origin serves the demo but never substitutes an API or SSE
ℹ tests 2  pass 2  fail 0
$ npm --prefix web run test:static-demo
ℹ tests 3  pass 3  fail 0
```

## Public deployment remains blocked

At the time of this check, `https://bouncepulse.com` returned Cloudflare HTTP
530. The checkout contains no Cloudflare connector configuration or credential,
and the connector host, target port, owner, and approved restart command are
unknown.

Once the connector owner supplies the approved target, build this revision on
that host, start this static origin at the approved port, and verify that the
public hostname serves the same static artifact before performing the
external-device checks in 2WKG-85.
