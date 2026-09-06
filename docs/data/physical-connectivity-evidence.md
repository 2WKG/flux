# Physical connectivity evidence receipts

This is a bounded readiness record for 2WKG-455 and 2WKG-456.  It is not an
inventory, a coverage denominator, or a claim that either state has a complete
real network.  The companion machine-readable record is
[`physical-connectivity-readiness-v1.json`](../../data/sources/physical-connectivity-readiness-v1.json).

## Acceptance rule

`pipelines.physical_connectivity` normalizes an electrical edge only when a
single source release supplies stable `terminal_id`, `from_terminal_id`, and
`to_terminal_id` values, with both referenced terminals present in that same
release.  The adapter has no geometry-to-topology operation.

Structural validity is **not** re-implemented here.  Identifier uniqueness,
endpoint existence, an edge joining two distinct terminals, and `asset_id` /
`source_id` resolving inside the release are all owned by
`pipelines.physical_inventory.validate_artifact` (2WKG-441), and
`normalized_receipt` enforces them by putting the rows it produced --
together with the caller's `sources[]` row, asset rows and coverage rows --
through that validator.  A receipt is returned only if the contract accepts
them, so `status: "ready_for_contract_integration"` is a checked claim rather
than a label.

The one rule this module owns is the one the contract cannot express, because
the contract only ever sees post-deduplication rows: a native release may
repeat an identifier, and repeating it with a *different* source record is a
conflict rather than a duplicate.  Terminal and edge rows use the canonical
`physical_inventory` shapes (`terminal_id`, `asset_id`, `source_id`,
`source_record_id`; and `edge_id`, endpoint IDs, `source_id`,
`source_record_id`) rather than a second persistence schema.

Line endpoints, crossings, proximity, plant coordinates, imagery, and street
geometry are display context only.  They cannot create a terminal, an edge, a
transformer winding, a switch, an intertie, or a service attachment.

## Receipt generation

`data/sources/physical-connectivity-readiness-v1.json` is not hand-authored: it
is the serialized output of
`pipelines.physical_connectivity.build_readiness_document`, which builds each
element with `blocked_readiness_receipt(...)`.  Regenerate it with

```
uv run python -m pipelines.physical_connectivity
```

`tests/test_physical_connectivity.py::test_committed_readiness_record_is_the_generator_output`
fails if the committed file and the generator disagree by a single byte.  Each
receipt records how its evidence was captured (`capture_method`), the sha256 of
each captured response body, the sentence quoted from it, and an explicit
`verification{}` block -- the `data/sources` receipt shape introduced by
2WKG-199/2WKG-216, rather than a bare asserted timestamp.

## Texas

ERCOT's public [modeling page](https://www.ercot.com/gridinfo/modeling) makes
process documentation and CIM schemas available, but it is not a public
release of the current operational network.  ERCOT's
[CEII market notice](https://www.ercot.com/services/comm/mkt_notices/archives/5178)
states that a certificate-holder role is required for ECEII posted in the MIS
Secure or Certified Area, including the Network Operations Model and other
datasets.  No authorized, versioned release containing terminal and circuit
references was available to this task, so Texas is explicitly `blocked` with
zero accepted terminals and edges.  Both pages were captured over HTTPS on
2026-09-06 and their sha256 digests are recorded in the receipt; the quoted
ECEII sentence is present in the captured market-notice body.

## Minnesota

Minnesota's [utilities GIS catalog](https://www.mngeo.state.mn.us/chouse/utilities.html)
states, verbatim: "7/20/2022: Given existing accuracy problems with the dataset
and insufficient current information, the Minnesota Department of Commerce
cannot continue to support the distribution and use of this dataset."

That sentence could **not** be read from the live URL: it 301-redirects to
`https://mn.gov/mngeo`, which answers with a Radware Bot Manager captcha
interstitial whose body carries a per-request nonce (so it has no stable
sha256).  The live attempt is therefore recorded in the receipt as
`quote_status: "unverified_as_committed"` with that outcome, and the quote is
carried against an Internet Archive snapshot of the same URL
(`2026-04-21T11:19:29Z`, sha256 `fb8f8132…1032ee`, identical across two
fetches).  The
[MnGeo utilities page](https://mn.gov/mngeo/gis-data-and-maps/info-by-topic/utilities-telecommunications/)
does provide public GIS context, but it does not establish terminal continuity.
No authorized, versioned source release with native terminal-and-circuit fields
was obtained, so Minnesota is explicitly `blocked` with zero accepted terminals
and edges.  GridSFM remains out of scope for real-network coverage unless a
separate source decision verifies its terms, version, fields, and mode.

## Integration boundary

The receipt does not publish a physical artifact.  The consumer is **2WKG-456**
(the state connectivity parser): it maps a state's documented native fields onto
`normalized_receipt`'s inputs and puts the returned rows straight into the
2WKG-441 physical-inventory artifact.  Until 2WKG-456 lands, nothing in the
shipped system calls this module -- its only exercise is its own test suite,
which drives `pipelines.physical_inventory.validate_artifact` over the rows it
produces. A denied,
restricted, stale, or geometry-only source closes only that acquisition attempt.
It never certifies an asset class as complete.
