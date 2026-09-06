# 2WKG-352 integrated browser proof

Base: `53cfafc` (`feat(web): compose static explorer support panels`). This proof
tests the frozen combined frontend as a static synthetic application with a bounded OpenFreeMap basemap network dependency; it has no live Flux API, agent, or provider connection.

## Reproducible setup

```sh
cd web
npm ci
npx playwright install chromium # only when no system Chrome is installed
npm run test:e2e
```

The locked `@playwright/test` runner uses `PLAYWRIGHT_EXECUTABLE_PATH` when set,
then a locally installed Google Chrome when available, and otherwise its
installed Chromium. Browser tests are isolated in `web/e2e/`, outside the
existing `node --test` globs.

## Covered behavior

- Candidate selection updates the synthetic scenario, inspector, and static
  context without an API request.
- The static Ask panel remains explicitly unavailable, with its run trace and
  result card explaining that no live tool call or scene action occurred.
- Context editing persists through Ask collapse/reopen and scenario changes,
  with an opaque revision that advances for both an edit and a selection change.
- Candidate keyboard activation and modal focus behavior work, including Tab,
  Escape, and focus restoration.
- Desktop (1440x900), laptop (1024x768), and mobile (390x844) views have no
  horizontal document overflow after `document.fonts.ready`.
- The suite records requests and rejects a client `/ask` or `/api` request.

## Explicitly not satisfied by this proof

This base has no 3D renderer, source-backed geographic asset, live provider,
live SSE stream, external deployment URL, or accepted performance budget.
Consequently, this work does not claim live-agent behavior, 3D/geometry
coverage, performance criteria, or an external-demo rehearsal. Those remain
blocked by the corresponding prerequisite issues and artifacts.
