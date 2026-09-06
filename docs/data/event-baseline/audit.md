# Historical event baseline audit

**Snapshot:** `32d006c0114836fcadc1abeca3908ff39ebc08cf`, assembled from the
locked 63-request frame. The catalog was generated with
`python scripts/data/event_baseline_assemble.py --events-dir docs/data/event-baseline/events --output docs/data/event-baseline/event_catalog.csv`
in the isolated integration checkout.

The catalog has 63 county-window records. It has 13 accepted records, 25
record-level shortfalls, and 25 candidate-only records. At the event level,
13 are accepted, 12 are shortfalls, and 38 remain candidate-only. Every
record has `time_series_or_grid` outage evidence; none is `not_assessed`.
The assembled bundle records have 21 complete outage coverages and 42
`UncoveredLabel` coverages. The acquisition ledger uses a more detailed
per-request state: 21 complete, 20 partial, and 22 `UncoveredLabel` entries.
Labels are either `UncoveredLabel` (43) or `unavailable` (20); this snapshot
does not claim a computed 5% label where the native denominator is absent.

The accepted rows have matched coverage, complete 24-sample EAGLE-I outage
evidence, selected source-row keys, and authoritative weather evidence. The
weather evidence registry is [source-artifacts.json](source-artifacts.json):
it rehashed 32 artifacts, has no missing **declared hashed** artifact, and
links all 13 accepted events to weather proof. It separately retains 48
receipt-only context entries without local bytes or a hash; those entries are
not proof of byte availability. The operational EAGLE-I ledger is
[acquisition-ledger.json](acquisition-ledger.json): all 63 entries declare
`exhaustive_annual_stream` and `acquisition_complete: true`. Raw annual files
are durable ignored cache under `data/raw/event-baseline/`; their hashes and
repository-relative locations are retained in the ledger. The ledger source
SHA-256 is `a8fdb5ed99e6a5e77afb60267d01407c2298a14b47452e3c86f3c2b3057c3675`.

The acquisition request frame is [requests.json](requests.json), with its
generator command, input corpus, and hashes in
[requests.provenance.json](requests.provenance.json). Its canonical tuple
digest is `75a2044d89dbe66ac82c8d72c6c6b77eea753b7eb42c3e6952df93fa772ffe2e`.
The request artifact SHA-256 is
`bbcb3e15ef84c045b0dd71117af72c74fb89b33eb93dc5956d04ff6b4b68ab8e`.

The contract validator passed all 63 canonical bundles using the legacy
receipt compatibility repair (`730f6fe`). The grouped manifests in
[`splits/`](splits/) contain 8 train, 4 calibration, and 1 test accepted
county-window rows. The split generator rejects accepted rows with incomplete coverage, an
`UncoveredLabel`, absent source-row keys, parent-system overlap, selected-row
reuse, or overlapping/adjacent context windows across splits. It never uses
an annual raw-file hash or a reused primary document as a leakage key.

The grouped manifests are for historical replay only. They do not establish a
forecast cutoff, forecast score, training result, or model performance claim.
