# 10 — Minnesota data identity, unit, coordinate, and provenance contract

**Contract version:** `2.0.0-mn`
**Status:** Minnesota artifact contract; executable DuckDB DDL is owned by 2WKG-98
**Consumers:** fixture builders, model/scoring adapters, read APIs, and Copilot tools

## Authority and scope

[10-minnesota-demo.md](10-minnesota-demo.md) supersedes the legacy Texas, ERCOT,
Uri, and ACTIVSg2000 demo contract. This document makes its required artifact
metadata concrete. It does not authorize a source download, a topology conversion,
or a result. The existing five-bus preview remains an unlabelled synthetic preview;
it is not a Minnesota fixture, topology, scenario, or evidence source.

The table names and compatible physical types in [00-overview.md](00-overview.md)
remain implementation inputs, but they do not authorize legacy Texas records for this
demo. When this document and a legacy table description differ about geography,
scenario, model mode, or Minnesota evidence, this document and the Minnesota amendment
win. 2WKG-98 implements the typed schema, constraints, and version preflight from this
contract; it must not seed fixture data or add consumer routes.

Every shared artifact is either **available** with the evidence below or
**unavailable** with an explicit reason. No empty value, zero, generated identifier,
or legacy record may stand in for Minnesota source evidence.

## Common artifact envelope

All persisted Minnesota artifacts and every available numeric/model response carry
these top-level fields. A physical table may normalize the fields, but API and
Copilot responses expose them without requiring a client to reconstruct provenance.

| Field | Type / rule |
| --- | --- |
| `artifact_id` | Stable string `mn:<artifact_kind>:<sha256-16>`. The digest is the first 16 lowercase hex characters of SHA-256 over the canonical JSON identity object below. |
| `artifact_kind` | `source_manifest`, `geography`, `fixture`, `scenario`, `model_result`, `score`, `citation_corpus`, or `api_result`. |
| `contract_version` | Exact contract version used to build the artifact. |
| `geography_id` | `mn` for statewide artifacts, or a source-qualified Minnesota region key. It is never `TX`, `ERCOT`, or a guessed utility/interconnection name. |
| `availability` | `available` or `unavailable`. Available artifacts use the full envelope; unavailable results use the unavailable envelope below. |
| `model_mode` | `topology`, `aggregate`, or `not_applicable`. A source manifest uses `not_applicable` until the network decision is recorded. |
| `created_at` | UTC timestamp, emitted by APIs with a trailing `Z`. |
| `provenance` | Ordered, nonempty list for available artifacts; each entry has the source fields in the next section. |
| `assumptions` / `limitations` | Arrays of nonempty strings. An available model or score result has at least one limitation. |

The canonical identity object is UTF-8 JSON with recursively sorted object keys and
no insignificant whitespace. It has only `artifact_kind`, `geography_id`,
`model_mode`, `source_identity`, `source_version`, and `content_sha256`.
`source_identity` is the source-qualified record identity below; `content_sha256` is
the lowercase SHA-256 of the immutable input artifact or canonical content. A builder
refuses a missing identity input rather than hashing a placeholder. The complete
identity object is retained in the source manifest so a digest collision is diagnosable.

## Source and field provenance

Each available artifact has one or more provenance entries:

| Field | Rule |
| --- | --- |
| `source_name` | Stable publisher/dataset name, not a display label. |
| `source_ref` | Stable source URL, accepted artifact-store path, or publisher record identifier. |
| `source_version` | Publisher release/version/date/checksum. If none is supplied, use `unknown` and record that limitation; never invent a version. |
| `retrieved_at` | UTC retrieval timestamp. It is required for every available source artifact. |
| `license_or_terms` | Verified terms or `unknown`; `unknown` blocks topology-mode fixture use. |
| `source_record_id` | Immutable upstream record key when one exists; otherwise `null` with an assumption explaining why. |
| `content_sha256` | SHA-256 of the accepted source artifact or record payload. |
| `field_provenance` | Maps every numeric, geographic, model-input, or legal-claim field to the provenance-entry index that supplied it. |

