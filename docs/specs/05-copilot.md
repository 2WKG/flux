# 05 — Copilot service (`copilot/`)

> **State scope:** Tools must expose a selected state only when its declared artifacts and validation contract are present. Texas references below describe the repository's topology adapter, which requires its source artifacts and build. [`10-minnesota-demo.md`](10-minnesota-demo.md) is planning authority, not a checked-in Minnesota fixture.

Status: draft, weekend build. Owner: copilot lane. Depends on `data/duck/grid.duckdb` being populated by specs 01–04 (twin, outage model, cascade, siting/line-upgrade).

> **Legacy Texas scope (D-5).** Every Texas/ERCOT/ACTIVSg2000 reference in this document is the
> **legacy** path that [`README.md`](README.md) declares superseded by
> [`10-minnesota-demo.md`](10-minnesota-demo.md) as *planning* authority. It is retained, not
> deleted, because it is what the code runs: `BUILT_LAYERS = frozenset({"buses"})`
> (`copilot/routes/layers.py:44`) and `SYNTHETIC_TOPOLOGY_LABEL = "synthetic (ACTIVSg2000)"`
> (`layers.py:59`) are the only topology this service serves, and no `mn_*` read route exists.
> Minnesota supersedes this as plan, not yet as behaviour.

## Purpose

A FastAPI service that (a) is the single read API the web app uses for map layers and scenario metadata, (b) fronts the engine tools (`predict_outage`, `run_cascade`, `score_site`, `top_lines`, and per 00 §A8 `compare_interventions`, `top_critical_elements`) as HTTP routes for the UI, and (c) hosts the tool-calling Claude copilot behind `POST /ask`.

The copilot is the "answers questions in English with citations" layer of Idea 1 — **Flux** (pitch §"What it does" item 5, Layer 6). The prior briefing's tool names (`top_line_upgrades`, `score_site(lat, lon, capacity)`, …) map onto the contract names per 00-overview amendment A8; only the contract names exist in code. Its contract with the judges is the one in the shared stack: **the model narrates and plans; it never computes.** Every number in an answer must come from a tool result; every regulatory claim must come from a `cite` hit. If the model cannot get a tool result it says so instead of answering.

State-aware: public-context tools operate only on the selected state's available artifacts. Topology, flow, cascade, and siting tools are available only where a validated topology contract exists; the repository's Texas ACTIVSg2000 adapter also requires its source artifacts and build. The checked-in five-bus preview is not a state model.

## Inputs

| Input | Source | Notes |
| --- | --- | --- |
| `data/duck/grid.duckdb` | specs 01–04 | Opened read-only by this service. Tables consumed: `buses`, `lines`, `gens`, `counties`, `critical_loads`, `scenarios`, `outage_predictions`, `cascade_runs`, `site_candidates`, `site_scores`, `line_upgrade_scores`, `eaglei_outages`. |
| Engine Python modules | specs 02–04 | `predict_outage`, `run_cascade`, `score_site`, `top_lines` are thin wrappers: they read precomputed rows from DuckDB when a matching `(scenario_id, …)` row exists and only call the live engine (LightGBM / pandapower) on a cache miss. On the demo path everything is precomputed. |
| `copilot/corpus/*.pdf` | hand-downloaded | 10 CFR 100; NRC Reg Guide 4.7; DOE coal-to-nuclear report (Sept 2022) + DOE update (Sept 2024); EO 14299, 14300, 14301, 14302 (May 2025, Federal Register PDFs); NRC July 2026 proposed siting rule (FR notice); FERC DLR ANOPR RM24-6; ADVANCE Act (P.L. 118-67 excerpt). Filenames are the citation keys (see Retrieval). |
| `ANTHROPIC_API_KEY` | env | Required. |
| `VOYAGE_API_KEY` | env | Optional; when absent retrieval is BM25-only (see Retrieval). |
| User question | `POST /ask` body | Plus optional UI context (current scenario, hour, selected site/element) so the model can resolve "this site". |

## Outputs

- SSE stream on `POST /ask`. Its complete v1 event list, envelopes, ordering,
  terminal behavior, heartbeats, and resume semantics are defined by the
  [SSE event schema](../research/sse-event-schema.md); this service and the web
  client implement that one transport contract.
- JSON on the engine routes and GeoJSON / Arrow IPC on `GET /layers/{name}`.
- A structured `answer` record appended to `copilot/logs/asks.jsonl` per question: question, ordered tool calls with inputs/outputs (truncated to the cap), citations, final text, `usage` tokens, wall time. This is the eval artifact.

## Algorithm or Design

### Process layout

```
copilot/
  (no copilot/pyproject.toml — deps live in the ROOT pyproject.toml; see 00 §amendments)
                            # pypdf, rank-bm25, numpy are in root pyproject (verified 2026-09-05).
                            # NOT yet in root pyproject (must be added before this lane builds):
                            #   pydantic-settings  (for Settings(BaseSettings) below — `import pydantic_settings` fails in the uv env)
                            #   voyageai           (no optional extra exists; add a `dense` extra or install ad hoc)
  app.py                    # FastAPI app factory, CORS, lifespan opens DuckDB
  config.py                 # Settings(BaseSettings) from `pydantic_settings`: ANTHROPIC_API_KEY, DUCKDB_PATH, VOYAGE_API_KEY, MODEL, ...
  db.py                     # one duckdb.connect(read_only=True); per-request cursor(); SQL guard
  tools/
    schemas.py              # TOOL_SCHEMAS: list[dict]  (JSON Schema, strict)
    impl.py                 # predict_outage, run_cascade, score_site, top_lines, sql, cite,
                            # compare_interventions, top_critical_elements (00 §A8), causal_query (spec 07) -> dict
                            # + resolve_site(lat, lon) helper (A8; not a model-facing tool)
    registry.py             # name -> callable, per-tool timeout, result cap
  agent/
    system_prompt.py        # SYSTEM_PROMPT constant (frozen text, cache-controlled)
    loop.py                 # run_ask(question, ctx) -> AsyncIterator[SseEvent]
    verify.py               # number-trace + citation-trace post-checks
  retrieval/
    ingest.py               # pdf -> chunks -> corpus_chunks table (+ embeddings if key)
    search.py               # cite(): hybrid BM25 + dense, RRF
  routes/
    ask.py layers.py scenarios.py engine.py
  corpus/                   # PDFs (git-lfs or downloaded by scripts/fetch_corpus.sh)
  eval/
    questions.yaml          # demo + regression questions with expected tool traces
    run_eval.py             # replays questions, checks traces, writes eval/report.md
```

One process, one DuckDB connection (read-only), async FastAPI; blocking DuckDB and engine calls run in `asyncio.to_thread`.

### Model and SDK

- SDK: `anthropic` (Python; installed 1.4.0, introspected 2026-09-05). Client: `anthropic.AsyncAnthropic()` (reads `ANTHROPIC_API_KEY`).
- Model: `claude-opus-5` (default; `COPILOT_MODEL` env can override, e.g. `claude-sonnet-5` for cheaper eval runs). Ids match the Anthropic `claude-api` skill model table (cached 2026-06-24); not confirmed against the live Models API this session (no key in the checkout) — the `/health` startup check must call `client.models.retrieve(COPILOT_MODEL)` and fail loud. Adaptive thinking is on by default on Opus 5; we set it explicitly with a low effort for the tool-planning turns to keep latency under the demo budget:

```python
thinking={"type": "adaptive"},
output_config={"effort": "medium"},
```

  (SDK shapes verified against `anthropic` 1.4.0: `ThinkingConfigAdaptiveParam = {type: "adaptive", display?: "summarized"|"omitted"}`; `OutputConfigParam.effort ∈ low|medium|high|xhigh|max`.) No `temperature`/`top_p` (rejected with 400 on Opus 5 per the `claude-api` skill thinking table — documented, not exercised live here). No assistant prefill (rejected). No forced `tool_choice` — `{"type": "auto"}` (`ToolChoiceAutoParam`, optional `disable_parallel_tool_use`) plus the system-prompt rule; `strict: true` on every tool (`ToolParam.strict: bool`, top-level on the tool, not on `tool_choice`) so arguments always validate.
