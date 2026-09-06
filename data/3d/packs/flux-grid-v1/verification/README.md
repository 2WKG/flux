# Evidence scope

The PR was prepared on master `8707bb92c158f868980f9cfef801efa8359fb360`, then
rebased onto `a34e59f` before publication. Its source catalog is the original
authorship snapshot, SHA-256
`f7ade755e6a61a634092a9d8437eb5976938057ad02fdd9fad056d39484f0f9c`.
The newer master adds `deliverables.sourceKit` documentation and source-kit
validation; all archetype IDs, transforms, footprints, connectors, status labels
and budgets are unchanged. The snapshot and binary hashes are not rewritten.
The runtime manifest's older `source_contract.local_revision` identifies that
authorship snapshot; it is not this PR's base revision.

`browser-report.json` is the frozen distribution's actual-browser receipt:
54 exact asset/LOD rows, per-source hashes, zero errors, and model-only pixel
comparisons with unchanged badges/text in both frames. It includes final
nuclear cooling-tower geometry, hospital crosses, all eighteen identity signs
at 24/32px, material isolation, axes and map pitch/heading. It used Chromium
ANGLE SwiftShader, deck 9.3.11 and MapLibre 6.7.0. It is not a production-placement
or hardware-performance claim; screenshots are in the downloadable archive.

`package-verification-report.json` records the distribution's original
standalone installer, which copies 120 runtime assets plus 4 integration modules.
The repository-specific installer deliberately copies only the 120 runtime
files, preserving the reviewed source modules in Git. Its fresh-checkout smoke
added 120 verified files, then added zero on the identical second install. A
deliberately different destination manifest was refused before writes; hashes
confirmed that every other installed file and package configuration stayed unchanged. The
entire generated directory is ignored. Node tests exercise checksum rejection,
source symlink refusal, valid @2x paths and traversal refusal.

Fresh-checkout checks:

- Locked `npm ci --ignore-scripts`, then `npm run typecheck` and `npm run build`
  passed without package, lockfile, target or application-entry changes.
- Eight focused Node tests passed for transforms, exact status acceptance,
  neutral/status material isolation, LOD/unavailable behavior, cache checksum
  and lifecycle, and publication installer boundaries.
- The complete frontend Node suite passed: 170 tests, zero failures/skips,
  including local HTTP/SSE servers and isolated headless Chrome. A first sandboxed
  run was blocked from binding localhost; the permitted rerun passed unchanged.
- Python 3.12 focused run: 57 passed (`tests/test_asset_archetypes.py` and the
  namespaced validator's 21 tests). Full external pack audit: 18/18 passed.
- All 15 new Python files passed Ruff check and format-check. An independent
  read-only Blender 5.2.1 in-memory comparison found all 54 generated variants
  identical in geometry, material assignments, connectors and shape metadata
  after the source portability/formatting changes. No models were regenerated
  into Git to perform that comparison.

The source port changes only the runtime's two own-property checks to their
ES2020-equivalent spelling. The asset overlay remains unmounted in the product;
accepted scene ownership, placement and geographic eligibility are unchanged.

The locked dependency install reported 13 existing audit advisories (4 moderate,
9 high). No automatic dependency upgrade or lockfile change was attempted in
this asset PR.