A deterministic domain identity is `(source_name, source_version,
source_record_id)`. It is preserved verbatim and never replaced by an arbitrary
integer. Where 2WKG-98 maps it into a legacy `*_id` column, it also stores this tuple
in the accepted source/provenance relation; a collision or missing upstream identity
is unavailable, not a synthesized key. `artifact_id` is the cross-surface identifier
for fixtures, model outputs, APIs, and Copilot evidence.

Derived artifacts name their producing module/version as a provenance entry and list
their input `artifact_id`s in `input_artifact_ids`. A model result also records
`model_name`, `model_version`, `model_run_id`, and the content hash of its validated
input manifest. The Copilot repeats those identifiers from its tool result; it does
not create or alter them.

## Coordinates, geometry, and geography

- Coordinates use WGS 84 / EPSG:4326. A point is decimal-degree `lon`, then `lat`;
  geometry is OGC WKB in the same coordinate reference system. Screen coordinates,
  Web Mercator, geocoded guesses, and coordinates copied from a legacy fixture are
  prohibited.
- A point has both `lon` and `lat` or neither. Missing source geometry is represented
  by both values `NULL` and `coordinate_status="unavailable"`; it is never `(0, 0)`
  or a state centroid. `coordinate_status` is `source`, `derived`, or `unavailable`.
- `coordinate_precision` records source precision/unit. The map must not display more
  precision than the accepted boundary or source record supports. A derived coordinate
  identifies its input geometry and method in `field_provenance`.
- Geography is Minnesota only when an accepted source manifest documents Minnesota
  coverage. A service area, utility name, county, zone, or allocation is a
  source-qualified `geography_id`; no FIPS, BA code, or interconnection is inferred.

## Units, timestamps, and absent values

`TIMESTAMP` values are UTC and timezone-naive in DuckDB; API/Copilot serializations
end in `Z`. `ts` is an observation instant and `ts_begin`/`ts_end` bound a documented
event. The initial scenario identifier is `mn_winter_2023_snow`; it is only
**historical weather stress** until a distinct outcome artifact and matching method
are accepted.

| Value | Required unit / encoding |
| --- | --- |
| power, energy, voltage, distance | `MW`, `MWh`, `kV`, `km` (`_mw`, `_mwh`, `_kv`, `_km`) |
| weather | `m/s`, `°C`, `mm` (`_ms`, `_c`, `_mm`) |
| probability, percent | `0..1` for `p_*`; `0..100` for `*_pct` |
| money and score | source-year USD with year in provenance; scores state scale and components |
| geometry and structured fields | EPSG:4326 WKB or lon/lat; `*_json` is valid JSON, never Python repr |

Every numeric field is finite and has field provenance. `NULL` means the accepted
source, join, or completed calculation did not supply a value. It never means zero,
`NaN`, an empty string, `-1`, or a plausible fallback. A missing derived row means the
calculation did not run or failed. Unknown units block calculation and return
unavailable output; conversion records its source unit and method.

## Model-mode boundary

`model_mode="topology"` is permitted only after the Minnesota network decision record
accepts bus and branch identity, endpoints/geometry, impedance/reactance, base MVA,
load/generation allocation, thermal ratings, usage terms, units, versions, and
source-to-solver mapping. A topology result includes accepted input artifact IDs,
solver and converter versions, base MVA, validation status, assumptions, and
limitations. Missing any required input is unavailable; it does not fall back to
ACTIVSg2000 or a guessed value.

`model_mode="aggregate"` requires a named regional stress metric, formula, value and
unit, named regions and allocation basis, input artifact IDs, and a limitation that it
is not a transmission-flow or outage simulation. It must not emit or imply bus flows,
line ratings/loading, DC power flow, N-1 conclusions, trips, cascades, or an
interconnection study. A validated Minnesota network remains allowed when the decision
gate is met; aggregate mode is the honest fallback, not a relabel.

Scores retain `metric`, `score_components`, `model_mode`, `input_artifact_ids`, and
`regulatory_label`. They are hypothetical model comparisons unless supporting evidence
says otherwise and never become permitability, construction-readiness, or legal claims.

## API and Copilot availability envelopes

An available API or Copilot tool result has `availability="available"`, nonempty
common-envelope `provenance`, `model_mode`, `limitations`, and `artifact_id`. Every
number or model claim links through `field_provenance` to a source or model artifact.

