# Flux PR review brief (bobvi criterion)

You are reviewing ONE pull request in the Flux hackathon repo (GitHub 2WKG/flux, default branch `master`).
Your checkout is already at the PR head. Do NOT commit, push, or write to Linear. Temporary edits for mutation probes must be restored with `git checkout -- .` before you finish. Your only output is the report below, posted as ONE pull-request comment (never an approval or a request-changes review) or written to the output path you were given.

## Authority (read first, in the worktree)
- `CLAUDE.md` (repo rules: no fabricated results, explicit unavailable errors, DuckDB contract, provenance labels)
- `docs/specs/00-overview.md` (amended shared contract wins over feature specs) and the feature spec the PR implements (copilot work → `docs/specs/05-copilot.md`, frontend/map → `06-frontend.md`)
- The PR body and the Linear ticket id in the branch name

## The review standard: the "bobvi pass"
Swarm-authored PRs tend to prove internal consistency (code + tests + mocks written by the same process) and be blind to reality. Grade against these six legs, each PASS / FAIL / N/A with evidence:

1. **Reality contracts** — code consuming an external system's shape (DuckDB tables, FastAPI envelopes from `00-overview.md`, corpus files, CRS/units) must match the REAL contract, not a hand-written mock. Check the mock/fixture against the spec'd table/envelope schema.
2. **Live proof** — did the author actually run what the PR body claims? RE-RUN the PR's stated verification commands yourself in the worktree (`uv run --extra dev pytest ...`, `ruff check`, `ruff format --check`). If `uv sync --frozen --extra dev` is needed, run it. Record exact commands + pass/fail counts. A claim not reproduced = FAIL.
3. **Scope collapse** — claim surface == proof surface. Does the PR title/body/docstrings claim anything the tests don't prove (e.g. "audit-ready", "deterministic", "bounded")? Unprovable capability must be behind a loud named error, not implied.
4. **Recovery walk** — enumerate every failure state the code can produce (missing table, empty corpus, malformed id, out-of-bounds). Each must yield the shared unavailable/validation envelope with a named reason, never a plausible default or a 500. Check with a real request/test where cheap.
5. **Substrate check** — if the base is not `master` the PR is STACKED on another open PR. Check whether the base branch drifted (compare with `origin/master` and the base ref); note conflicts, duplicated files, or contracts the base changed underneath.
6. **Day-2 seams** — bounds on inputs, no unbounded loops/reads, deterministic tie-breaking actually specified, errors degrade loudly, no credentials/data files committed.

## Assertions that cannot fail (mandatory mutation probe)
Pick the 2–3 most load-bearing assertions in the PR's tests and MUTATE the code (temporarily, then `git checkout -- .` to restore) to confirm each test goes RED. Classes to hunt: source-text `toContain`/`in source` pins; exit-code/status-only assertions blind to the harm; functions tested in body but never wired at the call site; probes that cannot distinguish the two states. Report every assertion that stayed green under mutation. Restore the worktree and verify `git status` is clean before finishing.

## Report format (markdown)
```
# PR #N — <title>
Verdict: APPROVE | APPROVE-WITH-NITS | REQUEST-CHANGES | BLOCK
One-paragraph summary a teammate can act on.

## Reproduced verification
<exact commands + results>

## Bobvi legs
1. Reality contracts — PASS/FAIL — evidence
... (6)

## Mutation probes
| assertion | mutation | went red? |

## Findings (ranked, most severe first)
- [severity] file:line — issue — concrete fix
## Nits
```
Be concrete, cite file:line, quote the exact failing behavior. No praise padding. Never fabricate a test result.

## Mutation classes to hunt (from prior post-mortems)

- **Class A — source-text pins.** `assert "foo()" in source` is satisfied by a commented-out call and by a substring anywhere in the file. Require line-anchored or slice-scoped pins, or a behavioral test.
- **Class B — outcome assertions blind to the harm.** `exit != 0` plus a stderr substring cannot distinguish "died before doing harm" from "did the harm, then died". When the property is "X must never happen", assert on X's absence directly.
- **Class C — body-tested, wire-untested.** Both functions correct and tested, but the one call that wires them in is unpinned; commenting it out leaves the suite green. Mutate the call site, not the body. (The `tests/conftest.py` wire-coverage plugin catches the HTTP-route form of this.)
- **Class D — the probe could not distinguish the two states.** A "pre-fix must be RED" run executed post-fix code because `git stash` was a silent no-op. Before believing a before/after probe, prove the tree moved (`git diff --stat`, or grep for a token present in exactly one version).
- **Class E — the shell swallowed the exit code.** `cmd | tail` reports `tail`'s status; a wrapper ending in `date` reports 0. Use `set -o pipefail`, check `PIPESTATUS`, and confirm against the artifact the command produced, not the exit code alone.

Comment out rather than delete when mutating (deletion also breaks hollow pins, so it proves nothing), then confirm the file still parses so RED cannot come from a syntax error. A test that stays green under the mutation it exists to catch is not a test.
