# 2WKG-87 freeze-readiness handoff — 2026-09-06

**Snapshot candidate:** `b26458a` (`origin/master`, merged into this branch on
2026-09-06). It supersedes the earlier candidate
`f8a3cfb2288…`, which was 63 commits stale by the time this handoff was written;
one SHA, and this is it. Every command below was re-run at this substrate. This
is a readiness receipt, not a tag or a request to stop parallel feature work.
Freeze only a reviewed, immutable commit after the open acceptance dependencies
below have completed.

## What can be rehearsed locally

The shipped desk is an offline static origin. It serves the checked-in
five-bus artifact `data/demo/bundle.json` from its built client and makes no
runtime API request. The artifact identifies itself as
`flux_checked_in_synthetic_fixture` version `1`, with fixture hash
`f5b2c271416b`; it is not a Minnesota, Texas, ERCOT, MISO, or actual
interconnection model.

From a clean checkout at the chosen freeze commit:

```powershell
npm --prefix web ci
npm --prefix web run build
npm --prefix web run test:rehearsal
$env:PORT = 4173
npm --prefix web run start
```

In a second PowerShell window, verify the actual built shell and client:

```powershell
curl.exe -I http://127.0.0.1:4173/
curl.exe -I http://127.0.0.1:4173/assets/app.js
```

Both responses must be `200`; the root is HTML and the asset is JavaScript.
Open the root in the presentation browser, select Baseline, Candidate A, and
Candidate B, then open **Data, units & limits**. Confirm that the synthetic
source, artifact hash, fixed four-hour assumption, and limitations are visible.
`/api/demo` is intentionally not a demo API. The shipped origin (`web/server.mjs`)
refuses every API-shaped path outright — `curl.exe -i http://127.0.0.1:4173/api/demo`
returns `503 Service Unavailable`, `content-type: text/plain`, body
`The static Flux demo does not serve API routes.` It does **not** fall back to the
SPA shell; only non-API unknown paths do. `web/test/static-demo.test.mjs` boots
`createApp()` from `web/server.mjs` and asserts that status, content type, and exact
body, so this row and the origin cannot drift apart again.

Stop the static origin with `Ctrl+C`. Do not start the optional FastAPI/Copilot
service for this static rehearsal or describe it as part of the judge route.

## Frozen file manifest

The "freeze" above is enforced, not merely listed. `gate/spec-authority` in
`.github/workflows/pr-gates.yml` re-hashes each file below on every pull request and
fails when a listed file changes without its hash being updated in this document in
the same PR. Changing a frozen file is therefore a deliberate, reviewable act rather
than a 3 a.m. commit nobody notices.

<!-- freeze-manifest:begin -->
```
7a59e2edc921aad536068bb62ab66c286e04aaea934b6115cccf6fa11378403a  data/demo/bundle.json
e8f0d2cf17cf548305a1e20924b86ae817972bcf060f35f99e3cf27c150d6cd7  README.md
99c2ba4cbddf71595a19abb10dad776873df60598bcc61e789f825723f6e8d5f  web/server.mjs
```
<!-- freeze-manifest:end -->

Regenerate after an intentional change with
`shasum -a 256 data/demo/bundle.json README.md web/server.mjs`
(`sha256sum` on Linux) and paste the result between the markers.

## Acceptance status at this snapshot

| 2WKG-87 acceptance item | State | Evidence or blocker |
| --- | --- | --- |
| README startup command | ready for local verification | `README.md` links to the clean-start command and local-startup runbook. |
| Source attribution and known limits | ready for local verification | README and in-app **Data, units & limits** identify the checked-in synthetic artifact and its limits. |
| Build and local static rehearsal | record the commands on the final freeze commit | The commands above exercise the built origin; no earlier result substitutes for a final-commit run. |
| Exact handoff rehearsal | blocked | Requires the final freeze SHA plus the presentation/browser check on that commit. |
| Public BouncePulse rehearsal | blocked | `bouncepulse.com` has a Cloudflare tunnel route with no live connector (HTTP 530 / error 1033 in the route inventory). Routing ownership and the external verification belong to 2WKG-86/2WKG-85. |
| Backup recording and screenshot | blocked | 2WKG-82 is still in progress. |

## Dependency boundary

Linear currently marks 2WKG-80, 2WKG-81, and 2WKG-77 done. 2WKG-82 and
2WKG-86 remain open, so 2WKG-87 cannot honestly be closed or called a complete
cold-start/public rehearsal. This document does not alter the tunnel, create a
deployment, test external health, add API tests, or relabel the synthetic
fixture as Minnesota.

For the current tunnel state and owner-only recovery procedure, use
[`static-origin-and-tunnel.md`](static-origin-and-tunnel.md). If the owner
restores the route, verify the public root serves the same built artifact before
calling the public rehearsal complete.
