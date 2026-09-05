---
title: "flux — BUILD target (converging-swarm Variant B)"
status: draft
owner: flux hackathon team
created: 2026-09-05
updated: 2026-09-05
related:
  - "[[../specs/00-overview]]"
  - "[[swarm-plan]]"
---

# Target: flux (BUILD driver) — v1

One converging-swarm BUILD spec that drives the ten specs in `docs/specs/` to a **frozen,
machine-checkable gate set** for the hackathon demo. Binary gates, build-to-green driver.
Format and discipline are borrowed from Buckeye's converging-swarm spec standard (five
elements, frozen fitness, anti-goals, loud-escalation done condition) and its
swarm-honesty-orchestrator (independent analyst gates every PR). REQUIRED READING before any
unit: `docs/specs/README.md` → `00-overview.md` (contract + amendments A1–A7) → the unit's spec.

## Intent
A judge who distrusts dashboards clicks one storm, one substation, one site, and one question,
and every number on screen traces to a physics run, a trained model, or a cited regulation.
The real-world consequence: the team can defend every claim in the 5-minute demo under
hostile questioning from defense, energy-policy, and investor judges, because nothing on
screen was typed in by a person or invented by a language model.

## Bold end-state
`flux` at the integration branch head builds green on a clean clone and passes every gate
below: Texas-first grid twin (ACTIVSg2000) with real geography, a LightGBM county outage model
validated on held-out Winter Storm Uri, a deterministic cascade simulator whose critical-load
loss is county-attributed, a siting engine producing two scores per candidate with a
persisted Uri counterfactual for the #1 site, a line-upgrade ranking screen, a copilot that
narrates only from tool results and citations, and a deck.gl front end that plays the six
demo beats from `00-overview.md` §demo. **NOT in scope:** national 82k-bus topology (scale
slide only), real CEII utility data, Grid2Op operator agent, Idea 2 (backup spec, separate
target if entered).

## Joshua-gated decisions (configured around, never resolved by the swarm)
1. Whether Idea 2 is entered as a second pitch (spawns a separate target).
2. Anthropic API key and spend cap for the copilot (`ANTHROPIC_API_KEY`, never committed).
3. Which DoD installation is named on stage (spec 04 picks by cascade evidence; the team
   confirms it is public-boundary data and appropriate to say aloud).
4. Any claim in the pitch the fact-check ledgers (`docs/specs/verification/`) left
   `[UNVERIFIED]` — say it or cut it; the swarm never "verifies" a pitch claim by asserting it.

## Global gate set (FROZEN measurement — `scope.immutable`)
`scope.immutable` = the entire `gates/` tree (`gates/__tests__/`, `gates/fixtures/`,
`gates/thresholds.yaml`), `docs/specs/*.md` contract sections and amendments, and this table.
All of it lands in **U0** and freezes at protected tag `gate-baseline-u0`. A fix-unit that
edits a gate command, widens an assertion, or relaxes a threshold is a scope-dodge BLOCK.
All gate commands are `[SPECULATIVE-UNTIL-U0]`; U0 flips them to `[PROVEN]` in
`gates/freeze-manifest.json`. Gates run from the repo root with `uv run` (Python 3.12) and
`pnpm --dir web` (Node 22+). `SERIAL`: G_CASCADE, G_SITING (CPU-bound, share the twin);
everything else may run concurrently.

