# Physical-inventory offline acceptance receipt

Run `python scripts/verify_physical_inventory.py --artifact <artifact.json> --state tx --expected-version <version> --receipt <receipt.json> [--published-artifact <published.json.gz>]` after a state ingest lane writes a contract-11 physical inventory artifact. A state selector such as `mn` also accepts a scoped artifact geography such as `mn:mille-lacs-county`; `tx` accepts the canonical `us-tx` form. That scope remains visible in the receipt and is never promoted to statewide coverage.

The verifier checks the immutable artifact checksum and contract, then reconciles
each state coverage row with the normalized asset count. It retains source IDs,
versions, record identities, source geometry/accuracy metadata, and
source-backed terminal/edge counts in the receipt.

A source query's returned count is deliberately recorded as
`source_returned_count`. It never becomes a statewide completeness denominator.
Only `denominator_basis: authoritative_state_class:<state>` plus
`source_scope: statewide:<state>` can support an offline complete-class claim;
even then, every counted asset must retain source geometry.

The verifier rejects an over- or under-reconciled authoritative denominator,
coverage rows that lose normalized assets, normalized assets with no state
coverage row, and derived geometry whose accuracy basis does not name its source
provenance. A nullable unavailable count remains explicitly reported as
unknown/unreported instead of treated as zero. Fabricated geometry metadata on an
unavailable asset and a CRS PROJ cannot resolve are rejected by contract 11's
`validate_artifact`, which the verifier calls first; the verifier does not
restate those checks.

The receipt is only an offline artifact-to-normalized-inventory proof. It always
marks spatial API transport, viewport rendering, selection, inspector, and
browser interaction `NOT VERIFIED`. It cannot complete 2WKG-439, 2WKG-458, or
2WKG-459.

`--published-artifact` records the repository-relative `published_path` and the
`published_compressed_sha256` of the file the receipt attests to, so a committed
receipt is fully tool-generated and regenerable. A path outside the repository is
refused rather than written as an absolute path.
`tests/test_physical_inventory_acceptance.py` re-hashes every published `.gz`,
re-derives every manifest field from it, and asserts each committed receipt is
byte-identical to the tool's output — flipping a byte in a release, falsifying a
manifest count, or hand-editing a receipt turns that suite red.

The clone-portable canonical releases are listed in
[`data/artifacts/physical_inventory/manifest-1.1.0.json`](../../data/artifacts/physical_inventory/manifest-1.1.0.json).
Load one with `gzip -cd <published_path> > /tmp/physical-inventory.json`, then
run the verifier against that JSON and the manifest's state and release version.
