---
name: flux-development
description: Implement and verify Flux using its amended technical contract and pragmatic hackathon workflow. Use for work in Wyzard1004/flux, not Buckeye operations.
---

# Flux development

Locate the Flux checkout by its `Wyzard1004/flux` remote. On Joshua's laptop it
is `/Users/joshua/buckeye-swarm/flux`. Resolve the paths below against that
checkout, not the current chat directory or a global skill symlink.

## Read the contract first

Read `CLAUDE.md`, `docs/specs/README.md`, the complete amended shared contract
in `docs/specs/00-overview.md`, the applicable feature spec, and
`docs/specs/VERIFICATION.md`. The amended overview is the current authority for
shared technical contracts. `DEPENDENCIES.md` records environment and data
evidence; verify any claim needed for the work rather than treating an
installed dependency as proof of product behavior.

For multi-feature delivery, read `docs/build/converging-swarm-target.md` and
`docs/build/swarm-plan.md`. They preserve the feature DAG and verification
intent, but do not create frozen gate baselines, numerical delivery thresholds,
or mandatory approval rituals.

## Execute the appropriate scope

The primary orchestrator coordinates work, dependency order, integration, and
status only. All execution—including code, documentation, tests, repository
commands, and external task writes—goes through `gpt-5.6-terra` workers.
Assign workers file-disjoint scopes and use isolated worktrees for substantive
implementation when that avoids overlap. Record each worker's scope and base
revision when a worktree is used.

For a focused change, follow the applicable feature ownership and run checks
that exercise the behavior changed. Prefer real database and HTTP paths when
they are affected; use the actual browser path for frontend behavior. Select
deeper checks, mutation probes, and peer review when change risk warrants
them. Do not make health/doctor checks routine: use them after setup changes or
for actual connectivity troubleshooting.

Record commands and results honestly. Missing model access is reported as
unavailable or `SKIPPED-ENV`; a failed fetch or solve is an explicit failure,
never a plausible default. Do not invent numbers, citations, tool results,
execution transcripts, or data.

Use the actual app's browser path for frontend verification. The configured
build command becomes meaningful only once the app entrypoint and TypeScript
configuration exist. Use existing computer-use/browser capabilities when
available; install test browser dependencies when the implementation needs them.

## Integrations and boundaries

Use the configured Linear MCP to identify the correct Flux workspace and issue
before updating work tracking. Use `gh` and Git for `Wyzard1004/flux`;
verify repository access and PR base before writing remotely. Respect the
user's requested scope for comments, issue creation, pushes, and merges.

Developer-owned credentials stay in their native stores/environment. The
repo's Joshua-owned product, API-spend, and pitch decisions remain explicit
decisions; do not infer them from access to an account.

Buckeye material is reference knowledge only. Do not write Flux material into
Buckeye repositories and do not reuse Buckeye credentials, architecture,
application data, or VM workflows. A separately requested Buckeye operation
follows its own repository instructions.
