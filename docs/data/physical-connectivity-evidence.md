# Physical connectivity evidence receipts

This is a bounded readiness record for 2WKG-455 and 2WKG-456.  It is not an
inventory, a coverage denominator, or a claim that either state has a complete
real network.  The companion machine-readable record is
[`physical-connectivity-readiness-v1.json`](../../data/sources/physical-connectivity-readiness-v1.json).

## Acceptance rule

`pipelines.physical_connectivity` publishes an electrical edge only when a
single source release supplies stable `terminal_id`, `from_terminal_id`, and
`to_terminal_id` values, with both referenced terminals present in that same
release.  Duplicate identifiers with different source records, repeated
endpoints, and references to missing terminals fail validation.  The adapter
has no geometry-to-topology operation.

Line endpoints, crossings, proximity, plant coordinates, imagery, and street
geometry are display context only.  They cannot create a terminal, an edge, a
transformer winding, a switch, an intertie, or a service attachment.

## Texas

ERCOT's public [modeling page](https://www.ercot.com/gridinfo/modeling) makes
process documentation and CIM schemas available, but it is not a public
release of the current operational network.  ERCOT's
[CEII market notice](https://www.ercot.com/services/comm/mkt_notices/archives/5178)
states that a certificate-holder role is required for ECEII posted in the MIS
Secure or Certified Area, including the Network Operations Model and other
datasets.  No authorized, versioned release containing terminal and circuit
references was available to this task, so Texas is explicitly `blocked` with
zero accepted terminals and edges.

## Minnesota

Minnesota's [utilities GIS catalog](https://www.mngeo.state.mn.us/chouse/utilities.html)
states that its former electric transmission-lines-and-substations dataset is
no longer supported because of accuracy and current-information problems.  The
[MnGeo utilities page](https://mn.gov/mngeo/gis-data-and-maps/info-by-topic/utilities-telecommunications/)
does provide public GIS context, but it does not establish terminal continuity.
No authorized, versioned source release with native terminal-and-circuit fields
was obtained, so Minnesota is explicitly `blocked` with zero accepted terminals
and edges.  GridSFM remains out of scope for real-network coverage unless a
separate source decision verifies its terms, version, fields, and mode.

## Integration boundary

The receipt and validator are intentionally schema-independent.  They await
2WKG-441's additive physical-inventory contract; a future state parser must
pass its authoritative terminal records through the validator before contract
publication.  A denied, restricted, stale, or geometry-only source closes only
that acquisition attempt.  It never certifies an asset class as complete.
