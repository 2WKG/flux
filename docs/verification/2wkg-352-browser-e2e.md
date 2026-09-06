# 2WKG-352 integrated browser proof — receipt

Recorded 2026-09-06 by the PR author's fixer on merge commit of
`joshuawangia/2wkg-352-run-browser-e2e-scene-performance-and-demo-rehearsal`
into `origin/master` (`8e56b6d`).

## Environment

| item | value |
| --- | --- |
| OS | macOS 26.6.2 (arm64) |
| node | v26.0.0 |
| `@playwright/test` | 1.63.0 (exact pin, no caret) |
| browser | bundled Chromium 153.0.8010.12 (`PLAYWRIGHT_EXECUTABLE_PATH=` empty) |
| origin under test | `node server.mjs` on `http://127.0.0.1:4173`, serving the real `dist/` |

Locally the config prefers an installed Google Chrome; CI (`gate/web-e2e`) and
this receipt use the bundled Chromium, which is why the run above sets
`PLAYWRIGHT_EXECUTABLE_PATH` to empty. `browserVersion` is recorded above so a
future run can tell the two apart.

## Reproducible setup

```sh
cd web
npm ci
npx playwright install chromium
npm run test:e2e
```

Browser tests live in `web/e2e/`, outside the `node --test` globs, and are run
in CI by `gate/web-e2e` in `.github/workflows/pr-gates.yml`.

## Recorded run

| command | result |
| --- | --- |
| `npm ci` | exit 0 |
| `npm run lint` | exit 0 |
| `npm run typecheck` | exit 0 |
| `npm run build` | exit 0 |
| `node --test $(find src test -name '*.test.mjs')` | 161 pass / 0 fail / 1 skipped |
| `npm run test:e2e` | **6 passed**, 5.1 s |

## Covered behavior

- Scenario selection (Baseline / Candidate A / Candidate B, by pointer and by
  keyboard) updates the scene heading and the inspector column.
- The screen's provenance is asserted on the machine token
  `main[data-source-status]`, written from `deriveSourceTruth(...)`, plus the
  derived nav summary and status pill — never on free-text copy alone. Any
  `source-backed` / `source-supported` / `source-screened` / "Minnesota
  coverage" string anywhere on the page fails the proof.
- The chat dock is collapsed by default and expands to its explicit
  "no Copilot endpoint" state; it never offers an answer.
- The data disclosure opens, names the artifact id and the scope sentence that
  disclaims Minnesota/Texas/ERCOT/MISO, and closes on Escape.
- Desktop (1440x900), laptop (1024x768) and mobile (390x844) have no horizontal
  document overflow after `document.fonts.ready`.
- **Network:** every request is asserted against a same-origin allowlist,
  installed in `test.beforeEach` so all six tests carry it. The one sanctioned
  exception is the Google Fonts stylesheet `web/src/styles.css:1` imports
  (`fonts.googleapis.com`, `fonts.gstatic.com`); it is named in the spec rather
  than hidden. No request to any `/ask` or `/api` path on any host is allowed.

## Mutation probes (all RED)

Each mutation was applied to source, rebuilt by the Playwright `webServer`, and
restored with `git checkout HEAD -- <file>`; `git status` was verified clean
after each.

| # | mutation | result |
| --- | --- | --- |
| P1 | `src/source-truth.ts` fixture branch returns `status: "source_supported"` | **RED** 4 failed / 2 passed |
| P2 | `src/main.tsx` status pill "not Minnesota data" → "Minnesota coverage" | **RED** 4 failed / 2 passed |
| P3 | `src/main.tsx` drops `data-source-status` from `<main>` | **RED** 4 failed / 2 passed |
| P4 | `src/main.tsx` adds `fetch("https://tiles.openfreemap.org/styles/dark")` | **RED** 6 failed |
| P5 | `src/main.tsx` adds `fetch("/api/demo")` | **RED** 6 failed |

P4 is the probe the previous `/ask|/api` denylist could not catch.

## Explicitly not satisfied by this proof

This base has no 3D renderer, source-backed geographic asset, live provider,
live SSE stream, external deployment URL, or accepted performance budget. No
timing, FPS, or LCP assertion exists here and none is claimed. 2WKG-352 stays
In Progress for those criteria.

## Known honesty gap this proof documents rather than fixes

The demo's own copy says "no API required", but `web/src/styles.css:1` imports a
Google Fonts stylesheet, so a first load does make three third-party requests.
The spec states that exception explicitly. Removing it (self-hosting the two
faces) is a product call for the shell's owner, not this proof's change.
