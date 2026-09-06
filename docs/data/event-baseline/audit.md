# Historical event baseline audit

**Composition base:** `ac4ae093c7c6eb9cad1b4cae9855e390ad50a0f9`.

This catalog was regenerated from the committed bundles with:

```bash
uv run python scripts/data/event_baseline_validate.py \
  --events-dir docs/data/event-baseline/events
uv run python scripts/data/event_baseline_assemble.py \
  --events-dir docs/data/event-baseline/events \
  --output docs/data/event-baseline/event_catalog.csv
uv run python scripts/data/event_baseline_split.py \
  --events-dir docs/data/event-baseline/events \
  --output-dir docs/data/event-baseline/splits \
  --controls-plan docs/data/event-baseline/events/controls/preselection-plan.yaml
```

The result has 63 county-window records: 10 accepted, 26 candidate-only, and
27 shortfalls. The accepted replay manifest has 10 rows (7 train, 2
calibration, 1 test). All 10 labels have `status="unavailable"` because their
native customer denominator is unavailable. This is a provenance and replay
baseline, not a supervised outage-label training set, forecast evaluation, or
model-performance result.

The catalog retains 46 `UncoveredLabel` rows, 17 unavailable labels, 18
covered outage windows, and two deliberately uncovered canonical rows. The
latter preserve the source metadata, event window, receipt IDs, and source-row
keys for Hurricane Ian and Idalia while refusing to promote their 15:00Z and
09:00Z source slices into canonical model labels. Their canonical rows are
aligned to the 00/06/12/18 UTC contract and remain shortfalls until complete
aligned EAGLE-I slices are acquired.

Receipts now carry the contract-required capture method, verification object,
files object, and uncertainty statement. A receipt whose bytes were not
acquired by this bundle says so explicitly; no placeholder hash, coverage
claim, denominator, or zero-outage label was invented.

The committed `acquisition-ledger.json`, `requests.json`,
`requests.provenance.json`, and `source-artifacts.json` are retained as
historical collection context. They are not a substitute for the bundle
validator or for a current raw-byte acquisition receipt. The reproducible
catalog and grouped manifests are the operative baseline artifacts for this
composition.