| id | command (real entrypoint) | GREEN predicate (+ load-bearing negative control) |
|---|---|---|
| **G_ENV** | `uv sync --frozen && uv run python -m gates.env && pnpm --dir web install --frozen-lockfile` | `uv.lock` and `web/pnpm-lock.yaml` unchanged by install; `pandapower`, `lightgbm`, `duckdb`, `anthropic`, `matpower`, `matpowercaseframes` import; LightGBM loads `libomp` (fails loud otherwise). **Neg-control:** deleting `matpowercaseframes` from the env reddens (twin loader depends on it). |
| **G_INGEST** | `uv run python -m gates.ingest` (spec 01 P0 sources only) | `data/duck/grid.duckdb` has every contract table from `00-overview.md` with the exact column set (schema diffed against `gates/schema.yaml`); `buses` = 2000 rows, each with non-null `lon/lat` from the CURRENT-version `ACTIVSg2000.aux` (`coord_source='tamu_aux'`; the June-2016 xlsx is a different case version and must not be the source) inside the Texas bbox, and a `county_fips` that exists in `counties`; `lines` = 2359; `eaglei_outages` covers `2021-02-13..2021-02-20` for ≥200 Texas counties; `weather_hourly` covers the same window for every Texas county; `ba_load_hourly` for `ERCO` covers all 168 Uri hours; ingest is idempotent (second run leaves row counts and a content hash unchanged). **Neg-controls:** a fixture bus row with lon/lat outside Texas reddens; a fixture EAGLE-I CSV with a renamed column reddens the loader (no silent column guessing); a fixture AUX whose bus ids overlap the pip case by < 100 % reddens (catches the June-2016 version mix-up). |
| **G_TWIN** | `uv run python -m gates.twin` | `twin.build.build_base_net()` returns 2000 buses / 2359 lines / 847 impedance branches (transformers) / 484 gen + 59 sgen + 1 ext_grid / 1125 loads / 67,109 ± 1 MW load; `rundcpp` converges; max base-case line loading < 100 % AND the loop's own transformer loading (from `res_impedance` p/sn_mva) < 100 %; `scale_loads(hour)` reproduces `ba_load_hourly.demand_mw` for `ERCO` within 0.5 % for every Uri hour. **Neg-control:** a fixture with one `lines.rate_a_mw` set to 0 must produce a base-case overload (proves ratings are read from the table, not the `.m` file). |
| **G_OUTAGE** | `uv run python -m gates.outage` | model trained with Uri/Beryl/Helene held out (asserted from the persisted `outage_eval.split_manifest`); on `uri_2021`: `hit_rate_top20 ≥ 0.60`, `peak_statewide_err ≤ 35 %`, Brier ≤ the logistic heuristic's Brier (model must beat its own fallback); `predict_outage("48453","uri_2021",72)` returns `p_out ∈ [0,1]`, `customers_at_risk ≥ 0`, `driver ∈ {wind,ice,wildfire,heat,other}`. **Neg-controls:** shuffling the label column in a fixture training set must drop `hit_rate_top20` below 0.30 (the model learns from labels, not leakage); a feature table containing any column dated after the prediction window reddens (leakage guard). |
| **G_CASCADE** | `uv run python -m gates.cascade` (SERIAL) | `run_scenario("uri_2021", seed=0)` completes 168 h in ≤ 120 s with plain pandapower `rundcpp` (warm solve 9–14 ms; lightsim2grid is incompatible with this case and out of scope); re-running with the same seed yields byte-identical `cascade_runs` rows (determinism); every tripped element id exists in `lines`/`gens`; `lost_load_mw` at every hour ≤ total scaled load; `counties_dark_json` sums to `lost_load_mw` ± 1 MW; at least one `critical_loads_lost_json` entry is a `dod` kind during Uri (the demo beat exists in data). **Neg-controls:** raising all `rate_a_mw` ×100 in a fixture must produce zero overload trips (trips come from ratings); forcing `line_failure_prob = 0` must produce zero weather trips; a fixture that overloads one transformer (impedance branch) only must still produce a trip (proves the transformer path is wired). |
| **G_SITING** | `uv run python -m gates.siting` (SERIAL) | `site_candidates` has ≥ 20 Texas rows across ≥ 3 `kind` values with a `bus_id` within 50 km; every `site_scores` row has `safety_flags_json` naming all 12 criteria with `{value, threshold, source}`; `grid_value_score` for the #1 site is computed from a with-unit vs baseline pair at the same seed (asserted via run provenance); the persisted counterfactual row `uri_2021-s0-cf-<site_id>-1000` exists with `counterfactual_site_id` set and `lost_load_mw` ≤ baseline at every hour; `regulatory_path` ∈ the six labels. **Neg-controls:** a fixture site inside a 20-mile radius with population density > 500/sq mi must be `excluded`; setting `unit_mw = 0` must yield `lol_reduction_mwh = 0`. |
| **G_LINES** | `uv run python -m gates.lines` | `line_upgrade_scores` has a row for every ≥ 138 kV line; `dlr_uplift_mw` derives from the IEEE 738 module (a fixture with wind = 0.6 m/s and 40 °C must yield ≤ static rating; wind = 5 m/s and 10 °C must yield > static); `mw_per_musd` = uplift / cost within rounding; `ferc_screen_pass` only where `congestion_usd_yr` > threshold in `gates/thresholds.yaml` AND wind criterion; `top_lines("ERCOT","any",10)` returns 10 rows sorted desc. **Neg-control:** zeroing `congestion_usd_yr` must set `ferc_screen_pass = false` for every line. |
| **G_COPILOT** | `uv run python -m gates.copilot` (spawns the FastAPI app on a free port; real HTTP) | `GET /health` 200; `POST /ask` streams SSE events `text|tool_call|tool_result|citation|done`; for each of the two demo questions the trace contains ≥ 1 tool call and every number in the final text appears in some `tool_result` payload (the post-answer verifier from spec 05 runs in-gate); every regulatory sentence carries a `citation` event whose chunk text contains the cited phrase; `sql` tool rejects non-SELECT and > 1000-row results; a question with tools disabled yields a refusal, not an answer. LLM calls go to the real Anthropic API when `ANTHROPIC_API_KEY` is set, else the gate reports **SKIPPED-ENV loudly** (never green) and convergence requires Joshua's ack. **Neg-controls:** a fixture tool that returns a number absent from the model's text must be flagged by the verifier; disabling the verifier must redden the gate (proves it is wired). |
| **G_WEB** | `pnpm --dir web build && uv run python -m gates.web` (Playwright, headless) | build exits 0; the app loads `uri_2021`, scrubs hour 0→72 without a network request per frame (asserted via request log); cascade playback shows the tripped set for hour t equal to `cascade_runs` at t; the critical-load panel turns red at the first hour a `dod` entry appears; the site card for the #1 site shows the same `safety_score`/`grid_value_score` as `site_scores`; the Ask box renders SSE text incrementally. **Neg-control:** a fixture `cascade_runs` with an extra tripped id must appear in the playback (UI reads data, not a baked demo array). |
| **G_HYGIENE** | `uv run python -m gates.hygiene` | no secrets (gitleaks-class scan), `.env` untracked, no file > 50 MB tracked, `data/raw/` untracked; freeze-walker: `git diff gate-baseline-u0..HEAD -- gates/ docs/specs/` limited to allowed paths is empty. **Neg-control:** a one-byte mutation of a frozen fixture must redden even if its manifest entry is regenerated. |
| **G_HONESTY** (per PR) | independent honesty-analyst per PR (see `swarm-plan.md`) | APPROVE with one mutation probe per load-bearing claim (break the wire → matching gate RED → reset), scope-dodge check, and re-run of the unit's gate command. One BLOCK-class finding = BLOCK, not CONDITIONAL. |

