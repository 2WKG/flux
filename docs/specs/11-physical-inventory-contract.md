# 11 — Physical inventory artifact contract

This contract is the shared ingestion boundary for the Texas and Minnesota
physical-map work. It is additive to the existing DuckDB, provenance, CRS,
readiness, and unavailable-state contracts. It creates no route, API envelope,
renderer adapter, state source acquisition, or electrical model.

`pipelines.physical_inventory` owns the stable version `1.0.0`. A producer
submits one canonical JSON object with an ID of
`<geography_id>:physical-inventory:<semantic-version>` and a SHA-256 over its
canonical JSON (excluding `content_sha256`). The writer persists that exact
canonical JSON and its decomposed relations into the `physical_*` DuckDB namespace and refuses a conflicting
repeat. This makes a map/API artifact traceable to a reproducible input rather
than a current mutable source query.

Every artifact declares both `inventory_mode` and `electrical_model_mode`.
`physical_observed` is the only real physical-inventory mode. `fixture` and
`synthetic` are accepted only as explicitly labelled modes. Electrical-model
coverage is independently `none`, `source_backed`, `synthetic`, or `aggregate`;
an observed asset does not establish a network model.

## Assets, geometry, and provenance

Each asset has a stable source record identity, one authoritative source entry,
an asset class, and either source/derived native geometry or an explicit
`unavailable` geometry state. Valid source geometry is non-empty GeoJSON
`Point`, `MultiPoint`, `LineString`, `MultiLineString`, `Polygon`, or
`MultiPolygon`, with an explicit EPSG CRS, including source-native CRSs.
Geometry precision in metres and a separate
human-readable accuracy basis are required whenever geometry exists. Authority
and version live in `sources`; accuracy basis never substitutes for authority.
Numeric precision may be null when the source publishes no numeric precision;
the accuracy basis must say so. Derived geometry also requires an explicit
derivation method. Unavailable geometry has null geometry, CRS, precision,
accuracy, and derivation fields.

Terminals and connectivity edges are optional. When present, both carry their
own source record identity, and an edge can only join two persisted sourced
terminals. Producers must omit unknown connectivity; they may not infer it from
proximity, imagery, a label, street data, or a synthetic case.

## Coverage

For every reported class/scope pair, `physical_coverage` records the observed
count, nullable denominator, unknown count, and unavailable count, denominator basis, source
scope, status, and a named reason. A source scope is never silently treated as
statewide or owner-level coverage.
Statuses are `complete`, `partial`, `unknown`, or `unavailable`. A `complete`
claim needs exact observed/denominator reconciliation with zero unknown and
unavailable counts; an unavailable or unknown denominator is
stored as `null`, never zero. Partial public layers therefore remain useful
without certifying that all owner-level assets exist.

## Consumer boundary

State builders call `validate_artifact()` and `write_artifact()`. The spatial
read API owns pagination, viewport filtering, and response envelopes; it reads
these tables without changing their truth labels. Renderers consume the API
payload. No consumer may promote a fixture/synthetic artifact, unknown
coverage, unavailable geometry, or absent terminal edge into a real-grid claim.
