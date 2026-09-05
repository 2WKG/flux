## Linear key

<!-- 2WKG-NNN (also in the branch name). No issue? Write `Linear: none (reason)` and gate/linear-key accepts it. -->
Linear:

## Summary

<!-- What changed and why. Claims here must be proven in Verification below. -->

## Verification

<!-- Exact commands you ran and their counts/output. Never claim a result you did not produce. -->

```
uv run --extra dev pytest -q            # N passed, M skipped
uv run --extra dev ruff check <files> && uv run --extra dev ruff format --check <files>
```

## Bobvi checklist

- [ ] **Reality contracts**: shapes consumed from DuckDB / API envelopes / corpus files match master's real contract, not a hand-written mock
- [ ] **Live proof**: every command above was actually run on this branch; counts are pasted, not typed
- [ ] **Claim == proof surface**: the title/body/docstrings claim nothing the tests do not prove
- [ ] **Every failure state named and tested**: missing table, empty result, bad id, out of bounds -> shared unavailable/validation envelope, never a 500 or a plausible default
- [ ] **Rebased on master / base PR open**: `gate/up-to-date` and `gate/stack-base` are green, not merely tolerated
- [ ] **Day-2 seams**: bounded inputs, no unbounded reads, deterministic ordering, no data files or credentials committed

## Stacked on

<!-- `master`, or `#NNN` (the base branch must have an open PR). -->
master
