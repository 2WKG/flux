# Historical event baseline audit

**Every number below was produced by a committed generator, from the bundles in
this repository, with this repository's contract validator.** Regenerate it:

```
python scripts/data/event_baseline_requests.py \
  --events-dir docs/data/event-baseline/events \
  --output docs/data/event-baseline/requests.json
python scripts/data/event_baseline_assemble.py \
  --events-dir docs/data/event-baseline/events \
  --output docs/data/event-baseline/event_catalog.csv
python scripts/data/event_baseline_split.py \
  --events-dir docs/data/event-baseline/events \
  --output-dir docs/data/event-baseline/splits
```

The generating commit, the input bundle count, and a SHA-256 for every input
bundle are recorded in `splits/audit.json.receipt` and
`requests.json.receipt` (`capture_method: generated`).

## Status: insufficient_corpus

`splits/audit.json` reports `"status": "insufficient_corpus"`, not `pass`. The
bundle corpus in the tree today holds 40 bundles with **0 accepted
county-window records** — 23 `candidate_only` and 17 `shortfall` — so all three
splits are empty.
An audit whose every leakage check is a collision detector cannot demonstrate
anything on a corpus with no collisions, so the split generator refuses (exit
status 1) instead of reporting a vacuous pass. The declared floor is 12 accepted
rows, at least one non-singleton group, and three non-empty splits; it lives in
`scripts/data/event_baseline_split.py` (`MINIMUM_ACCEPTED_ROWS`,
`MINIMUM_NON_SINGLETON_GROUPS`) and is recorded in
`splits/audit.json.declared_minimums`.

The manifests in [`splits/`](splits/) are still written, so the state is
inspectable, but they are **not** a defensible held-out split and must not be
used as one. They will be regenerated, and the status is expected to reach
`pass`, once the remaining event-bundle PRs (#237, #238, #241, #243) land and
the corpus carries accepted records again.

Nothing downstream reads a frozen catalog: every generator above reads the
bundles under `--events-dir` at generation time, so a bundle downgraded from
`accepted` to `candidate_only` cannot survive in a regenerated artifact. On top
of the contract validator, `accepts()` refuses an accepted record whose window
does not start on the 00/06/12/18Z grid or does not span six hours.

## What was replaced, and why

An earlier revision of this document claimed a 63-county-window catalog, "the
contract validator passed all 63 canonical bundles", and 8 train / 4
calibration / 1 test manifests. None of that was reproducible here:

- the 63-bundle corpus existed only in a `/private/tmp` integration checkout at
  a snapshot (`32d006c`) that is not a commit in this repository;
- the validation was qualified as holding "using the legacy receipt
  compatibility repair (`730f6fe`)" — the head of PR #250, whose loosening of
  the receipt contract was rejected and whose PR is closed. Nothing in this
  document now depends on it;
- `requests.json` was produced by an uncommitted `/tmp/flux-460-request-frame.py`
  reading three absolute `/private/tmp` paths, so only its original worktree
  could regenerate it. That generator is now committed, repo-relative, and
  bundle-driven as `scripts/data/event_baseline_requests.py`;
- `acquisition-ledger.json` and `source-artifacts.json` described EAGLE-I
  acquisitions and weather artifacts for that phantom 63-request frame, with no
  generator and no way to check them from a checkout. They have been removed
  rather than shipped unverifiable; they belong with the acquisition run that
  actually produces them.

## What the split generator does establish

Grouping connects rows by `parent_system_id`, by reuse of a selected source row
key, and by overlapping or adjacent context windows. It never uses an annual
raw-file hash or a reused primary document as a leakage key: those legitimately
support many independent episodes.

Alongside the cross-split collision checks, `audit()` positively re-derives each
row's split from its own group key, so moving a single row — or a whole group —
between manifests fails the audit even when every group is a singleton and no
collision exists to detect. `tests/test_event_baseline_split.py` drives each of
those rules directly, including the `parent_system_id` union, the
context-window-overlap union, and the `source_evidence_status` refusal.

The manifests are for historical replay only. They establish no forecast cutoff,
forecast score, training result, or model performance claim.