An unavailable result has exactly these top-level fields: `availability="unavailable"`,
`status`, `code`, `message`, `next_step`, `artifact_id=null`, `model_mode=null`,
`provenance=[]`, and `limitations`. It contains no invented result fields or numeric
defaults. A missing source, corpus, configured provider, required model input, or
unaccepted topology gate uses this envelope. Copilot reports the tool's envelope; it
does not compute a replacement result.

An unavailable artifact persisted for audit/rebuild still has its deterministic
`artifact_id`, `availability="unavailable"`, and `model_mode="not_applicable"`; it has
no domain-family row. The null `artifact_id` form is only an ephemeral API/Copilot
response, where no artifact was built or selected.

## 2WKG-98 physical schema map

2WKG-98 stores the following typed relations in `data/duck/grid.duckdb`. `TEXT` IDs
are UTF-8, `TIMESTAMP` values are UTC, and `JSON` values contain valid JSON. A listed
`PK` is non-null. The domain-family rows below represent available artifacts only;
the manifest records a persisted unavailable state without a domain row.

| Relation | Exact key and columns | Constraints / purpose |
| --- | --- | --- |
| `schema_meta` | `key TEXT PK`, `value TEXT NOT NULL` | Holds `contract_version = "2.0.0-mn"`. |
| `artifact_manifests` | `artifact_id TEXT PK`, `artifact_kind TEXT NOT NULL`, `contract_version TEXT NOT NULL`, `geography_id TEXT NOT NULL`, `availability TEXT NOT NULL`, `model_mode TEXT NOT NULL`, `identity_json JSON NOT NULL`, `created_at TIMESTAMP NOT NULL`, `assumptions_json JSON NOT NULL`, `limitations_json JSON NOT NULL`, `input_artifact_ids_json JSON NOT NULL` | `artifact_kind` is one of the common-envelope kinds; availability is `available`/`unavailable`; model mode is `topology`/`aggregate`/`not_applicable`. `identity_json` is the canonical identity object. |
| `artifact_provenance` | `(artifact_id TEXT, provenance_ordinal INTEGER) PK`, `source_name TEXT NOT NULL`, `source_ref TEXT NOT NULL`, `source_version TEXT NOT NULL`, `retrieved_at TIMESTAMP NOT NULL`, `license_or_terms TEXT NOT NULL`, `source_record_id TEXT NULL`, `content_sha256 TEXT NOT NULL`, `is_derived BOOLEAN NOT NULL` | FK `artifact_id → artifact_manifests`; ordinal is nonnegative and hash is 64 lowercase hex characters. Initializer validation requires at least one row for every available manifest. |
| `artifact_field_provenance` | `(artifact_id TEXT, field_name TEXT, provenance_ordinal INTEGER) PK`, `derivation_method TEXT NULL` | Composite FK `(artifact_id, provenance_ordinal) → artifact_provenance`. Multiple rows allow a field to retain every source/derived input; `derivation_method` is required when a field is derived. |
| `geography_artifacts` | `artifact_id TEXT PK`, `geometry_wkb BLOB NULL`, `lon DOUBLE NULL`, `lat DOUBLE NULL`, `coordinate_status TEXT NOT NULL`, `coordinate_precision TEXT NULL` | FK to manifest. Status is `source`/`derived`/`unavailable`; lon and lat are both null or both finite/in range, and `unavailable` requires all geometry/point values null. |
| `fixture_artifacts` | `artifact_id TEXT PK`, `source_manifest_id TEXT NOT NULL`, `fixture_label TEXT NOT NULL`, `fallback_label TEXT NULL` | FKs to manifest and source-manifest artifact. Metadata only: it does not seed data or identify a topology. |
| `scenario_artifacts` | `artifact_id TEXT PK`, `scenario_id TEXT NOT NULL UNIQUE`, `scenario_label TEXT NOT NULL`, `ts_begin TIMESTAMP NOT NULL`, `ts_end TIMESTAMP NOT NULL`, `location_coverage TEXT NOT NULL`, `weather_values_json JSON NOT NULL`, `outcome_artifact_id TEXT NULL`, `matching_method TEXT NULL` | FK to manifest; end cannot precede begin. Label is `historical_weather_stress` unless both an accepted outcome artifact and a nonempty matching method exist; values are retained as source-valued JSON with field provenance. |
| `model_results` | `artifact_id TEXT PK`, `model_name TEXT NOT NULL`, `model_version TEXT NOT NULL`, `model_run_id TEXT NOT NULL`, `input_manifest_sha256 TEXT NOT NULL`, `validation_status TEXT NOT NULL`, `metric_name TEXT NOT NULL`, `metric_value DOUBLE NOT NULL`, `metric_unit TEXT NOT NULL`, `formula TEXT NULL`, `base_mva DOUBLE NULL`, `solver_version TEXT NULL`, `converter_version TEXT NULL` | FK to manifest; finite value; status is `validated`. Initializer validation requires an available manifest. Aggregate requires formula and null solver/converter/base-MVA; topology requires base-MVA, solver, and converter. |
| `score_results` | `artifact_id TEXT PK`, `metric TEXT NOT NULL`, `score_value DOUBLE NOT NULL`, `score_unit TEXT NOT NULL`, `score_components_json JSON NOT NULL`, `regulatory_label TEXT NOT NULL` | FK to manifest; finite value. Regulatory label is `hypothetical`, `source_screened`, or `source_supported`. |
| `citation_chunks` | `chunk_id TEXT PK`, `corpus_artifact_id TEXT NOT NULL`, `doc TEXT NOT NULL`, `title TEXT NOT NULL`, `page INTEGER NOT NULL`, `chunk_ordinal INTEGER NOT NULL`, `text TEXT NOT NULL` | FK corpus artifact to manifest; page is positive, ordinal nonnegative, and `(corpus_artifact_id, doc, page, chunk_ordinal)` is unique. This is versioned local corpus storage for 2WKG-128, not retrieval implementation. |
| `citation_hits` | `(artifact_id TEXT, hit_ordinal INTEGER) PK`, `chunk_id TEXT NOT NULL`, `doc TEXT NOT NULL`, `title TEXT NOT NULL`, `page INTEGER NOT NULL`, `score DOUBLE NOT NULL`, `text TEXT NOT NULL` | FKs to manifest and chunk; ordinal nonnegative and score finite. It preserves the exact `doc`, `title`, `page`, `chunk ID`, `score`, and `text` required in a cited API/Copilot evidence artifact. |