## Integration branch / repo
- Repo `Wyzard1004/flux`, default `master`. Integration branch **`swarm/flux`**; per-unit
  branches `swarm/flux-u<N>` PR into it. The team merges `swarm/flux` → `master`.
- U0 creates the `gates/` tree, `gates/thresholds.yaml`, fixtures, and the freeze manifest,
  and tags `gate-baseline-u0` on merge. Nothing else may edit `gates/` afterwards.

## Baseline-red exceptions
None — greenfield. Every gate is born red. G_COPILOT's SKIPPED-ENV (no API key) is the only
sanctioned non-green terminal state and requires an explicit ack.

## Anti-goals (a win that trips one is REJECTED even if the gate went green)
1. **The model never computes.** Any number in copilot output that does not trace to a tool
   result is a lie, whatever the gate says. Hard-coding demo answers into the prompt = BLOCK.
2. **No fabricated regulatory or market facts.** Every citation resolves to a chunk in
   `corpus_chunks` from a real document; every pitch claim tagged `[UNVERIFIED]` in
   `docs/specs/verification/` stays out of the UI and the system prompt until verified.
3. **Synthetic topology is said out loud.** The UI and copilot label ACTIVSg2000 as synthetic;
   overlaying real HIFLD geometry never implies real topology.
4. **No baked demo data.** Playback, cards, and scores read the DuckDB tables the pipelines
   wrote; a `demo_fixtures.json` that the UI prefers over the tables = BLOCK.
5. **No silent fallbacks.** Missing data, missing key, failed solve, failed fetch → loud error
   or an explicit SKIPPED-ENV, never a default value that looks like a result.
6. **No threshold gaming.** Tuning `gates/thresholds.yaml`, dropping hard counties from the
   holdout, or shrinking the Uri window to pass G_OUTAGE = scope-dodge BLOCK.
7. **No secrets in the repo.** API keys via env only; `data/raw/` and `.env` stay untracked.
8. **Determinism over speed.** A faster cascade that is no longer seed-reproducible fails
   G_CASCADE by design. Swapping in lightsim2grid to chase speed is out of scope (it cannot load this case).

## Done condition
CONVERGED = every gate GREEN on `swarm/flux` from a clean clone, with G_HONESTY APPROVE on
every merged PR and `gates/freeze-manifest.json` `[PROVEN]`; or LOUD-ESCALATION naming the
gate, the unit, and the decision needed. "Document the gap and stop" is not a terminal state.
