# 11 — Physical inventory artifact contract

This contract is the shared **physical-inventory** ingestion boundary for state
physical-map lanes (Texas first). It is additive to the existing DuckDB,
provenance, CRS, readiness, and unavailable-state contracts. It creates no
route, API envelope, renderer adapter, state source acquisition, or electrical
model.

It does **not** own Minnesota artifact identity, availability, or provenance.
[10-duckdb-contract.md](10-duckdb-contract.md) remains the authority for the
`mn:<artifact_kind>:<sha256-16>` identity and the `availability` /`model_mode` /
`field_provenance` / `assumptions` / `limitations` envelope, implemented by
`pipelines/minnesota_schema.py` in the `mn_*` namespace. A Minnesota producer
that writes a `physical_*` inventory artifact still registers its Minnesota
artifact under spec 10; see "Relationship to spec 10" below.

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

The CRS must be a registered `EPSG:<code>` or `ESRI:<code>` authority string.
For example, Minnesota source geometry may truthfully retain `ESRI:103705`;
the validator resolves the declared authority rather than treating a numeric
WKID as an EPSG code. Unrecognized authority codes fail validation.

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

## State-release composition

`pipelines.assemble_physical_inventory` joins validated partial artifacts into a
new state release, such as `tx:physical-inventory:1.1.0`. It resolves the
documented `us-tx` producer alias and state-qualified scopes such as
`mn:mille-lacs-county` to their state release keys, retains sorted input content
SHA-256 values as `input_artifact_sha256s`, and preserves each coverage row without
rolling counts into a completeness claim. Exact duplicate sources may be
deduplicated, as may identical coverage rows; conflicting source IDs,
duplicate physical identities, and conflicting class/scope coverage rows fail
assembly.

## Published release artifacts (size and lineage policy)

A composed state release may be published under
`data/artifacts/physical_inventory/<state>/physical-inventory-<version>.json.gz`
and listed in `manifest-<version>.json`. These gzip streams are the one class of
binary this repository tracks: they are the deliverable itself, not downloaded
data, and `.gitattributes` marks `*.gz` binary so Git never rewrites them.

Every published release carries a lineage that a clone can check.
`input_artifact_sha256s` lists the component artifacts, and the manifest names
any component that is *not* tracked here — with the reason — under
`untracked_input_artifact_sha256s` / `untracked_input_reason`, rather than
implying a lineage a clone cannot resolve. `compressed_sha256` identifies the
committed bytes only; deflate output is not portable between compressors, so the
reproducible invariant is `canonical_content_sha256`, the contract digest of the
decompressed canonical JSON. `tests/test_physical_inventory_acceptance.py`
re-hashes each published file, re-derives every manifest field from it, and
reassembles the release from its tracked components.

A release whose components cannot be tracked, or whose size would outgrow this
policy, is published outside Git with a receipt under `data/sources/` recording
where it lives; it is not committed.

## Relationship to spec 10 (declared divergence)

The `physical_*` namespace and the `mn_*` namespace are two different contracts
and are deliberately not unified in this PR.

| Concern | Spec 10 (`mn_*`) | Spec 11 (`physical_*`) |
|---|---|---|
| Identity | `mn:<artifact_kind>:<sha256-16>` — content-addressed, kind-qualified, Minnesota-scoped | `<geography_id>:physical-inventory:<semver>` — a *named release* a state lane can re-cut and version |
| Availability | `availability` on the artifact | per class/scope rows in `physical_coverage` (`complete`/`partial`/`unknown`/`unavailable`) |
| Model mode | `model_mode` ∈ `topology`/`aggregate`/`not_applicable` | `electrical_model_mode` ∈ `none`/`source_backed`/`synthetic`/`aggregate`, held separately from `inventory_mode` |
| Provenance | `field_provenance`, `assumptions`, `limitations` per field | per-asset `source_id` + `source_record_id` + geometry accuracy basis and derivation method |

**Reason for the divergence.** A physical inventory is republished as a versioned
release whose id must stay stable while its digest changes across recuts, so a
content-addressed id is the wrong identity for it; and its unavailability is
per asset class and scope, not per artifact, so a single `availability` field
cannot carry it. Unifying the two would either freeze release ids to content
digests or flatten class/scope coverage into one artifact-level flag — both lose
truth. This divergence is recorded in both documents; neither contract may be
changed unilaterally to claim the other's namespace.

**Boundary rule.** A `physical_*` artifact never writes, reads, or renames an
`mn_*` row, and never substitutes for a spec-10 artifact in an API or Copilot
envelope. A Minnesota lane that publishes physical inventory records the
spec-10 artifact for the API surface and cites the `physical_*`
`artifact_id`/`content_sha256` as its source identity.