## 2WKG-98 implementation handoff

2WKG-98 owns DDL/initializer implementation in `data/duck/grid.duckdb`. Its first
operation reads `schema_meta.contract_version`; a missing database creates contract
`2.0.0-mn`, an equal version may rerun idempotently, and any other version fails before
creating or changing a table. It must never silently migrate a fixture.

The physical map above is the complete minimum 98 storage scope, including fixture and
citation evidence metadata. The manifest holds the common envelope and canonical identity
JSON; typed families hold coordinates, units/values, model mode, input-artifact IDs,
score components, and citations. This permits stable cross-surface identity without
forcing a source record into a legacy numeric `*_id` field.

2WKG-98 validates deterministic identity generation; preflight-before-mutation;
idempotent reruns; provenance and field-provenance preservation; paired coordinate
absence; finite/unit-safe numeric values; topology/aggregate requirements; and
available/unavailable envelopes. These are initializer validation rules when a relational
FK/CHECK cannot express them: every typed domain row has an available manifest, and every
available manifest has provenance. Meaningful tests rerun the same manifest without
duplicates, reject a mismatched version without schema mutation, reject an available
numeric/model row without complete provenance, reject one-sided coordinates and an
aggregate result with a flow/cascade field, require scenario weather values/time/location,
reject an outage-replay label without both outcome and matching method, and accept the
explicit unavailable envelope.
It may use the legacy table catalogue only where it faithfully represents these Minnesota
artifacts. It must not create Minnesota rows, call a source, introduce Texas data, or
change API/Copilot consumers. Fixture, model, API, and Copilot owners consume this
contract in their own work items.

## Verification

Review this contract with [10-minnesota-demo.md](10-minnesota-demo.md) and verify its
Markdown diff with `git diff --check origin/master...HEAD`. 2WKG-98 adds executable
schema tests for the handoff criteria; this documentation-only change does not claim an
initializer or Minnesota artifact already exists.
