# Spec ↔ code reconciliation ledger

**What this is.** A standing record of every place the specs disagreed with what `master`
implements, what the code actually does, and how the disagreement was resolved. It is the
companion to the authority lattice in [`00-overview.md`](00-overview.md) §"Authority lattice
(D-0)": rule 1 there says executable source is the fact, and this file is where the exercise of
that rule is written down so nobody re-derives it.

**Baseline.** Every claim below was re-verified against `master` at
`056072b50406a4e27add24cfd4eccbfdd2b26079` (2026-09-06). Line numbers are from that commit.

**Scope.** This pass is documentation-only. Where a row's honest resolution is a change to code,
data, or tests, the row says so and names it as a follow-up instead of pretending a doc edit fixed
it.

---

## The ledger

| # | Disagreement | What the code does | Resolution in this pass |
|---|---|---|---|
| **D-0** | Authority: `CLAUDE.md:11-12` said the overview wins unqualified; `00-overview.md:15-17` scoped that win to four things (table name, column name, tool signature, scenario ID); `README.md:3-6`, `10-minnesota-demo.md:9-12` and `10-duckdb-contract.md:19-21` each claimed supersession | n/a — prose | One lattice, stated identically in `CLAUDE.md` and `00-overview.md`: **source > the 10-\* amendments inside what they supersede > `00-overview.md` > specs 01–09, design docs, runbooks.** |
| **D-0b** | GitHub org: `CLAUDE.md:4` and ten PR links in `10-minnesota-demo.md` said `Wyzard1004/flux` | live remote is `2WKG/flux` (`gh repo view Wyzard1004/flux` redirects to it) | Rewritten to `2WKG/flux` in `CLAUDE.md`, `10-minnesota-demo.md` (×10), `docs/runbooks/merge-gates.md` (×4), `CODEX_PROJECT_MEMORY.md`, `.agents/skills/flux-development/SKILL.md` (×3), `.github/bobvi-brief.md`. `@Wyzard1004` as a **username** (CODEOWNERS, merge-gates owner line) is correct and untouched. `configs/scenarios/examples/*.json` keeps its old URLs: those are recorded provenance receipts, and rewriting a receipt is not a doc fix. |
| **D-1** | Envelope shape: `envelopes.md:7-33` defines a failure-only HTTP envelope with four codes and no success envelope; `10-duckdb-contract.md:141-157` and `10-minnesota-demo.md:122-125` mandate `availability` / `next_step` / top-level `code` / `provenance` / `limitations` | **`envelopes.md`.** `FailureEnvelope` is `ConfigDict(extra="forbid", frozen=True)` (`copilot/api/envelope.py:35`, `:63-67`), so the rival fields *cannot* be emitted; `FailureCode` (`:24-29`) is exactly `unavailable`/`invalid_input`/`not_found`/`internal_error`; there is no `availability` field anywhere in `copilot/api/` | The 10-\* text is re-scoped to the **tool-result payload** it actually governs (renamed to "Artifact availability on a tool result"), with `envelopes.md` named as the HTTP authority and the crossing point spelled out: an unavailable payload condition leaves the boundary as the 503 failure envelope with the cause in `error.details.reason`. The re-scoped payload paragraphs are marked **intended shape, not current behaviour**: `grep -rn next_step copilot/ causal/` is 0 hits in both trees and no tool on `master` emits that flat shape (`causal/`'s `availability` is a nested `{"status", "unavailable_codes"}` object, `causal/validation.py:144-150`). One follow-up named, not done here: **FU-3** — implement or amend the tool-result availability payload. |
| **D-2** | `GET /layers/national_hex` when not built: `05-copilot.md:200` said 404 `{"not_built":true}`; `envelopes.md:38` "**Correction:** … a `not_found` 404 … not 503"; `06-frontend.md:83`, `:203` said 404 | **None of the three.** `layers.py:236-237` raises `_unavailable("not_built", …)` (`:98-112`) → `UnavailableError` → **503**, `status:"unavailable"`, `code:"unavailable"`, `details.reason:"not_built"`, `retry_after_s: 30` (`copilot/api/errors.py:76-83`). `BUILT_LAYERS = frozenset({"buses"})` (`layers.py:44`), so **11 of the 12 documented layers answer this way**, not just `national_hex` | All four sites corrected to 503 `unavailable` + `details.reason`; the wrong "Correction" note in `envelopes.md` deleted; the "11 of 12" fact added where it was missing. |
| **D-3** | Route inventory: `00-overview.md:265`, `:268`, `05-copilot.md:214`, `:216` and `06-frontend.md:19` require `POST /cascade` and `POST /predict`; `GET /scenarios/{scenario_id}` appears in no spec route table; `local-startup.md` says "nine registered local routes" and records a six-path OpenAPI dump | **Eleven routes**, regenerated here from `app.openapi()['paths']`: `/ask` (POST), `/cascade` (GET), `/compare` (POST), `/elements/critical` (GET), `/health` (GET), `/layers/{layer_name}` (GET), `/lines/top` (GET), `/predictions` (GET), `/scenarios` (GET), `/scenarios/{scenario_id}` (GET), `/site-score` (POST). Neither `POST /cascade` nor `POST /predict` exists in any form | `00-overview.md` §4.2 and `05-copilot.md` §Routes rewritten from the decorators + `copilot/test_read_route_contracts.py:95-250`; the two phantom routes removed rather than marked planned; `GET /scenarios/{id}` documented; `06-frontend.md` Inputs corrected; `local-startup.md` corrected to eleven and its OpenAPI list regenerated. |
| **D-3b** | `05-copilot.md:323` said `POST /site-score` and `POST /cascade` "return identical dicts to calling the Python functions directly (route is a pass-through)", contradicting `:229-233` ("persisted read … never computes a score") in the same file | **`:229-233`.** `POST /site-score` is a persisted read; `POST /cascade` does not exist | Acceptance criterion 4 rewritten to the persisted-read behaviour, with the removed claim quoted so the change is legible. |
| **D-4** | "Source supported" vs "Source-supported": the IA (`minnesota-demo-narrative-ia.md:225-226`) and every other module are hyphenated; `web/src/inspector/Inspector.tsx:8-9` is not, and `web/src/inspector/browser-harness.test.mjs:47-48`, `:55-56` pin the unhyphenated spelling | **Both spellings ship.** One screen would render the same status two ways | **No doc change: the docs are already right and the code is wrong.** Owned by U2 (`labels.ts`/`STATUS_COPY` consolidation), which must also update the two harness assertions. Listed here so the row is not lost. |
| **D-5** | Texas vs Minnesota: `00-overview.md:120-125`, `:288-298`, `06-frontend.md`, `05-copilot.md`, `texas-demo-narrative-ia.md`, `team-work-plan.md` describe Texas as the live path; `README.md:3-6` and `10-minnesota-demo.md:9-18` say Minnesota supersedes | **Texas.** `BUILT_LAYERS = frozenset({"buses"})` serves the Texas `buses` table; `SYNTHETIC_TOPOLOGY_LABEL = "synthetic (ACTIVSg2000)"` (`layers.py:59`, `scenarios.py:32`) is the only topology label any route emits; **no `mn_*` read route exists**; `pipelines/minnesota_*.py` exist but nothing HTTP-facing reads them | The Texas material is **kept** — it describes what runs — and banners were added to `05-copilot.md`, `06-frontend.md`, `texas-demo-narrative-ia.md`, `team-work-plan.md` plus notes in `00-overview.md` §2.3 and §4.2, all saying the same thing: *Minnesota supersedes this as plan, not as behaviour.* |
| **D-5b** | `minnesota-demo-narrative-ia.md:61-64` said `copilot/app.py` mounts "exactly five routers" and that "no `/ask` route exists on `master`"; `texas-demo-narrative-ia.md:201`, `:240` said `/ask` exists as a transport | **The Texas IA.** `copilot/app.py:68-75` mounts **eight** routers; `copilot/routes/ask.py:139` is `@router.post("/ask")`, transport-only — `AskBackend` is deployment-injected, nothing injects one, so the default stream is `lifecycle` then `unavailable` (`ask.py:76-86`) | The Minnesota IA paragraph corrected, keeping its real point (the dock is not live: an existing transport with no backend is not a live copilot). The Texas IA's own stale citation `copilot/app.py:71` corrected to `:75`. |
| **D-6** | Three 3D "tiers" | **Docs and validator agree** ✅ — `3d-asset-contract.md:160-174` and `scripts/validate_asset_source.py:14-27`, `:56-60`, `:126-141` name the same three delivery tiers and the same `unknown_asset_tier` refusal. The drift is that the browser has no tier concept: `web/src/performance/archetype-catalog.ts:27`, `:236` knows only LOD levels and carries an unrelated nine-value rejection vocabulary (`:65-74`) | *Delivery tier* (Python, on disk, 3 values) and *LOD level* (TypeScript, `budgets.lodLevels`, 3 values) disambiguated in `3d-asset-contract.md`. **Correction to the plan this pass was written from:** the `lodRule` regex parse (`archetype-catalog.ts:106-124`) is not an unnoticed hazard to file as a bug — it is deliberate and **fails closed** (`invalid_lod_rule` is a named rejection, never a default). The real, unstated fact is that `data/3d/asset-archetypes-v1.json` → `budgets.lodRule` is a **load-bearing string**: changing the numbers inside that sentence changes the budget. That is now stated in the Budgets section, which is a doc fix, not a follow-up. |
| **D-7** | Truth vocabularies: `labels.ts:5-6` says "there is no `source_backed` token anywhere in the vocabulary"; `minnesota-gate-0-approval.md:51-66` and `texas-demo-narrative-ia.md:77-82` freeze `source_backed·synthetic·unavailable` as a separate artifact axis; the inventory JSON adds a fourth value `illustrative` | **Both axes.** `TruthLabel` does not exist; the near-name is `SourceTruthLabel` (`ChatDock.tsx:45`). `web/src/ask/results/types.ts:73` (`geometry: "source_backed" \| "synthetic" \| "unavailable"`) is the **artifact axis, correctly spelled**. `illustrative` still ships in `data/sources/minnesota-accepted-artifact-inventory.json` and is the negative case in six pipeline tests. The binder **rejects** `source_supported` (`pipelines/tests/test_minnesota_asset_binding.py:53`, `:208-216`) | `00-overview.md` §4.3 names the two axes, their owners, and the consequence that `results/types.ts:73` must **not** be "fixed" to `source_supported`. Two follow-ups named, not done here: **FU-1** delete `illustrative` from the inventory JSON and its six tests (data + tests); **FU-2** reconcile the `source_backed` ↔ `source_supported` binder seam — a behavioural bug, not a naming one. |
| **D-8** | `request_failed` sub-causes: no document enumerates any | `web/src/failure-states/types.ts:24-35` enumerates **eleven** `FailureKind`s, bound at `:42-54` — seven collapse to `request_failed`, `unavailable` maps to itself, `loading`/`empty`/`partial` map to `null`. The doc-enumerated reason vocabularies (7 layer reasons at `layers.py:98-112`, ~20 route reasons in spec 05) are all `unavailable`. The SSE eight-code terminal set agrees doc↔code ✅ | `00-overview.md` §4.4 documents `request_failed` as a **display token with an open cause set**, and names the three layers (closed four-code `FailureCode` / server `details.reason` / browser `FailureKind`). One rule is left undecided — **OQ-1**. |
| **D-9** | Four work graphs: `swarm-plan.md` U1–U9 (one key: 2WKG-412 at `:23`), `team-work-plan.md`'s two waves, `10-minnesota-demo.md:171-190` MN01–MN11, and `:200-259`'s numbered list | n/a — prose. The only enforced tracker binding is `gate/linear-key` (`.github/workflows/pr-gates.yml`), which reads the branch name or PR title | Linear declared authoritative; the three prose graphs bannered **historical**. The tracker's own split is **OQ-2**. |

---

## Open questions — decisions, not facts

These two are genuinely product/owner calls. Both options are stated; neither is chosen here, and
nothing above depends on the choice.

### OQ-1 — Is "a terminal-less stream is `request_failed`" normative?

`docs/design/texas-demo-narrative-ia.md:98` states, in exactly one place and in no other document:

> a stream that ended without a terminal event is `request_failed`, not `unavailable`

**Nothing implements it.** There is no such rule in `copilot/sse.py`,
`web/src/chat/ChatDock.tsx`, or `web/src/failure-states/adapters.ts`; `ChatDock.tsx:121-122`
handles a missing terminal as a rendered sentence ("The server did not supply a terminal error
event…"), not as a status.

- **Option A — normative.** Keep the sentence, and it becomes work: a browser rule that maps
  "stream closed with no `done` and no `error`" to `FailureKind: "failed"` → `request_failed`, plus
  a test that goes red without it. Cost: one adapter change and one test. Benefit: the UI asserts a
  machine token instead of prose in the one case where the server broke its own contract
  (`sse-event-schema.md`: exactly one terminal, never neither).
- **Option B — not normative.** Delete the sentence. The existing behaviour (a rendered
  contract-break message with no status token) is then the documented behaviour. Cost: the screen
  has one state that carries no machine token, so a browser proof cannot pin it.

### OQ-2 — What happens to the Texas/Minnesota twin projects inside Linear?

`gate/linear-key` makes Linear the enforced tracker, and the three prose graphs are now bannered
historical. What remains undecided is inside Linear: the merged web PRs were filed under **two twin
projects**, so several Minnesota issues sit in Backlog describing work already merged under a Texas
twin's key (for example the inspector, chat dock, result cards, run trace, and failure states each
have a Done Texas issue and a Backlog Minnesota issue).

- **Option A — reconcile the twins in Linear.** Close or merge each Minnesota twin against the
  Texas key that actually landed, and keep one project. Cost: a tracker pass by someone with the
  history. Benefit: "what is left" becomes readable, and `2WKG-355`'s Gate-1 milestone closes on
  real children.
- **Option B — leave the twins and pick per PR.** Keep both projects and let each PR carry whatever
  key its author picks. Cost: the Gate-1 milestone can never be trusted as a completion signal, and
  every future reconciliation gets more expensive.

Reconciling a tracker is an owner decision, not a code unit; it is out of scope for this pass by
construction.

---

## Decisions taken on 2026-09-06 (2WKG-355)

Two of the open questions above were product calls, not facts, and Joshua made them. They are
recorded here because each one **retired a landed assertion**, and a retired assertion is only
honest when what replaced it is written down.

### D-10 — the one App is server-backed

*Decision:* "demo will be online". The one App composes the landed panels (`ChatDock`,
`RunTrace`, `ResultCards`, `FailureState`, `Inspector`, `LayerControls` and the per-layer legend)
and the physical-inventory map, and feeds them from real routes: `GET /health`,
`GET /scenarios/{scenario_id}`, `GET /layers/{name}` through `src/scene/minnesota-adapter.ts`,
`POST /ask` as SSE, and `GET /api/v1/grid/layers/{layer}` (2WKG-89). The bundled synthetic
scenario explorer is unchanged and still needs no API to paint, which is what its
"no API required for this scene" claim is now scoped to.

*What was retired:* `web/test/static-demo.test.mjs` asserted
`assert.doesNotMatch(source, /\bfetch\s*\(/)` and the same over the built bundle. That rule made
an offline demo and a live evidence surface mutually exclusive in one esbuild entry — the whole
`web/src/data/` layer exists to call `fetch` — so a server-backed App could not satisfy it.
`00-overview.md` wins over a test's implied product claim, and the decision is the product claim.

*What replaced it,* in the same file, so the file stays worth running:

1. **No absolute URL is a request target anywhere in the bundle**, and the served shell's CSP is
   `connect-src 'self'`. `web/e2e/static-explorer.spec.ts` asserts the browser-side half as
   **zero off-origin requests**, with no sanctioned exception (it previously carried two, for the
   Google Fonts hosts).
2. **Every data path, driven against a transport that cannot connect, produces a named
   `unavailable`/`request_failed` outcome with a reason, and never a ready one.** That is the
   assertion a "fake-fine" offline state cannot pass, and it is the one the `fetch(` denial was
   standing in for.

*Consequences recorded elsewhere:* `05-copilot.md` §Routes gains a browser-consumer note;
`STACK-LOCK.md` gains the `FLUX_API_ORIGIN` seam; `web/test/renderer-artifact.test.mjs`'s control
for the conditional MapLibre copy moved from the demo build (which now does bundle MapLibre) to a
purpose-built probe entry.

*Not decided here:* whether `POST /ask` gets a backend injected. It does not have one
(`ask.py:76-86`, D-5b), so the dock's collapsed label stays "Not available in this offline build"
until a probe proves otherwise, and its Send button stays disabled.

### D-12 — `script-src` stays `'self'`; the `'wasm-unsafe-eval'` relaxation is dropped

*What happened:* the 2WKG-475 branch shipped `script-src 'self' 'wasm-unsafe-eval'` in
`web/index.html` and `web/server.mjs`, where D-10's policy is `script-src 'self'`. It arrived with
no comment and no entry here, and `web/test/renderer-artifact.test.mjs` and
`web/test/server.test.mjs` were widened to admit the new token -- so the CSP assertion those two
files exist to make was relaxed without a recorded reason.

*What was checked, not assumed.* `WebAssembly` appears five times in the built
`dist/assets/app.js`, and every one is inside loaders.gl, pulled in by deck.gl:
three in the meshoptimizer decoder (`WebAssembly.validate`, `WebAssembly.instantiate`, and the
same call inside the source string it posts to its worker) and two in Draco's
`typeof WebAssembly === "object"` decoder-type probe. Neither decoder runs unless a glTF asset
declares `KHR_draco_mesh_compression` or `EXT_meshopt_compression`, which only
`FluxAssetLayer`'s `ScenegraphLayer` could request -- and this repository publishes no `.glb` at
all: `data/3d/packs/flux-grid-v1/manifest.json` records
`"completion": "source_only_binaries_unpublished"`.

*The probe.* `script-src 'self'` was put back, `npm run build` re-run, and the Playwright suite
driven against the real `server.mjs` with a `securitypolicyviolation` listener installed on the
page. The primary route reported `CSP-VIOLATIONS: []` and `PAGE-ERRORS: []`, and the whole
suite stayed green (4 passed, 1 live-only skip) -- the same result it gives with the relaxation
present. Nothing that ships today exercises it.

*Decision:* drop it. D-10's `script-src 'self'` stands, and both test files go back to the
narrower allowlist. If a Draco- or meshopt-compressed `.glb` is ever published into
`data/3d/packs/`, `'wasm-unsafe-eval'` must be added back in the same commit that publishes it,
with the browser proof that it is needed -- not before.

### D-11 — the webfonts are dropped for a system stack

*Decision:* "use your own system font according to style guide". `web/src/styles.css:1`'s
`@import url('https://fonts.googleapis.com/css2?family=DM+Mono&family=Manrope…')` was the only
off-origin dependency in the built artifact, and it made three third-party requests on a page that
advertised itself as offline.

*Resolution:* no prose style guide in `docs/design/` names a font stack. The repo's one checked-in
visual guide does: `docs/design/texas-workspace-prototype.html:9` sets
`font: 14px/1.4 ui-sans-serif, system-ui, sans-serif` and `:17` sets
`font-family: ui-monospace, monospace`. Those two are used verbatim, as `--font-sans` and
`--font-mono` in `:root`. `Manrope` and `'DM Mono'` appear nowhere in the sheet, and
`web/test/stylesheet-unification.test.mjs` asserts the sheet declares no font family it does not
load, plus `@font-face` and off-origin `@import`/`url()` absence.

*Also landed with it (2WKG-366):* the four component stylesheets
(`chat/chat.css`, `ask/results/result-cards.css`, `layers/layer-controls.css`,
`renderer/renderer.css`) are merged into the single physical file `web/src/styles.css`, which is
what `viewport-shell.test.mjs` reads. Five rival panel backgrounds, five rival borders and four
rival inks collapse onto `:root` tokens. The one remaining `@import` is MapLibre's own vendor
sheet, a local package file inlined by esbuild at build time — not a URL.

---

## Verification — the retired-string check

A doc-only change cannot be mutation-tested against a runtime, so the check is a **link-and-quote
scan**: every string this pass retired must be absent, and every fact it asserts must still match
the code. The scan is failable by construction — reintroduce any one retired string and the command
that owns it prints a hit and exits non-zero.

Run from the repository root. `X="--exclude=spec-code-reconciliation.md"` keeps this file's own
description of a retired string from matching it.

```sh
X=--exclude=spec-code-reconciliation.md

# 1. D-3 — the two routes that do not exist must not appear as route-table entries.
! grep -rnE '^\| `POST /(cascade|predict)`|^POST /(cascade|predict) ' $X docs/

# 2. D-2 — no doc may claim national_hex answers 404 or a bare {"not_built": true} body.
! grep -rnE 'returns 404 .\{"not_built"|404 \(`not_built`\) hides|`/layers/national_hex` 404s|\*\*Correction:\*\*' $X docs/

# 3. D-0b — the repo path is 2WKG/flux (the @Wyzard1004 *username* is correct and stays).
! grep -rn 'Wyzard1004/flux' $X docs/ CLAUDE.md CODEX_PROJECT_MEMORY.md .agents/ .github/

# 4. D-5b — the router count and the /ask denial.
! grep -rnE 'exactly five routers|no `/ask` route exist|copilot/app\.py:71' $X docs/

# 5. D-3b — the pass-through claim is gone from the acceptance list.
! grep -rn 'route is a pass-through; tested by equality' $X docs/

# 6. D-3 — the stale route count in the runbook.
! grep -rn 'nine registered local routes' $X docs/

# 7. Positive checks: the code still says what the docs now claim.
grep -q 'http_status = 503' copilot/api/errors.py                 # D-2
grep -q 'extra="forbid"' copilot/api/envelope.py                  # D-1
test "$(grep -c 'app.include_router' copilot/app.py)" = 8         # D-5b
uv run --extra dev python -c "from copilot.app import app; assert len(app.openapi()['paths']) == 11"   # D-3
```

**Proof the scan can fail.** Reintroducing one retired string makes exactly one command red and
names the file:

```
$ printf '\n| `POST /predict` | {county_fips} | predict_outage dict |\n' >> docs/specs/05-copilot.md
$ grep -rnE '^\| `POST /(cascade|predict)`|^POST /(cascade|predict) ' $X docs/
docs/specs/05-copilot.md:397:| `POST /predict` | {county_fips} | predict_outage dict |
$ git checkout HEAD -- docs/specs/05-copilot.md   # restored
```

Each numbered command is tied to the ledger row named beside it. A row whose command cannot be made
to fail is not a check — if you add a row, add its command.
