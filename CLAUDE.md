# Flux

Flux is the product, repository, and package. Work locally in this checkout.
GitHub: `2WKG/flux`; default branch `master`. (The repository moved out of its
original personal org; GitHub still redirects the old path, so older links resolve
even though the org written in them is stale.) Check the actual branches, upstream
state, and existing work before using a branch or worktree.

## Context and authority

Start with `docs/specs/README.md`, then the complete amended
`docs/specs/00-overview.md`, the applicable feature spec, and
`docs/specs/VERIFICATION.md`.

**Authority lattice** — four documents used to claim the top of it in four
different ways. One order now, highest first:

1. **Executable source, migrations, generated wiring, and tests.** They are the
   fact. When prose disagrees with them, the prose is wrong and gets corrected
   with the change. `docs/specs/spec-code-reconciliation.md` is the standing
   ledger of known disagreements and how each was resolved.
2. **`docs/specs/10-minnesota-demo.md` and `docs/specs/10-duckdb-contract.md`,
   within what they explicitly supersede** — Minnesota geography, scenarios,
   model mode, storage/identity contract, and demo acceptance language.
3. **`docs/specs/00-overview.md`** for everything else in the shared technical
   contract: table names, column names, tool signatures, scenario IDs, and the
   route inventory. It wins over specs 01–09 and over the design and build docs.
4. **Downstream feature specs (01–09), design docs, and runbooks.**

The build documents describe a pragmatic delivery workflow and must not revive
superseded frozen-gate or quantitative requirements.

Read executable source before changing existing behavior. A written command or
planned check is not evidence that it exists or passes.

Use `.agents/skills/flux-development/SKILL.md` for implementation guidance.

## Local development

- Python 3.12: `uv sync --frozen --extra dev`; use `uv run --extra dev` for
  development commands so the test and lint extras are available.
- Frontend: `pnpm install --frozen-lockfile` from the frontend's package root.
- DuckDB is the shared storage contract. Resolve contradictory planning prose
  against the amended overview before implementing a different database.
- Keep downloaded data, database files, local environments, and credentials
  out of Git. Credentials come from the developer environment; never copy
  credentials from another repository.

Run a health/doctor command only after a setup change or while diagnosing an
actual connectivity problem. It is not routine implementation ceremony.

## Product invariants

- ACTIVSg2000 is synthetic topology; label it in user-visible results.
- Current-version AUX coordinates must match the electrical case. The June-2016
  bundle has different bus numbering.
- Use pandapower DC power flow; include the 847 impedance branches in the
  transformer overload path. The installed case is incompatible with
  lightsim2grid.
- Copilot numbers come from tool results. Regulatory claims require supporting
  sources; `[UNVERIFIED]` claims remain unresolved.
- Missing data, failed solves, and missing API access produce explicit errors
  or reported unavailable checks, never plausible defaults or fabricated
  results.

## Hackathon workflow

The primary orchestrator coordinates scope, dependencies, integration, and
status. All execution—including code, documentation, tests, repository
commands, and external task writes—goes through `gpt-5.6-terra` workers. Use
file-disjoint scopes and isolated worktrees for substantive work when they help
prevent overlap. Keep the feature ownership and dependency DAG in
`docs/build/swarm-plan.md` current as implementation proceeds.

Each worker reads the applicable spec and records the commands it actually ran.
Choose verification in proportion to the changed behavior: exercise real
DuckDB, HTTP, model, and browser paths when those paths are affected; use a
focused behavioral check for a focused change. Peer review and deeper probes
are useful for risky or load-bearing changes, but are not mandatory per-PR
gates. Never claim a result, test outcome, dataset, citation, or tool response
that was not produced.

## Scope of Buckeye reuse

Buckeye material is reference knowledge only. Flux may borrow ideas such as
clear ownership, worktree isolation, and behavioral verification, but it does
not inherit Buckeye architecture, gates, VM workflows, repositories, data, or
credentials. Do not write Flux material into a Buckeye repository or reuse
Buckeye credentials.

Linear uses the developer's globally configured `linear` MCP connection.
Identify the correct workspace/project before changing issues. A connected tool
does not prove project access or authorize sending messages.

`CLAUDE.md` is canonical; `AGENTS.md` links to it for Codex.