- Streaming: `client.messages.stream(...)` on every model turn (long outputs, tool chains). Verified signature (`AsyncMessages.stream`): keyword-only `max_tokens, messages, model, system, tools, tool_choice, thinking, output_config, cache_control, …`; returns an async context manager whose stream yields typed events (`TextEvent{type:"text", text, snapshot}`, `InputJsonEvent`, `ThinkingEvent`, raw `RawContentBlockDeltaEvent`…) and exposes `get_final_message()` / `get_final_text()`. `max_tokens=8000` per turn (answers are short; tool inputs are tiny).
- Refusal handling: check `stop_reason == "refusal"` before reading content (`StopReason` literal in 1.4.0: `end_turn|max_tokens|stop_sequence|tool_use|pause_turn|refusal|model_context_window_exceeded`; `Message.stop_details: RefusalStopDetails | None`). Emit a terminal `error` using the canonical `refusal` code and a safe user-facing message; do not expose provider category or explanation unless it has been explicitly classified safe. Server-side `fallbacks` is a `client.beta.messages.create/stream` parameter only (verified: present on the beta signature, absent on non-beta `messages.stream`); the `claude-api` skill recommends enabling it by default on Opus 5, but we do not need it for this corpus — energy siting questions do not trip classifiers. Leave a TODO.
- Prompt caching: `system` is a single frozen text block with `cache_control: {"type": "ephemeral"}` (`CacheControlEphemeralParam{type, ttl?: "5m"|"1h"}`); tools list is a module constant in fixed order; volatile UI context goes in the first **user** message, never in `system`. Verify `usage.cache_read_input_tokens > 0` on the second demo question (`Usage` fields verified: `input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens, …`).

### Tool-use loop (`agent/loop.py`)

Manual loop (not the beta tool runner) because we need to emit an SSE event per tool call/result and enforce timeouts and size caps ourselves.

```
messages = [{"role":"user","content": render_user_turn(question, ui_ctx)}]
for iteration in range(MAX_ITER=8):
    async with client.messages.stream(model, max_tokens=8000, system=SYSTEM,
                                      tools=TOOL_SCHEMAS, thinking=..., output_config=...,
                                      messages=messages) as stream:
        async for event in stream:
            if event.type == "text": yield SSE text(delta=event.text)   # TextEvent; .snapshot is the running text
        msg = await stream.get_final_message()
    if msg.stop_reason == "refusal": yield terminal SSE error(code="refusal", retryable=false); return
    messages.append({"role":"assistant","content": msg.content})
    tool_uses = [b for b in msg.content if b.type == "tool_use"]
    if not tool_uses:  break                      # end_turn
    results = await asyncio.gather(*[run_tool(tu) for tu in tool_uses])   # parallel calls
    for tu, res in zip(tool_uses, results): yield SSE tool_call / tool_result
    messages.append({"role":"user","content":[tool_result blocks, ALL in one message]})
else:
    yield terminal SSE error(code="deadline", message="The answer reached its iteration limit.", retryable=false)
verify(final_text, tool_results, citations) -> yield SSE done{verified:…}
```

Rules:

- `MAX_ITER = 8` model turns per question. Demo questions need 2–4.
- Per-tool timeout (`asyncio.wait_for`): `predict_outage` 5 s, `run_cascade` 20 s (precomputed hit is ms; live pandapower on a miss can take seconds), `score_site` 20 s, `top_lines` 5 s, `sql` 5 s, `cite` 5 s, `compare_interventions` 30 s (runs a baseline/with-intervention `run_scenario` pair per id), `top_critical_elements` 5 s (reads persisted `cascade_runs` only), `causal_query` 5 s. Timeout → `tool_result` with `is_error: true` and content `{"error":"timeout","tool":…}`; the model is told (system prompt) to report the failure, not to guess.
- Tool exceptions → `is_error: true` with the exception message (no traceback). Never dropped.
- Result size cap: each `tool_result` content is JSON-serialized and truncated to **8 KB** (`sql` rows capped at 200 before serialization; `cite` chunks capped at 1,200 chars each). Truncation appends `{"truncated": true, "omitted_rows": n}`.
- Parallel tool calls are executed concurrently and returned in a single user message (splitting them degrades parallel calling).
- Whole `/ask` wall-clock budget 90 s; exceeded → terminal `error` using the canonical `deadline` code.
- `json.loads` on `tool_use.input` is not needed (SDK gives a dict) but every input is re-validated with the pydantic model for the tool before execution.

### Tool schemas (`tools/schemas.py`)

All nine use `strict: true`, `additionalProperties: false`, explicit `required`. Signatures are the shared contract (00 §2.4 + amendment A8) and must not change. `tools/schemas.py` bounds the two ranking page sizes to `1 ≤ n ≤ 50` (`TOP_LINES_MAX_LIMIT`; `top_critical_elements.n` carries the same bound); `top_lines` exposes no `offset` or `sort` parameter — pagination is not model-facing and the result order is spec 08's `mw_per_musd` desc, owned by the implementation. The nine: the six below plus `compare_interventions`, `top_critical_elements` (both A8, rows below), and `causal_query` (spec 07 owns its schema; registered here in the same list).

| name | input schema (required unless default) | returns (JSON dict) |
| --- | --- | --- |
| `predict_outage` | `county_fips: str`, `scenario_id: str` (enum `uri_2021,beryl_2024,helene_2024,forecast_72h`), `horizon_h: int = 72` | `{county_fips, county_name, scenario_id, horizon_h, peak_p_out, peak_ts, customers_at_risk, driver, series:[{ts,p_out,customers_at_risk}]}` (series downsampled to ≤ 24 points) |
| `run_cascade` | `element_ids: list[str]`, `scenario_id: str`, `hour: int` | `{run_id, scenario_id, hour, tripped_element_ids, lost_load_mw, counties_dark:[fips], critical_loads_lost:[{id,name,kind,hour_lost}], steps:int}` |
| `score_site` | `site_id: str`, `unit_mw: int` (enum 300, 1000), `scenario_id: str` | `{site_id, name, kind, county_fips, unit_mw, safety_score, safety_flags:[str], grid_value_score, lol_reduction_mwh, congestion_relief_pct, blackstart_reach_mw, critical_loads_protected:[str], regulatory_path:str}` |
| `top_lines` | `region: str` (e.g. `"ERCOT"`, `"TX"`, or a county fips), `tech: "dlr"\|"reconductor"\|"any"`, `n: int = 10` | `{region, scenario_id, artifact_id, tech, lines:[{line_id, source_class, intervention_type, status, from_bus, to_bus, kv, congestion_usd_yr, uplift_mw, cost_usd, mw_per_musd, ferc_screen_pass, spark_eligible}]}`; ambiguous or legacy-unqualified artifacts are unavailable |
| `sql` | exactly one of legacy `query: str` or deployment-advertised `template_id: str` (the input boundary rejects neither/both) | `{columns:[str], rows:[[…]], row_count, truncated}` |
| `cite` | `query: str`, `k: int = 5` | `{hits:[{doc, title, page, chunk_id, score, text}]}` |
| `compare_interventions` (A8) | `scenario_id: str` (same enum), `intervention_ids: list[str]` (each `site:<site_id>`, `site:<site_id>@300`, or `line:<line_id>`; 1–5 ids) | `{scenario_id, baseline_run_id, interventions:[{intervention_id, kind: site\|line, run_id, lol_reduction_mwh, customer_hours_avoided, critical_loads_protected:[cl_id]}], assumptions:[str]}` — sorted by `lol_reduction_mwh` desc; the tool computes every delta, the model reports them. **Reconciliation (2WKG-173):** that sentence describes the *tool* (`compare_interventions` in `tools/impl.py`), which may compute. The HTTP `POST /compare` route above is a different surface: it only reads deltas a pipeline already persisted and answers `persisted_delta_unavailable` when they are absent. The output shape is shared; the obligation to compute is not |
| `top_critical_elements` (A8) | `region: str` (`"ERCOT"`, `"TX"`, or a county fips), `n: int = 10` | `{region, n, scenario_ids:[str], elements:[{element_id, kind: line\|bus\|gen, lost_load_mw, critical_loads_lost:[cl_id], runs:int}], partial?:bool}` — ranked by cascade reach from persisted `cascade_runs`; `partial: true` when fewer than `n` elements have any persisted run |
| `causal_query` | `kind: "attribution"\|"effect"\|"counterfactual"`, optional selected county/site/treatment and the declared scenario/capacity fields | `{answer_numbers, method, assumptions, interval, evidence_rows, question:{treatment,outcome,target_population}, sources:[{source_id,name,version,locator,coverage}], sample:{unit,n_total,n_treated,n_control,period}, diagnostics:[{name,status:"pass",evidence}], citations:[{source_id,locator}]}` from one exact registered evidence artifact; malformed, fixture, missing, or insufficient evidence is canonical unavailable with no effect number |

