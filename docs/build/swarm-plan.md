---
title: "flux — swarm build plan (honesty-gated)"
status: draft
created: 2026-09-05
updated: 2026-09-05
related:
  - "[[converging-swarm-target]]"
  - "[[../specs/00-overview]]"
---

# flux swarm plan

Execution pattern borrowed from Buckeye's `swarm-honesty-orchestrator`: an orchestrator that
writes only markdown, implementation subagents in isolated git worktrees on file-disjoint
units, and an **independent honesty-analyst** with no implementation context gating every PR
with behavioral probes. The fitness function is the frozen gate set in
`converging-swarm-target.md`; this file is the DAG and the operating procedure.

## Units (one PR each, branch `swarm/flux-u<N>` → `swarm/flux`)

| Unit | Spec | Owned paths (exact) | Depends on | Gate(s) it must turn green |
|---|---|---|---|---|
| U0 gates + contract | 00, target | `gates/**`, `pipelines/schema.py`, `docs/build/freeze-manifest.json`, CI workflow | — | G_ENV, G_HYGIENE, all other gates exist and are RED with neg-controls proven |
| U1 data ingest | 01 | `pipelines/**` (except schema.py), `scripts/data/download.sh` | U0 | G_INGEST |
| U2 twin build | 03 §build | `twin/build.py`, `twin/params.yaml` | U1 | G_TWIN |
| U3 outage model | 02 | `models/outage/**` | U1 | G_OUTAGE |
| U4 cascade sim | 03 §cascade | `twin/cascade.py`, `twin/tools.py` | U2 | G_CASCADE |
| U5 siting engine | 04 | `siting/**` | U4 | G_SITING |
| U6 line upgrades | 08 | `pipelines/line_upgrade.py`, `lines/**` | U1, U2 | G_LINES |
| U7 copilot | 05 | `copilot/**` | U3, U4, U5, U6 (tool wrappers may stub-fail loudly until deps merge) | G_COPILOT |
| U8 frontend | 06 | `web/**` | U7 routes (may develop against fixtures written by U0, never against baked answers) | G_WEB |
| U9 causal layer | 07 | `causal/**` | U3, U4 | contributes `causal_query` to G_COPILOT; C2 slideware stays labeled |

Waves: **W0** = U0 (foreground, merge before fanout). **W1** = U1. **W2** = U2 ∥ U3.
**W3** = U4 ∥ U6. **W4** = U5 ∥ U9 ∥ U7 (U7 starts on U3/U4/U6 wrappers, adds U5 last).
**W5** = U8. The critical path is U0→U1→U2→U4→U5→U8, matching `00-overview.md`.

## Per-unit procedure

1. Orchestrator creates the worktree explicitly (never the Agent tool's own worktree mode,
   which branches off `master`): `git worktree add .worktrees/u<N> -b swarm/flux-u<N> swarm/flux`.
2. Implementation subagent prompt contains: worktree path + base SHA; bootstrap (`uv sync`,
   `pnpm --dir web install`); ground-truth reads (the unit's spec, `00-overview.md` amendments,
   the target's gate row); EXACT file scope; DO-NOT list (every other unit's paths, `gates/`);
   anti-goals verbatim; the gate command and expected GREEN output; commit format
   `u<N>: <what>`; escalation protocol (write `.notes/u<N>/escalation.md` and stop when a spec
   contradiction, an unavailable dataset, or scope ≫ budget appears — never invent).
3. Subagent must persist proof under `.reports/u<N>/`: `gate-command.txt`, `gate-output.txt`
   (real timestamps, real row counts), `env.txt`, and for U7/U8 an HTTP transcript.
4. Orchestrator dispatches the **honesty analyst** (separate subagent, no implementation
   context) with: the diff, the spec, the target's gate row, the anti-goals, and the probes
   below. Verdict file `.reports/honesty/u<N>/verdict.txt` with APPROVE | BLOCK.
5. Merge only on APPROVE; merge message references the verdict path. BLOCK → follow-up
   subagent with the analyst's required actions, then a fresh analyst pass.

## Honesty-analyst probes (adapted from the Buckeye template)

- **P1 tighten-assertion.** Make one gate assertion stricter; the gate must go RED. Reset.
- **P2 break-prod.** Mutate the unit's production path per its spec's "break-it" probes
  (e.g. U4: set `line_failure_prob` to 0; U5: swap the with-unit and baseline nets; U7: strip
  the number-trace verifier; U8: feed a fixture with an extra tripped element). The matching
  gate must go RED. Reset after each.
- **P3 remove-mock.** Any mock of DuckDB, HTTP, or the Anthropic client in tests = BLOCK
  (real DuckDB file, real spawned FastAPI, real API or SKIPPED-ENV). Timer mocks are fine.
- **P4 re-run.** Run `.reports/u<N>/gate-command.txt` yourself; exit code, counts, and timings
  must match the subagent's transcript within reason. Fabrication patterns (placeholder
  timestamps, `<n>` counts) = BLOCK.
- **P5 scope-dodge.** `git diff <base>..HEAD --stat` must equal the declared scope; any file
  under `gates/` or another unit's paths = BLOCK naming the file.
- **P6 anti-goal sweep.** Grep for baked answers (`demo_fixtures`, literal county names in
  prompts, hard-coded scores), silent fallbacks (`except: pass`, default returns on failure),
  secrets, and unverified pitch claims copied into UI/system-prompt text.
- **Content probe (U7 system prompt, U8 copy).** Every regulatory or market sentence must map
  to a `docs/specs/verification/` VERIFIED row; one unverified sentence = BLOCK.

## Orchestrator rules

- Writes markdown only: this plan, prompts, `.notes/progress.md`, verdict summaries.
- Contracts first (U0), inventory before fanout, sequential recovery when parallel units stall.
- Never lets a green gate stand in for an APPROVE, and never lets an APPROVE stand in for a
  green gate; both are required per PR.
- Records every Joshua-gated decision it hit in `.notes/decisions-needed.md` instead of
  resolving it.
