---
name: flux-orchestration
description: Coordinate bounded Flux work through Terra workers with clear authority, ownership, lightweight reporting, and reviewable handoffs.
---

# Flux orchestration

Use this skill when Flux work needs a worker, more than one independent worker, or coordination across a shared contract. The root agent owns the plan, integration, and final user response. Terra workers perform all implementation and final verification. A simple explanatory question needs no worker: the root answers it directly.

## Routing and roles

- Give any code, documentation, investigation, or verification change to one Terra worker. The root does not take an implementation shortcut for a small change.
- Use one Terra worker for a small coherent task. A short paragraph containing the objective, authority, scope, acceptance check, and expected handoff is enough.
- Use separate Terra workers only for genuinely independent work. Give each a non-overlapping claim over files **and** shared interfaces, schemas, database/runtime state, deployment surfaces, and contracts.
- Use an Astra sub-orchestrator only for a distinct, sufficiently large stream that needs its own coordination. It still uses the same brief and reporting rules; the root remains accountable.
- If work shares a file, contract, runtime state, or dependency sequence, keep one owner or order the work. Do not parallelize it merely because the filenames differ.

## Before delegation

1. Read the current issue or request, contract, affected local guidance, working state, and relevant existing claims.
2. State the observable outcome and identify shared interfaces or runtime concerns before splitting work.
3. For new Linear issue work, use its exact `gitBranchName`. For an existing associated branch, resume that branch. Do not infer a branch, issue ID, or sync state when Linear is unavailable.
4. Record every parallel claim: owner, files and shared surfaces, dependency, and expected output.
5. Give the worker authority for normal in-scope choices. Ask the user only when an action is outside existing authorization; do not ask again for an authorized PR or Linear write.

Read-only inspection of Buckeye materials is allowed when relevant. Never write Flux material into Buckeye-associated repositories, and never borrow Buckeye secrets, control-plane procedures, virtual machines, or sandbox tooling.

## Scaled worker brief

For a small task, use one paragraph that makes these facts explicit: objective, inputs/authority, owned files and shared interfaces, dependencies, acceptance/validation, and expected output. Use the template below only when it makes a larger or cross-stream task clearer.

```md
## Assignment: <short name>

**Objective and contract**
<observable outcome; relevant issue, interfaces, and verified facts>

**Authority and inputs**
<branch, paths, permitted tools/actions, routine decisions the worker may make>

**Owned scope**
<files plus contracts, schemas, runtime/state, or deployment surfaces owned by this worker>

**Dependencies and non-goals**
<prerequisites, claims to respect, out-of-scope work, and independent work that may continue>

**Acceptance and output**
<success criteria, proportionate validation, patch/findings, and handoff evidence>
```

## Worker behavior and status

Workers inspect the local state that affects their assignment, preserve unrelated changes, and stay within their claim. They may make routine in-scope decisions without waiting. They report `ready` when they can start and `blocked` with the exact missing input, collision, or failing dependency.

When one dependency is blocked, workers continue other independent work inside their owned scope. A worker stops for coordinator direction only when it would alter the contract, collide with a claim, require an unapproved external action, or prevent an acceptance criterion.

Before retrying a write whose outcome is unknown, read back the target state. Do not repeat a potentially duplicate write blindly.

## Completion report

Use this compact report for complete, partial, or blocked work:

```md
## Review report: <assignment>

**Status:** complete | partial | blocked | needs-review

**Result**
<outcome tied to the objective>

**Scope**
<changed files and shared surfaces; confirm the claim held>

**State**
- Applied: yes/no/unknown
- Tested: yes/no/partial — <checks and results>
- Pushed: yes/no/unknown
- Merged: yes/no/unknown
- Linear synced: yes/no/unknown

**Blockers, risks, and handoff**
<exact missing item, material limitation, remaining independent work, and next coordinator action; or none>
```

`complete` means all acceptance criteria and required publication/synchronization for this assignment have been verified. Use `partial` or `blocked` when checks, push, merge, Linear sync, or another required outcome remains pending.

## Integration and publication

The root checks that all work matches the contract, claims did not collide, and reports accurately distinguish applied, tested, pushed, merged, and Linear-synced state. Terra performs the final validation command or check; the root reviews the evidence and reports it.

Keep each PR to one behavior or reviewable documentation change. Separate independent feature work, and do not fold an existing review-fix PR into a different change. A large inherited dependency diff is not small: draft it with explicit dependencies or hold it until its scope can be narrowed.

For reviewable new issue work, open the authorized PR to `master`; do not auto-merge. Perform authorized Linear writes without an extra approval step, then read back when the result is uncertain. Do not post teammate comments without explicit authorization.