`resolve_site(lat: float, lon: float) -> {site_id, name, distance_km}` (A8) is a helper inside `impl.py`, not in `TOOL_SCHEMAS`: when a question carries a bare lat/lon (the description's `score_site(latitude, longitude, capacity)` shape), the `score_site` wrapper resolves it to the nearest `site_candidates` row (error if > 25 km) and the UI context / answer names that `site_id`. The model never sees lat/lon-shaped `score_site` arguments.

`sql` guard (`db.py`): a deployment may register named approved templates. Each template has a unique simple `template_id`, fixed SQL, and its complete declared set of approved view relations; construction validates that declaration against the parsed statement. When a registry is configured, requests must send exactly one known `template_id`; raw `query` text is rejected before opening the database. Deployments without a registry retain the legacy `query: str` input and answer a `template_id` with an explicit `unsupported_request` naming the missing registry rather than executing anything. The published JSON Schema and TypeScript declaration preserve the legacy query-only form (and accept the template-only form); strict provider schemas require both selector keys and make the unused selector `null`, while enforcing exactly one non-null selector. Only deployment-owned templates may contain positional `?` parameters. Their callers may supply at most 25 finite JSON scalar values; exact arity is checked and values are bound before execution. Legacy free-form `query` text rejects placeholders and supplied values.

For either mode, strip comments; reject unless the statement, after `sqlglot`-free heuristics, starts with `SELECT` or `WITH`, contains none of `INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|ATTACH|COPY|PRAGMA|INSTALL|LOAD|CALL|EXPORT`, contains a single statement (no `;` except trailing), and the connection is `duckdb.connect(path, read_only=True)`. The denylist is load-bearing, not belt-and-braces: verified on duckdb 1.5.5 that a `read_only=True` connection rejects `INSERT` ("Cannot execute statement of type INSERT on database … attached in read-only mode") and `ATTACH`, but **`COPY (SELECT …) TO '/path'` still writes a file** on a read-only connection — only the denylist stops it. Wrap as `SELECT * FROM (<q>) LIMIT 201` to detect truncation; there is no DuckDB `statement_timeout` (verified: `SET statement_timeout` → "unrecognized configuration parameter", and no `%timeout%` entry in `duckdb_settings()`); use `asyncio.wait_for` plus `conn.interrupt()` (method exists on `DuckDBPyConnection`) on timeout.

Production registry mode rejects every query shape except a deployment-approved template; approved templates, including full-view aggregates, run under the 200-row response cap and enforced five-second interruptible deadline. The response cap does not claim to bound scan work. Each attempt emits a structured execution record containing only template id, parameter count, row count, duration, provenance artifact ids, and safe outcome; it never records raw SQL, bound values, paths, secrets, or driver exception text. Logging callback failure cannot change the tool result.

`regulatory_path` in `score_site` is a lookup from `site_candidates.kind` (spec 04 defines it): `coal_retired|coal_retiring → "ADVANCE Act brownfield / DOE coal-to-nuclear"`, `nuclear_existing → "NRC early site permit, existing licensed site"`, `federal → "DOE authorization on federal land (EO 14301)"`, `defense → "DoD installation (EO 14299 / Army Janus)"`. The model must still `cite` before repeating it.

### System prompt (`agent/system_prompt.py`) — contents

Frozen text, ~600 tokens. Required contents (write them as plain prose; do not over-prescribe, Opus 5 follows short rules well):

1. Identity: grid-planning copilot for the selected state's declared data and model contract. The repository's only topology adapter is synthetic ACTIVSg2000 Texas and requires its source artifacts and build; say when topology is synthetic and report unavailable when the selected state has context only.
2. **Never compute.** Every number (MW, MWh, %, counts, dollars, probabilities, distances, scores) you state must be copied from a tool result in this conversation. Do not add, subtract, average, convert units, or estimate. If a comparison needs a number you don't have, call a tool. If no tool can produce it, say you cannot answer that part.
3. **Cite regulation only from `cite`.** Any statement about NRC, DOE, FERC, executive orders, or statutes must follow a `cite` call and quote the `doc` + `page`. Inline citation format: `[doc p.N]`. Never cite from memory.
4. **No tool, no answer.** If the question is about the grid, outages, cascades, sites, or lines and you have made no tool call, do not answer — call a tool first. Greetings/meta questions are the only exception.
5. Planning: prefer `score_site`/`predict_outage`/`run_cascade`/`top_lines`/`compare_interventions`/`top_critical_elements` over `sql`; use `sql` only for lists/lookups (e.g. resolve a name to an id, list top-N). "Which elements/substations carry the most cascade risk" → `top_critical_elements`; "compare site X with line upgrade Y" → `compare_interventions`, never two `run_cascade` calls plus your own subtraction. Batch independent calls in one turn.
6. UI context: the user message may carry `scenario_id`, `hour`, `selected_site_id`, `selected_element_id`, `compare_site_id`. "This site"/"the one near Houston" resolve to those ids; if absent, resolve via `sql` on `site_candidates`.
7. Answer shape: ≤ 180 words, lead with the recommendation, then 3 reasons and up to 3 risks as bullets, each with its number and source (`tool:score_site` or `[doc p.N]`). End with one line listing which tools were used.
8. Report tool failures plainly ("cascade timed out; I can't quantify lost load") — do not fill the gap.
9. Do not include internal or system XML tags in the response.

### Post-answer verification (`agent/verify.py`)

Runs after the final text; result is emitted in `done` and logged. It does not block the stream (the demo must not stall), but the UI shows a small "verified" / "unverified numbers: 2" badge.

- **Number trace:** regex all numerals in the final text (strip thousands separators; accept `%`, `MW`, `MWh`, `$`, `k`, `M` suffixes). For each, search the concatenated tool results for the same value with tolerance: exact match, or match after rounding to the printed precision (e.g. text `1,240 MWh` vs tool `1239.6`). Years in citations (`2021`), FIPS codes, and `p.N` page numbers are exempted. Unmatched numerals → `unverified_numbers: [...]`.
- **Citation trace:** every `[doc p.N]` must correspond to a `cite` hit returned in this conversation (`doc` + `page` exact). Unmatched → `unverified_citations`.
- **Regulatory-claim guard:** if the text mentions `NRC|10 CFR|DOE|FERC|executive order|EO 14|ADVANCE Act|Reg Guide` and there was no `cite` call → `verified=false, reason="regulatory_claim_without_cite"`.

### Retrieval (`retrieval/`)

**Corpus:** `copilot/corpus/<doc_key>.pdf`, doc keys: `10cfr100`, `regguide-4.7`, `doe-c2n-2022`, `doe-c2n-2024`, `eo-14299`, `eo-14300`, `eo-14301`, `eo-14302`, `nrc-siting-rule-2026`, `ferc-dlr-anopr-rm24-6`, `advance-act`. A `corpus/manifest.yaml` maps key → title, source URL, date, and is what `cite` returns as `title`.

**Ingest (`ingest.py`, run once, idempotent):** `pypdf` page text (`pypdf.PdfReader(path).pages[i].extract_text()`; pypdf 6.17.0 installed) → per-page normalization (dehyphenate line breaks, collapse whitespace) → chunk by ~800 tokens (≈3,200 chars) with 150-token overlap, never crossing a page boundary (so `page` is exact) → rows into DuckDB table `corpus_chunks(chunk_id, doc, title, page, text, embedding FLOAT[1024] NULL)`. This table lives in `grid.duckdb` too (spec 01 owns the file; this service creates the table via a separate write connection during ingest only, never at request time).

**Dense (optional):** if `VOYAGE_API_KEY` is set, embed chunks with `voyageai.Client().embed(texts, model="voyage-4", input_type="document")` (1024-d default; Voyage docs verified 2026-09-05: `voyage-4` / `voyage-4-large` / `voyage-4-lite` / `voyage-4-nano`, 32k context, dims 1024 default + 256/512/2048; signature `Client.embed(texts, model, input_type=None, truncation=None, output_dimension=None)`) and queries with `input_type="query"`; store in `embedding`; query with DuckDB `array_cosine_similarity(embedding, ?::FLOAT[1024])` — both `array_cosine_similarity` and `list_cosine_similarity` exist in duckdb 1.5.5 (verified via `duckdb_functions()`; use the `array_` form on the `FLOAT[1024]` column) over the ~1,500 chunks — brute force is fine, no index. Anthropic has no embedding model; Voyage is the documented recommendation (Anthropic embeddings guide, fetched 2026-09-05: "Anthropic does not offer its own embedding model … Voyage AI"). The `voyageai` package is not installed in the uv env yet (see layout note).

**Sparse (always):** `rank_bm25.BM25Okapi(corpus_tokens, k1=1.5, b=0.75)` (`get_scores` / `get_top_n`; verified installed) over lowercased, punctuation-stripped tokens, built at startup from `corpus_chunks` (< 1 s). Legal text is heavy on exact terms (`"exclusion area"`, `"500 persons per square mile"`, `"population center distance"`), so BM25 alone is demo-adequate.

**Fusion:** if dense is available, take top-20 from each, reciprocal-rank fusion (`k=60`), return top-`k`. Otherwise BM25 top-`k`. `cite` returns `{doc, title, page, chunk_id, score, text[:1200], source, version, date, locator, content_kind, provenance}`; source identity and fixture classification are carried through unchanged.

**No-embeddings fallback is the default path for the weekend**; dense is a Sunday-morning upgrade only if the BM25 eval misses.

### Layers endpoint

`GET /layers/{name}` serves what the map needs (spec 06 consumes). `name ∈ {buses, lines, gens, counties, critical_loads, outage_risk, cascade, sites, line_upgrades, storm, national_hex}`. Static geometry is cached in memory as GeoJSON bytes at startup; scenario-dependent layers are built per request from DuckDB and cached by `(name, scenario_id, hour, run_id)` in an LRU (size 64).

| name | format | query params | shape |
| --- | --- | --- | --- |
| `buses` | GeoJSON Point | — | props `bus_id, name, kv, county_fips` |
| `lines` | GeoJSON LineString | `scenario_id?`, `hour?` | props `line_id, from_bus, to_bus, kv, rate_mw, loading_pct` (loading from cascade run at hour if given, else base) |
| `gens` | GeoJSON Point | — | `gen_id, name, fuel, mw, retiring` |
| `counties` | GeoJSON Polygon (simplified, 5 kB/county max) | — | `county_fips, name, customers` |
| `critical_loads` | GeoJSON Point | — | `id, name, kind (dod\|hospital\|water), mw, bus_id` |
| `outage_risk` | Arrow IPC (`county_fips: str, ts: timestamp, p_out: f32, customers_at_risk: i32, driver: str`) | `scenario_id` (required) | full time series for choropleth scrub |
| `cascade` | JSON | `scenario_id`, `run_id?` (default: latest run for scenario) | `{run_id, hours:[{hour, tripped_element_ids, lost_load_mw, counties_dark, critical_loads_lost}]}` |
| `sites` | GeoJSON Point | `scenario_id`, `unit_mw?=300` | `site_candidates ⋈ site_scores` props |
| `line_upgrades` | GeoJSON LineString | `tech?` | `line_upgrade_scores ⋈ lines` |
| `storm` | GeoJSON Polygon FeatureCollection | `scenario_id` | one feature per hour: `{hour, severity}` (from spec 02's storm polygon table or NWS-alert geojson file; if absent returns empty collection) |
| `national_hex` | Arrow IPC (`h3: str, res: i8, buses: i32, lines: i32, gen_mw: f32`) | `res?=4` | precomputed from the 82k model (spec 01); **if not built the response is 503 `unavailable` with `details.reason: "not_built"`** — the shared failure envelope, never a 404 and never a bare not-built JSON body (`copilot/routes/layers.py:236-237` → `_unavailable` `:98-112` → `UnavailableError.http_status = 503`, `copilot/api/errors.py:76-83`). `BUILT_LAYERS = frozenset({"buses"})` (`layers.py:44`), so **eleven of the twelve documented layers answer this way today**, not only `national_hex` and the UI hides the layer |
| `eaglei` | Arrow IPC (`county_fips, ts, customers_out`) | `scenario_id` | actual outages for the compare slider |

Arrow responses: `pyarrow.ipc.new_stream(sink: pa.BufferOutputStream, schema)` (pyarrow 25.0.1 installed), `Content-Type: application/vnd.apache.arrow.stream` (IANA-registered media type, HTTP 200 on the registry entry 2026-09-05). GeoJSON: `application/geo+json`, gzip via `fastapi.middleware.gzip.GZipMiddleware` (fastapi 0.141.1 installed).

## Interfaces

### Routes

| Route | Body / params | Response |
| --- | --- | --- |
| `GET /health` | — | `{ok, duckdb_path, tables:[…], corpus_chunks:int, dense:bool, model}` |
| `GET /scenarios` | — | `[{scenario_id, name, kind, ts_start, ts_end, hours:int, has_cascade:bool, has_predictions:bool}]` |
| `GET /scenarios/{scenario_id}` | path `scenario_id` | one row of the same shape, unwrapped; an unknown id is a `not_found` 404 failure envelope (`copilot/routes/scenarios.py:248`) |
| `GET /layers/{name}` | see table | GeoJSON / Arrow / JSON |
| `POST /site-score` (2WKG-172 Minnesota artifact read) | `{site_id (≤128), unit_mw ∈ {300, 1000}, scenario_id (≤128)}` | one persisted `site_scores` row for that `(site_id, scenario_id, unit_mw)`, unwrapped: `{site_id, name, kind, county_fips, scenario_id, unit_mw, artifact_id, model_mode:"topology", safety_score, safety_flags:[str], grid_value_score, lol_reduction_mwh, congestion_relief_pct, blackstart_reach_mw, limitations:[str], source_kind, topology, provenance:{site_candidate:{…}, site_score:{…}}}`. It reads persisted values only and never runs `score_site`. `model_mode` and `limitations` are **not** `site_scores` columns — the DDL 2.1.0 contract (`pipelines/db.py`) does not define them — so they are read from the owning `mn_artifact_manifests` row, selected by `identity_json.source_identity` `{family: "site_score", scenario_id, intervention_id: "site:<site_id>@<unit_mw>"}`, the same manifest JOIN `GET /cascade` and `GET /predictions` use. Failures: site not persisted at all → `404 not_found` (permanent, never a retryable 503); site persisted with no score for this scenario/unit → `503` reason `no_persisted_outcome`; absent DB → `503` reason `missing`; no owning manifest → `outcome_metadata_unavailable`; more than one → `ambiguous_identity`; manifest `availability='unavailable'` → `artifact_unavailable`; `model_mode ≠ 'topology'` → `unsupported_model_mode`; column drift → `schema_mismatch`; unreadable persisted values or empty limitations → `invalid_persisted_outcome`; missing provenance → `provenance_missing`; no derivable topology label → `topology_label_unavailable` (never a `null` label inside a 200, matching `GET /cascade`); malformed params are the shared 422 `invalid_input` |
| `GET /lines/top` (2WKG-172 paged persisted read) | `region` (1–64), `tech=any ∈ {dlr, reconductor, any}`, `limit=50` (1–`TOP_LINES_MAX_LIMIT`, i.e. 1–50), `offset=0` (0–10,000) | the `top_lines` `LinesData` dict (`copilot/tools/schemas.py`) for one bounded page of the persisted ranking, served through the same `TopLinesReader`. The page is a total order — `mw_per_musd` desc, then the winning-tech cost asc, then `line_id` asc — via `copilot.api.pagination.DeterministicOrder`, so paging cannot repeat or skip a row. The HTTP `limit` is capped at `TOP_LINES_MAX_LIMIT` so this surface can never exceed the model-facing bound for the same read; out-of-range `limit`/`offset` are the shared 422 `invalid_input`. An absent database, an absent `line_upgrade_scores` table, or a qualified selection with zero rows is `503` reason `artifact_unavailable` — never an empty `lines` list. The frozen A8 tool input is unchanged: `top_lines(region, tech, n)` stays unpaginated and exposes no `offset` or `sort` (§Tool schemas) |
| `GET /predictions` (2WKG-104 Minnesota artifact read) | `scenario_id?` (`^[a-z0-9][a-z0-9_-]*$`, ≤64), `county_fips?` (`^\d{5}$`), `model_kind? ∈ {lightgbm, heuristic}`, `limit=1000` (1–1000) | bare array `[{scenario_id, county_fips, ts, p_out, customers_at_risk, driver, model_kind, model_version, artifact_sha256, split_id, feature_set_version, evaluation_sha256, rule_id, rule_version, persisted_at, evaluation_status, qualified, qualification_reason}]` — only rows whose cited evaluation is persisted `qualified = TRUE` (filtered in SQL before `LIMIT` via `models.outage.persistence.query_predictions(qualified_only=True)`), ordered `(scenario_id, county_fips, ts)`. Heuristic rows cite no evaluation and are by design never qualified: an artifact with only unqualified/heuristic rows is `503 unavailable` reason `no_qualified_prediction`; absent DB / absent `outage_predictions`·`prediction_provenance`·`evaluation_artifacts` table / drifted columns are `database_missing` / `missing` / `schema_mismatch`; malformed params are the shared 422 `invalid_input` |
| `GET /cascade` (2WKG-170 Minnesota artifact read) | `scenario_id` (required, same shape), `run_id?` (≤128) | one qualified persisted `cascade_runs` run, unwrapped: `{run_id, scenario_id, artifact_id, model_mode:"topology", geography_id, hours:[{hour, tripped_element_ids, lost_load_mw, counties_dark, critical_loads_lost}], provenance:[{source_name, source_ref, source_version, retrieved_at, license_or_terms, source_record_id, content_sha256, is_derived}], limitations:[str], source_kind, topology, attributes}` — qualified means the run's `mn_model_results` row is `validated`, its `mn_artifact_manifests` row is `available` with `model_mode = 'topology'`, and it has ≥1 `mn_artifact_provenance` row and ≥1 limitation. `lost_load_mw` is MW (`attributes` carries unit/source per field); `source_kind`/`topology` (`"synthetic (ACTIVSg2000)"` or `null`) are derived from the artifact's and the row's persisted provenance, never a constant — no derivable label → `503` reason `topology_label_unavailable`. Without `run_id` the qualified run with the greatest manifest `created_at` wins, tie-broken by lexical `run_id` then `artifact_id` desc — a total order over the selected columns, so the served run is deterministic when two available manifests cite one `model_run_id` at the same `created_at` (`created_at` is the only run-level timestamp persisted). No persisted row for the scenario → `503` `cascade_not_computed`; an `aggregate` or `not_applicable` model and no topology artifact → `503` `topology_cascade_unsupported`; a persisted row with absent or unavailable topology metadata → `503` `cascade_artifact_unavailable` (`run_id` echoed when given). Precedence when a scenario holds both is *most recoverable wins*: any `topology` artifact present → `cascade_artifact_unavailable`, so a scenario with one `aggregate` run and one unavailable `topology` run is never reported as an unsupported model. (`mn_model_results.validation_status` is `CHECK(validation_status='validated')` in the 2.1.0 DDL, so an unvalidated row cannot be persisted; the route's `validated` filter is defensive only.) `run_id` not persisted at all → `404 not_found`; table absent (incl. the `mn_*` namespace) / column drift / NULL `lost_load_mw` / malformed manifest → `503` reason `missing` / `schema_mismatch` / `invalid_topology_artifact` (never a 500, never an invented number). |
| `POST /compare` (A8; 2WKG-173 persisted-artifact read) | `{scenario_id (≤128), intervention_ids:[str]}` (1–5 ids, each `site:<id>`, `site:<id>@300\|@1000`, or `line:<id>`) | the `compare_interventions` dict — `{status, provenance:[ArtifactRef], scenario_id, baseline_run_id, interventions:[{intervention_id, kind, run_id, lol_reduction_mwh, customer_hours_avoided, critical_loads_protected}], assumptions}` — **plus** two documented additions: `evidence` (the persisted score behind each row: `artifact_id`, `model_mode`, `metric`, `score_value`, `score_unit`, `score_components`, `regulatory_label`, `provenance`, `limitations`, `assumptions`) and `comparison_status: "persisted_scores_not_derived_deltas"`. The A8 fields validate against the frozen `InterventionsData`/`Intervention` models verbatim; `scenario_id` follows the Minnesota `^[a-z0-9][a-z0-9_-]*$` shape of `GET /predictions`, which is wider than the tool's four-value `ScenarioId` enum. **This route reads persisted deltas; it never derives one.** Every A8 measure comes from the artifact's `score_components_json`; a component the artifact does not carry is `503` reason `persisted_delta_unavailable` naming the `field` and `intervention_id`, never a zero or an omission. `provenance` is built only from persisted `mn_artifact_provenance` rows, with `source_kind` derived by the same label deriver `GET /cascade` uses — an unlabelable source is `503` reason `source_kind_unavailable`. Qualification is read from the manifest, never from the request: `artifact_kind='score'`, `geography_id='mn'`, `identity_json.source_identity` = `{family:'comparison', scenario_id, intervention_id}`. Failures: absent DB → `database_missing`; absent `mn_artifact_manifests` → `missing`; fewer qualified artifacts than requested ids → `no_qualified_result` (never a 200 carrying a subset); two qualified artifacts for one intervention, or artifacts citing different `baseline_run_id`s → `ambiguous_identity`; a declared-unavailable manifest → `artifact_unavailable`; `model_mode ≠ 'topology'` → `unsupported_model_mode`; identity/values disagreement → `invalid_persisted_result`; column drift → `schema_mismatch`; malformed ids are the shared 422 `invalid_input` |
| `GET /elements/critical` (A8; 2WKG-173 persisted-artifact read) | `region` (1–128), `n=10` (1–50), `offset=0` (0–10,000) | the `top_critical_elements` dict — `{status, provenance:[ArtifactRef], region, n, scenario_ids, elements:[{element_id, kind, lost_load_mw, critical_loads_lost, runs}], partial}` — **plus** two documented additions: `offset` (the page cursor) and `evidence` (the persisted score behind each element). The A8 fields validate against the frozen `CriticalElementsData`/`CriticalElement` models. `scenario_ids` is the sorted set of the served elements' persisted `scenario_id`s. `partial` is `true` when fewer than `n` elements have any persisted run — counted over the whole filtered relation, so a short last page under `offset` is **not** `partial`. The page is a total order (`score_value` desc, then the `mn_score_results.artifact_id` primary key asc) via `copilot.api.pagination.DeterministicOrder`, so paging cannot repeat or skip an element. Failure reasons are the same closed vocabulary as `POST /compare` |
| `GET /api/v1/grid/layers/{layer}` (2WKG-89 published physical-inventory read) | path `layer` (an `asset_class` present in the release, or `all`); `state ∈ {tx, mn}` and `version` (`^\d+\.\d+\.\d+$`) both required; `bbox?` = `west,south,east,north` in WGS84; `limit=50` (1–100); `cursor?` (opaque, base64url) | one deterministic page of the published release, unwrapped: `{api_version:"v1", state, artifact_version, artifact_id, release_sha256, layer, inventory_mode, electrical_model_mode, items:[{asset_id, asset_class, asset_kind, availability ∈ {available, unavailable}, display_geometry (GeoJSON, WGS84) or null, display_crs or null, native_geometry, native_crs, geometry_status, geometry_accuracy_basis, geometry_precision_m, transform_provenance:{method, source_crs, display_crs} or null, provenance:{source_id, source_record_id, authority, source_ref, source_version, retrieved_at}}], page:{limit, cursor, next_cursor, total}, coverage:[the release's coverage rows for this layer]}`. `api_version` restates the `X-Flux-Api-Version` header inside this payload and is sanctioned here; `total` counts the whole filtered selection, not the page. The page is a total order on `asset_id` asc, so paging cannot repeat or skip an asset; `next_cursor` is `null` on the last page. The cursor is bound to `(state, version, layer, bbox, release_sha256)` — replaying it against a different request is the shared 422 `invalid_input`, so a page can never be read against a different release. This route is transport only: it never derives topology, coverage totals, or coordinates for an asset the release calls `unavailable` (those come back `display_geometry: null`, `availability: "unavailable"`, and are excluded from a `bbox` page rather than co-located into it). The WGS84 `display_geometry` is a rendering copy produced by `pyproj` `always_xy` from the release's own `geometry_crs`; the native geometry and CRS are always carried alongside it. Before any byte is served the release is verified against `manifest-{version}.json`: the manifest row's `published_path` must name the opened file, its `compressed_sha256` must equal the file's bytes, its `canonical_content_sha256` must equal the release's `content_sha256`, and the release must be self-consistent (`artifact_sha256(release) == content_sha256`). Verification is cached on both files' `(st_mtime_ns, st_size)`, so an immutable release is verified once per file version and a file replaced underneath re-verifies rather than serving a stale parse. Failures are all `503 unavailable` with `details.artifact = "physical_inventory"` and a named `reason`: no release or manifest for `(state, version)` → `release_not_found`; unparseable manifest or no row for the state → `invalid_manifest`; unreadable gzip → `unreadable_release`; a release that is not an object with an `assets` list → `invalid_release`; any of the four digest conjuncts failing → `release_hash_mismatch`; a verified release whose `geography_id`/`artifact_version` disagree with the request → `release_identity_mismatch`; a selected asset with no matching `sources` row → `provenance_missing`; a geometry that is neither `unavailable` nor a transformable object → `invalid_geometry` / `display_transform_failed`. An unknown `layer` is `404 not_found`; a malformed `bbox`, `limit`, `state`, `version`, or `cursor` is the shared 422 `invalid_input`. There is no empty success and no default: an absent release is always a named refusal |
| `POST /ask` | see below | `text/event-stream` |

**Browser consumer (D-10, 2WKG-355).** As of Joshua's 2026-09-06 decision the web App is a live
consumer of five of these routes — `GET /health`, `GET /scenarios/{scenario_id}`,
`GET /layers/{name}`, `POST /ask`, and the versioned `GET /api/v1/grid/layers/{layer}` (2WKG-89) —
through `web/src/data/`. Three properties of that consumer are contractual, not incidental:

- **Same-origin only.** The served shell's CSP is `connect-src 'self'`, so the browser requests
  these paths on its own origin. `web/server.mjs` forwards a fixed allowlist of them to
  `FLUX_API_ORIGIN` when that variable is set, and serves the SPA shell for all of them when it is
  not; it still defines no route of its own (2WKG-300).
- **A failure envelope keeps its named reason.** Every non-2xx answer reaches the screen as its
  own `error.code` and `error.message` under the frozen `unavailable` / `request_failed` token —
  never as a client-invented sentence, and never as an empty success.
- **A stream with no terminal frame is a failed request.** `POST /ask` must emit exactly one
  terminal `done` **or** `error` (`docs/research/sse-event-schema.md`). A stream that closes with
  neither is reduced to a named protocol failure by `web/src/data/ask-stream.ts`, not treated as a
  quiet end. (This implements what OQ-1 in `spec-code-reconciliation.md` left undecided on the
  browser side; the server side is unchanged.)

**Route inventory (D-3).** The twelve rows above are exactly what `copilot/app.py:68-76` mounts,
regenerated from `app.openapi()['paths']` and matched against
`copilot/test_read_route_contracts.py:95-250`. Two compute-style routes were listed here and
**have never existed on `master`** — a cascade POST and a predict POST; the persisted-artifact
reads `GET /cascade` (`copilot/routes/predictions.py:445`) and `GET /predictions` (`:248`) are
what took their place, and no route computes a cascade or a prediction inside a request.
`GET /scenarios/{scenario_id}` was implemented and undocumented.

`POST /compare` and `GET /elements/critical` are, as of 2WKG-173, persisted-artifact
reads of named Minnesota score artifacts. They keep the A8 output shape and add the
`evidence` (and, for the paged route, `offset`) fields named in their rows; they do not
run a model, derive a delta, or rank from legacy `cascade_runs`.

`POST /site-score` and `GET /lines/top` are, as of 2WKG-172, persisted-artifact
reads: they retrieve values that a pipeline already wrote and never compute a
score or a ranking in the request. Their route names and request shapes are
unchanged; what changed is that an absent, unqualified, or unlabelable artifact
is a named failure envelope rather than a computed answer.

The Minnesota `GET` routes above are read-only artifact retrieval and, like every
route here, return unwrapped payloads (`copilot/api/envelope.py`: only the failure
envelope is wrapped). `GET /cascade` returns only the latest persisted run for a scenario
whose model result is validated and whose available topology manifest has nonempty
provenance and limitations. It invokes no compute behaviour at all: the compute-style cascade route
previously described here was never implemented (D-3), so `GET /cascade` is the only cascade route. `GET /predictions` excludes
unqualified evaluation artifacts; a missing or unqualified prediction artifact returns the
documented unavailable failure envelope rather than an empty success.

Every response carries `X-Request-ID` and `X-Flux-Api-Version: v1` without wrapping a
success body. `X-Flux-Artifact` appears only on a successful `GET /cascade` response
and equals that payload's resolved immutable `artifact_id`; it is omitted elsewhere,
including every failure response.

`POST /ask` request:

```json
{
  "attempt_id": "client-generated-opaque-id",
  "question": "Why this site over the one near Houston?",
  "context": {
    "scenario_id": "uri_2021", "hour": 3,
    "selected_site_id": "site_tx_0007", "compare_site_id": "site_tx_0021",
    "selected_element_id": null, "unit_mw": 300
  },
  "history": [ {"role":"user","content":"…"}, {"role":"assistant","content":"…"} ]
}
```

`attempt_id` is required: the client creates it, sends it on the initial and any
resume POST, and verifies the matching `X-Flux-Attempt-Id` response header.
`history` is optional prior Q/A text only (no tool blocks) — max 6 turns; the
server re-injects it as plain messages before the new question.

SSE events (each `event: <type>` + `data: <json>`) use the complete v1 schema
in [`sse-event-schema.md`](../research/sse-event-schema.md). In particular,
`lifecycle` is first; every payload has `v` and `seq` equal to its monotonic
SSE `id`; `tool_call`/`tool_result` use `call_id`, `tool`, and `elapsed_ms`; and
exactly one `done` or nested-envelope `error` is terminal. A `citation` is
emitted for each `cite` hit after its tool result so the UI can render
footnotes. Producers and clients must not add local event shapes or codes.

Because it is a POST, the client uses `fetch` + `ReadableStream`, not
`EventSource` (spec 06). Transport uses
`sse_starlette.sse.EventSourceResponse(gen, ping=15,
ping_message_factory=lambda: ServerSentEvent(comment="keepalive"))`, yielding
`ServerSentEvent(data=json, event=type, id=str(n))`. Clients ignore every
comment line beginning with `:`; heartbeats do not advance the application
sequence.

### Python signatures (`tools/impl.py`) — the shared contract

```python
def predict_outage(county_fips: str, scenario_id: str, horizon_h: int = 72) -> dict: ...
def run_cascade(element_ids: list[str], scenario_id: str, hour: int) -> dict: ...
def score_site(site_id: str, unit_mw: int, scenario_id: str) -> dict: ...
def top_lines(region: str, tech: Literal["dlr", "reconductor", "any"], n: int = 10) -> dict: ...
def sql(query: str | None = None, template_id: str | None = None) -> dict: ...
def cite(query: str, k: int = 5) -> dict: ...
# amendment A8 (00-overview):
def compare_interventions(scenario_id: str, intervention_ids: list[str]) -> dict: ...
def top_critical_elements(region: str, n: int = 10) -> dict: ...
def resolve_site(lat: float, lon: float) -> dict: ...        # helper, not in TOOL_SCHEMAS
# spec 07 owns: def causal_query(...) -> dict
```

### Env vars (`config.py`)

| var | required | default | meaning |
| --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | yes | — | SDK reads it; startup fails loud if missing |
| `DUCKDB_PATH` | yes | `data/duck/grid.duckdb` | opened read-only |
| `COPILOT_MODEL` | no | `claude-opus-5` | model id |
| `COPILOT_EFFORT` | no | `medium` | `output_config.effort` |
| `VOYAGE_API_KEY` | no | unset | enables dense retrieval |
| `CORPUS_DIR` | no | `copilot/corpus` | |
| `ASK_MAX_ITER` | no | `8` | |
| `ASK_DEADLINE_S` | no | `90` | |
| `CORS_ORIGINS` | no | `http://localhost:5173` | Vite dev origin |
| `PORT` | no | `8000` | |

Run: `uv run uvicorn copilot.app:app --port 8000 --reload`.

## Acceptance criteria

1. `GET /health` returns `ok: true`, lists all 16 contract tables, and `corpus_chunks > 500`.
2. `GET /scenarios` returns exactly the four scenario ids `uri_2021, beryl_2024, helene_2024, forecast_72h` with `has_cascade` and `has_predictions` true for `uri_2021`.
3. Every `/layers/{name}` in the table returns 200 when its artifact is built, or the shared 503 `unavailable` envelope with `details.reason: "not_built"` when it is not, in < 300 ms warm; `lines` for Texas is < 3 MB gzipped.
4. `POST /site-score` returns the persisted `site_scores` row described in its route row above — it is a persisted read and never calls `score_site` in the request (see §Routes, 2WKG-172). The previous criterion here asserted the opposite (that the route was a pass-through returning the Python function's dict, tested by equality) and named a cascade POST route that does not exist; it is removed (D-3b).
5. `sql` rejects every statement in `eval/sql_denylist.txt` (INSERT/UPDATE/DELETE/DROP/ATTACH/COPY/PRAGMA/multi-statement/`SELECT … ; DROP`) with a 4xx-shaped tool error and never mutates the DB (file hash unchanged after the run).
6. `POST /ask` streams at least one `tool_call` event before any `text` event containing a digit, for every question in `eval/questions.yaml`.
7. For the two demo questions, the emitted tool-call sequence matches the expected trace (order-insensitive within a turn) in `eval/questions.yaml`, and `done.verified == true`.
8. `verify.py` catches a planted violation: an answer with a made-up number (`"reduces loss-of-load by 999 MWh"`) yields `unverified_numbers: ["999"]` — unit test.
9. A regulatory question ("What does 10 CFR 100 require for population density?") produces a `cite` call and the answer contains `[10cfr100 p.N]` where `N` is a page the `cite` result actually returned.
10. A question the tools cannot answer ("What will natural-gas prices be in 2030?") gets an answer that says the tools cannot produce that, with no numbers, and `done.tools_used` is empty or `["cite"]`.
11. Tool timeout is surfaced: with `run_cascade` monkey-patched to sleep 30 s, the stream emits `tool_result{ok:false}` and the text says the cascade timed out; no `lost_load` number appears.
12. Second consecutive `/ask` shows `usage.cache_read_input_tokens > 0`.
13. p50 end-to-end for the demo questions < 12 s, p95 < 25 s on the demo laptop with warm DuckDB.
14. `eval/run_eval.py` runs all questions and writes `eval/report.md` with pass/fail per criterion 6–10; the demo Q&As must be green before rehearsal.
15. **Mutation probes (each must turn red, run in CI as `pytest -m mutation`, reset after):**
    - (a) comment out the `is_error: true` branch in `run_tool`'s timeout handler → criterion 11 must fail (the stream no longer emits `tool_result{ok:false}`).
    - (b) replace the `sql` denylist with an accept-all → criterion 5 must fail on `COPY (SELECT 1) TO 'x.csv'` (this is the case `read_only=True` does **not** stop — verified on duckdb 1.5.5), and the DB-hash check must catch a file write if the probe targets the DB path.
    - (c) delete the regulatory-claim guard in `verify.py` → a fixture answer that mentions "10 CFR 100" with no `cite` call must flip from `verified=false` to `verified=true`, failing the unit test that pins `reason="regulatory_claim_without_cite"`.
    - (d) drop `cache_control` from the `system` block → criterion 12 must fail (`cache_read_input_tokens == 0` on the second `/ask`).
    - (e) set `ping=0` on `EventSourceResponse` → a 12 s idle-stream test asserting at least one `:`-comment line must fail.
    If any probe stays green, the corresponding criterion is an assertion that cannot fail and must be rewritten before it counts.

## Demo hook

Demo step 5 is entirely this service ("Ask the copilot: *Why this site over the one near Houston?*"). Step 4's site card and counterfactual numbers come from `/site-score` and `/cascade`; step 2's choropleth from `/layers/outage_risk` + `/layers/eaglei`; step 3 from `/layers/cascade`; step 6 from `/layers/national_hex`.

### Demo Q&A pairs and expected tool traces

**Q1 — "Why this site over the one near Houston?"**
Context: `scenario_id=uri_2021, hour=3, selected_site_id=<#1 ranked TX coal site>, compare_site_id=<the candidate in Harris/Fort Bend county>, unit_mw=300`.

Expected trace:

1. turn 1 (parallel): `score_site(selected_site_id, 300, "uri_2021")`, `score_site(compare_site_id, 300, "uri_2021")`
2. turn 2 (parallel): `cite("population density exclusion area population center distance siting criteria", 5)` → expect hits in `10cfr100` and `regguide-4.7`; optionally `cite("cooling water source availability nuclear siting")`.
3. turn 3: final text. Must contain: both `safety_score`s and `grid_value_score`s, the two `lol_reduction_mwh` values, the `safety_flags` of the Houston site (expected: population-density flag, possibly floodplain/hurricane), `congestion_relief_pct` for the winner, a `[10cfr100 p.N]` citation on the population-density sentence, and the critical load protected (e.g. Fort Hood / Fort Cavazos from `critical_loads_protected`).

Expected answer skeleton (numbers are placeholders resolved by the tools):

> Recommend **{name_A}** over the Houston-area candidate **{name_B}** for a 300 MW unit under Winter Storm Uri.
> - Safety: {A.safety_score} vs {B.safety_score}. {B} fails the population-density screen ({flag}); 10 CFR 100 requires siting that accounts for population density and center distance [10cfr100 p.N].
> - Grid value: {A.lol_reduction_mwh} MWh loss-of-load avoided vs {B.lol_reduction_mwh}; congestion relief {A.congestion_relief_pct}%.
> - Critical loads: {A.critical_loads_protected}.
> Risks: {A.safety_flags…}.
> Tools: score_site ×2, cite ×1.

**Q2 — "Where should the next 2 GW of firm generation go in Texas and why?"**
Context: `scenario_id=uri_2021` (or `forecast_72h`), no selection.

Expected trace:

1. turn 1: `sql("SELECT s.site_id, s.name, s.county_fips, sc.safety_score, sc.grid_value_score, sc.lol_reduction_mwh FROM site_scores sc JOIN site_candidates s USING(site_id) WHERE sc.scenario_id='uri_2021' AND sc.unit_mw=1000 ORDER BY sc.grid_value_score DESC LIMIT 5")`
2. turn 2 (parallel): `score_site(top1, 1000, "uri_2021")`, `score_site(top2, 1000, "uri_2021")` (two 1 GW units = 2 GW; the model must not sum MWh itself — it reports both numbers separately)
3. turn 3: `cite("coal plant sites nuclear conversion advantages transmission infrastructure", 5)` → `doe-c2n-2022`/`doe-c2n-2024`; `cite("federal land reactor authorization executive order")` → `eo-14301`/`eo-14302`.
4. turn 4: final text naming the two sites, their scores, `lol_reduction_mwh` each (stated separately, not summed), `blackstart_reach_mw`, the regulatory path per site with citations, and the top risk per site from `safety_flags`.

Guard: if the answer contains a total MWh not present in any tool result, criterion 7 fails (this is the exact failure mode the never-compute rule is for; the eval asserts it).

**Q3 — "Which three substations create the greatest cascade risk for critical facilities?"** (prior briefing example; A8)
Context: `scenario_id=uri_2021`, no selection.

Expected trace:

1. turn 1: `top_critical_elements("ERCOT", 10)` (the model asks for 10 and filters to `kind == "bus"` with non-empty `critical_loads_lost` when reporting; it must not call `run_cascade` per element — the ranking is precomputed from `cascade_runs`).
2. turn 2 (optional, parallel): `sql("SELECT cl_id, name, kind FROM critical_loads WHERE cl_id IN (...)")` to name the stranded facilities.
3. turn 3: final text naming three `bus` element ids (with `buses.name` if resolved), each with its `lost_load_mw` and the critical facilities in `critical_loads_lost`, stated separately — no totals. If `partial: true` or fewer than three buses strand a critical load, say so and list what exists.

Guard: any `lost_load_mw` in the answer must appear verbatim in the `top_critical_elements` result (number trace); a `run_cascade` call in this trace fails criterion 7.

**Regression questions (in `eval/questions.yaml`, not in the demo):** "Which Texas counties are at highest outage risk in the next 72 hours?" (`sql` or `predict_outage` on top counties + driver), "What happens if line {L} trips at hour 3 of Uri?" (`run_cascade`), "Which ten lines give the cheapest new MW in ERCOT and by which technology?" (`top_lines("ERCOT","any",10)`; the spec 08 line-upgrade screen), "Compare the #1 site with DLR on its serving line" (`compare_interventions("uri_2021", ["site:<id>", "line:<id>"])`; model reports both deltas, never a difference it computed), "How does the predicted Uri outage compare to what actually happened in {county}?" (`predict_outage` + `sql` on `eaglei_outages` — model reports both, never a delta it computed).

## Evaluation checklist

- [ ] All 14 acceptance criteria green in `eval/report.md`.
- [ ] Number trace: 0 unverified numbers on Q1 and Q2 across 5 runs each (model nondeterminism — run 5×).
- [ ] Citation trace: every `[doc p.N]` resolves; no regulatory keyword without a `cite` call.
- [ ] No answer summed/averaged tool numbers (manual read of 5 Q2 runs).
- [ ] Refusal-to-guess: the out-of-scope question and the tool-timeout case both produce an honest "can't" line.
- [ ] Tool-call hygiene: parallel calls returned in one user message; `is_error` used on failures; every tool_result ≤ 8 KB.
- [ ] Latency: p50 < 12 s, p95 < 25 s.
- [ ] Cache hit on second question.
- [ ] Logs contain no API keys; `asks.jsonl` is gitignored.
- [ ] `COPILOT_MODEL=claude-sonnet-5` run of the eval also passes (cheap fallback if Opus rate limits during the demo).

## Risks / unknowns

- **Engines not done in time.** Mitigation: tools read precomputed tables; a `make seed-demo` populates `site_scores`, `cascade_runs`, `outage_predictions` for `uri_2021` from whatever the engine lanes have by Saturday night. The copilot demo only needs `uri_2021` rows.
- **Model narrates a computed number anyway** (e.g. sums two MWh). The verifier catches it post hoc and the UI badge shows it; the prompt says "state separately". If it recurs in eval, add a one-line few-shot in the system prompt showing the "separately" phrasing. Do not add more rules than needed — over-prescription degrades Opus 5.
- **BM25 misses a legal phrase** (e.g. the query says "population density" but the rule says "population center distance"). Mitigation: `cite` runs two rewordings when the top score is low (< 0.3 of max) and RRF-merges; and the Voyage upgrade path exists.
- **PDF text extraction quality** for the Federal Register PDFs (two-column). `pypdf` may interleave columns; if so, fall back to `pdfplumber` for those docs only. Check by eyeballing 3 chunks per doc during ingest.
- **Rate limits / API outage during the demo.** Keep `COPILOT_MODEL` switchable and the two demo answers cached as a last resort (`eval/cached_answers/`), replayed through the same SSE emitter so the UI path is identical — label as cached in the log; never present cached as live to the judges.
- **Anthropic SDK drift.** Shapes used here (`messages.stream`, `thinking={"type":"adaptive"}`, `output_config.effort`, `strict` tools, no prefill, no forced tool_choice, `stop_reason=="refusal"`) were introspected against the installed `anthropic` 1.4.0 on 2026-09-05 (see `docs/specs/verification/05-06.md`). Pin `anthropic>=1.0` — the root `pyproject.toml` currently says `anthropic>=0.40`, which admits the pre-1.0 API (bump it) — and run the health check on install. Not exercised live this session (no API key in the checkout): the 400s on `temperature`/prefill/forced `tool_choice`, and the model ids themselves — the skill table is the source; `/health` calling `models.retrieve` is the runtime guard.
- **Resolved 2026-09-05:** both `list_cosine_similarity` and `array_cosine_similarity` exist in duckdb 1.5.5; the spec uses `array_cosine_similarity` on the `FLOAT[1024]` column. Irrelevant on the BM25-only default.

## Weekend time-box (hours)

| Block | Hours | Deliverable |
| --- | --- | --- |
| Sat AM | 2 | `app.py`, `config.py`, `db.py` with SQL guard, `/health`, `/scenarios`, static `/layers/*` from DuckDB |
| Sat PM | 3 | tool schemas + impl wrappers over precomputed tables; `/cascade`, `/site-score`, `/lines/top`, `/predict`, `/elements/critical`, `/compare` (A8) |
| Sat PM | 2 | corpus fetch script, ingest, BM25 `cite`, manifest |
| Sat eve | 3 | `/ask` loop with SSE, timeouts, caps, system prompt v1, `verify.py` |
| Sun AM | 2 | `eval/questions.yaml` + `run_eval.py`; iterate prompt on Q1/Q2 until 5/5 verified |
| Sun PM | 1 | scenario-dependent layers (`outage_risk`, `cascade`, `sites`, `eaglei`) wired to real engine outputs; cache |
| Sun PM | 1 | optional Voyage dense path if BM25 eval misses; cached-answer fallback |
| Sun eve | 1 | rehearsal with the frontend, latency check, logs review |
| **Total** | **15** | |
