# Merge gates runbook

Last updated: 2026-09-05. Owner: repo admin (William, `@Wyzard1004`) for the
ruleset and secrets; anyone with push for the workflows themselves.

## Why

Two failure patterns cost us most of the review time in the first week: stacks
that drifted from `master` until they could not merge (#57/#58/#61 sit three deep
on a base that is itself far behind; #66 merged into a feature branch instead of
`master`; #83 and others opened green against a `master` that had already moved),
and PRs whose tests exercised function bodies but never the wire, so the feature
could be unmounted with every test still green (#52's layer route, and #87's
hand-copied mirror of `copilot/tools/schemas.py` that nothing checks). CI could
not have caught any of it because there was no CI.

This PR adds the gates below as named GitHub Actions jobs, an automated bobvi
review, and the exact ruleset the admin must enable so the gates are *required*
rather than advisory. **Nothing here blocks a merge until the ruleset exists.**

## The gates (`.github/workflows/pr-gates.yml`)

Each job has a stable `name:` so it can be listed as a required status check.

| Gate | What it checks | How to fix a red |
| --- | --- | --- |
| `gate/up-to-date` | PR head is at most 20 commits behind `origin/master` and `git merge-tree` reports no conflicts. Prints the count. | `git fetch origin master && git rebase origin/master` (or merge master), resolve conflicts, push. |
| `gate/stack-base` | If the base is not `master`, the base branch must be the head of an **open** PR (otherwise the stack is orphaned). Warns if that base PR is not green. | Retarget the PR at `master` (`gh pr edit N --base master`) or reopen the base PR. |
| `gate/ruff` | `ruff check` + `ruff format --check` on the `*.py` files this PR adds/changes relative to `origin/master`. Scoped to changed files because `master` itself is not ruff-clean today (25 errors, 27 unformatted files at a4096ce); widen to `.` once master is clean. | `uv run --extra dev ruff check --fix <files> && uv run --extra dev ruff format <files>`. |
| `gate/pytest` | `uv sync --frozen --extra dev && uv run --extra dev pytest -q`, whole suite, including the wire-coverage plugin (below). | Fix the failing test. For a wire-coverage red, add a test that drives the listed route through `TestClient`. |
| `gate/web` | Only when `web/**` changed: `npm ci`, `npm run typecheck`, `npm run build`, and `node --test` over every `web/src/**/*.test.mjs`. | Fix the type/build error locally with the same commands from `web/`. |
| `gate/contract-drift` | Reruns `scripts/ci/export_tool_contracts.py` and fails if `web/src/contracts/` differs from what is committed. | `uv run --extra dev python scripts/ci/export_tool_contracts.py` and commit the result. Never hand-edit the generated files. |
| `gate/spec-authority` | If `copilot/tools/schemas.py`, `copilot/api/envelope.py`, `copilot/api/errors.py`, or `pipelines/db.py` changed, one of `docs/specs/00-overview.md`, `05-copilot.md`, `10-duckdb-contract.md` must change in the same PR. | Amend the owning spec (shared contract: 00; tool/envelope shapes: 05; tables: 10) in the PR, even if only to record the change. |
| `gate/linear-key` | Branch name **or** PR title contains `2wkg-NNN` (case-insensitive), **or** the PR carries the label `no-linear`, **or** the body has a line starting `Linear: none`. | Rename the branch/title, or declare `Linear: none (reason)` in the body for process-only PRs. |

Concurrency is per PR (`cancel-in-progress`), so pushes supersede running jobs.
`merge_group` events are accepted; the PR-specific gates pass trivially there.

### Wire coverage (`tests/conftest.py`)

The plugin patches `Route.handle` / `APIRoute.handle` to record every
`(method, endpoint)` actually served during the session and, at session end,
compares that with the routes `copilot.app.create_app()` registers. Any
registered route no test drove fails the run with the route list. Rules:

- Only enforced when `copilot.app` is importable (not on `master` today; the
  plugin is inert there and `tests/test_wire_coverage.py` skips its app test).
- Not enforced for narrowed runs (`pytest path/…`, `-k`, `-m`, `--collect-only`),
  so developers can run one file. CI runs the whole suite, which is enforced.
- `FLUX_WIRE_COVERAGE=0` disables it and says so; do not set it in CI.

What it does **not** catch: a route whose `include_router` call is deleted is
no longer registered, so the plugin has nothing to compare; the route's own
`TestClient` tests are what go red in that case (verified on the #94 branch:
commenting out `include_router(layers_router)` fails 28 layer tests). What it
catches is the complement: a route that is mounted but that no test drives
(verified: silencing the layer tests, or adding an untested route inside
`create_app()`, both fail the session with `GET /layers/{layer_name}` /
`GET /orphan-probe` listed while every test still passes).

### Contract export (`scripts/ci/export_tool_contracts.py`)

Introspects every public pydantic model in `copilot/tools/schemas.py`, emits one
JSON Schema document (`$defs` merged, sorted keys) plus TypeScript declarations
generated by a ~150-line dependency-free converter, into `web/src/contracts/`.
This replaces hand-copied mirrors such as `web/src/panels/copilot-contracts.ts`
in #87: import from `web/src/contracts/copilot-tools` instead, and let
`gate/contract-drift` prove the mirror is current.

## Bobvi review (`.github/workflows/bobvi-review.yml`)

On every non-draft PR from this repository, `anthropics/claude-code-action@v1`
reads `.github/bobvi-brief.md`, reproduces the PR's stated verification, runs
mutation probes, and posts **one** comment (never approve/request-changes). It
is advisory: mutation testing stays in the reviewer, not in a required gate, for
hackathon speed. If `ANTHROPIC_API_KEY` is not configured the `bobvi/preflight`
job emits a notice and `bobvi/review` is skipped, not failed. Fork PRs are
skipped because they cannot see secrets.

## Admin steps (William)

Joshua has push/triage but not admin, so these cannot be done from the PR.

### 1. Secret

Settings → Secrets and variables → Actions → New repository secret →
`ANTHROPIC_API_KEY`. Without it the bobvi workflow skips.

### 2. Claude GitHub App

`anthropics/claude-code-action` posts comments through the Claude GitHub App;
install it on `Wyzard1004/flux` (from a checkout with Claude Code:
`claude /install-github-app`, or via <https://github.com/apps/claude>). Until the
app is installed the `bobvi/review` job will fail at token exchange; it is not a
required check, so nothing blocks.

### 3. Ruleset on `master`

Click-path: Settings → Rules → Rulesets → New ruleset → New branch ruleset.
Name `master-merge-gates`; Enforcement **Active**; Bypass list **empty** (or
Repository admin only); Target branches → Add target → Include default branch.
Rules: **Restrict deletions**; **Block force pushes**; **Require a pull request
before merging** → Required approvals 1, Dismiss stale approvals when new
commits are pushed, Require review from Code Owners; **Require status checks to
pass** → Require branches to be up to date before merging, then add each of the
eight `gate/...` names below (they appear in the search box once this PR's
workflow has run at least once).

Or as one API call (needs admin; `gh auth status` must show the admin account):

```sh
gh api -X POST repos/Wyzard1004/flux/rulesets --input - <<'JSON'
{
  "name": "master-merge-gates",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": true,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "allowed_merge_methods": ["merge", "squash", "rebase"]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "do_not_enforce_on_create": false,
        "required_status_checks": [
          { "context": "gate/up-to-date" },
          { "context": "gate/stack-base" },
          { "context": "gate/ruff" },
          { "context": "gate/pytest" },
          { "context": "gate/web" },
          { "context": "gate/contract-drift" },
          { "context": "gate/spec-authority" },
          { "context": "gate/linear-key" }
        ]
      }
    }
  ]
}
JSON
```

`strict_required_status_checks_policy: true` is "Require branches to be up to
date before merging": GitHub itself then refuses a merge whose head is not on top
of `master`, independent of the 20-commit tolerance in `gate/up-to-date`.
`require_code_owner_review` is what makes `.github/CODEOWNERS` bite; without it
the file is documentation. To allow admins to bypass in an emergency, replace
`"bypass_actors": []` with
`[{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]`
(5 = repository admin role).

Verify afterwards with `gh api repos/Wyzard1004/flux/rulesets --jq '.[].name'`
and by opening a PR whose branch lacks a Linear key: it must show
`gate/linear-key` as a blocking red.

### 4. Admin checklist

- [ ] `ANTHROPIC_API_KEY` repository secret added
- [ ] Claude GitHub App installed on `Wyzard1004/flux`
- [ ] Ruleset `master-merge-gates` created (click-path or the `gh api` payload above), enforcement active
- [ ] All eight `gate/...` contexts listed as required, "up to date" enabled
- [ ] Code-owner review required (activates `CODEOWNERS`)
- [ ] Merge attempt on a red PR confirmed blocked

## Linear side (process only; Linear cannot block a GitHub merge)

- Issue template acceptance criteria to paste:
  - `[ ] Branch named <user>/2wkg-NNN-<slug>; PR body follows .github/pull_request_template.md`
  - `[ ] All gate/* checks green; bobvi comment read and addressed or explicitly declined in the PR`
  - `[ ] Verification commands and counts pasted from a real run on this branch`
  - `[ ] Stacked PRs list their base PR; base PR is open`
- Workflow setting: in the team's GitHub integration, enable "move issue to Done
  when the PR merges" and disable manual moves to Done so Done means merged.
- The `gate/linear-key` opt-out (`Linear: none (...)`) is for process PRs like
  this one; feature work must carry a key.

## Local equivalents

```sh
uv sync --frozen --extra dev
uv run --extra dev pytest -q                                   # gate/pytest (+ wire coverage)
uv run --extra dev ruff check $(git diff --name-only origin/master...HEAD -- '*.py')
uv run --extra dev ruff format --check $(git diff --name-only origin/master...HEAD -- '*.py')
uv run --extra dev python scripts/ci/export_tool_contracts.py --check   # gate/contract-drift
git rev-list --count HEAD..origin/master                       # gate/up-to-date (must be <= 20)
(cd web && npm ci && npm run typecheck && npm run build)       # gate/web
actionlint .github/workflows/*.yml                             # when editing workflows
```
