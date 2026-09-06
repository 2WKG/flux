# Historical event baseline contract

This directory defines the collection contract for 2WKG-460/461 (the hazard
bundles are 2WKG-462 through 2WKG-472; the catalog and held-out split are
2WKG-473). It records
research evidence; it does not establish a causal relationship, a grid model,
or a forecast score. Raw downloads and credentials stay in approved storage
outside Git.

## Layout and ownership

Each hazard owns only its bundle directory:

```text
docs/data/event-baseline/events/<hazard>/<event_id>.json
```

The bundle is JSON conforming to
`docs/data/event-baseline/event_baseline.schema.json`. That file is the single
structural definition: `scripts/data/event_baseline_validate.py` loads and
enforces it (including `additionalProperties: false`) before applying the
cross-field rules a JSON Schema cannot express. Every `*.json` committed under
`events/` is validated by `tests/data/test_event_baseline_bundles.py`, so
`gate/pytest` — not a reviewer's memory — is the enforcement point. The final audit owns
the assembled `event_catalog.csv` and split manifests. `event_baseline_assemble.py`
can assemble validated bundles into that catalog, but collection work must not
write a partial catalog at the repository root.

## Identity, time, and grouping

The canonical label identity is the tuple
`(county_fips, scenario_id, window_start_utc)`. `county_fips` is a five-digit
FIPS code and every row declares the boundary vintage used to resolve it.
`window_start_utc` and `window_end_utc` are UTC timestamps and define a
half-open six-hour interval `[start, end)`. Six-hour windows are a **closed
vocabulary aligned to 00/06/12/18 UTC** (`docs/specs/02-outage-model.md`:
"Window = 6 h, aligned to 00/06/12/18 UTC"). An unaligned start such as
`15:00:00Z` is refused by name: two bundles could otherwise cover the same
county-hour under two overlapping windows and the assembler's
`(county_fips, scenario_id, window_start_utc)` dedup key would not see the
collision, and nothing would join to `outage_predictions.ts`. Event, context, and recovery
windows are also UTC half-open intervals; context contains the event and
recovery ends after the event. `event_id` is stable across county windows;
`parent_system_id` groups the same meteorological system and is the split and
leakage grouping key. A compound episode has `compound=true` and names all
secondary hazards. Its components are not independent events.

Use a stable slug, for example `mn-2021-12-15-high-wind`, rather than a row
number or retrieved filename. `scenario_id` must be stable for a replay or
forecast experiment and must not be reused for a different event window.

## Candidate, acceptance, and coverage

Five independent candidate episodes are the collection frame for each hazard;
prioritize up to three only when matched observed weather and outage coverage
exists. This is a collection target, not a claim of statistical sufficiency.
Texas Uri and Beryl are reusable context, not new independent baseline events.

`disposition` is intentionally separate from the county-window label:

| Field | Meaning |
| --- | --- |
| `candidate_only` | A plausible episode that has not met the accepted-evidence rule. It must never be presented as an accepted event. |
| `accepted` | The row has a documented matched weather/outage decision and required receipts. |
| `rejected` | The candidate was evaluated and excluded; record why. |
| `shortfall` | A declared collection gap, exclusion, or unmet coverage target. |

An accepted record needs `weather.coverage="covered"`,
`outage.coverage="covered"`, `matched_coverage_decision="matched"`, and
provenance receipt references. An EAGLE-I gap is exactly
`outage.coverage="UncoveredLabel"`; it is never a zero outage. Such a row
cannot have `disposition="accepted"` or a computed/accepted label, and its
`observed_outage_customers` must be **null**: an uncovered window has no
measured count, so a `0` there is refused by name as `gap_recorded_as_zero`.

`covered` is a completeness claim, not merely a nonempty interval. For each
selected county-window, record `expected_samples`, `observed_samples`, and
`missing_timestamps`. An accepted row must have a positive expected count,
equal observed and expected counts, and no missing timestamps for EAGLE-I
outage labels and any weather `time_series_or_grid` evidence. EAGLE-I is
**15-minute cadence** (minutes `00/15/30/45`, verified on the 2021 and 2024
files — `docs/specs/01-data-ingest.md`), so a covered six-hour EAGLE-I window
expects **24 samples**, not six; the validator enforces that count for covered
`time_series_or_grid` outage evidence backed by an EAGLE-I receipt. Other
sources record their own real cadence rather than assuming one.

Weather evidence declares both `evidence_kind` and `observation_kind`.
`time_series_or_grid` supplies the count-based completeness evidence above and
is `observed` (for example, station measurements) or `modeled` (for example,
event-valid HRRR analysis in replay). HRRR analysis is never presented as an
observed station series. `authoritative_event_report` does not manufacture
one sample: it has null sample counts and instead requires source event IDs,
the report's UTC interval, a county or zone scope identifier, and explicit
limitations. The report interval must intersect the canonical county-window.
Point gauges, regional narratives, and storm-track/advisory material retain
their `point`, `regional`, or `track` scope and cannot by themselves prove
county weather coverage. Use `not_assessed` when evidence has not been
collected rather than inventing a row key or count.

Coverage acceptance and label computation are distinct. A row can be accepted
with observed outage coverage while its customer denominator is unavailable;
in that case `label.status="unavailable"` and no rate or positive/negative
label is asserted. Do not use population as a proxy. The versioned rule
`county_outage_5pct_v1` **is** spec 02's `y_out`, not a variant of it
(`docs/specs/02-outage-model.md`). It therefore fixes both halves the label
needs:

- `observed_outage_customers` is the **max** `customers_out` over the window's
  15-minute samples (spec 02 `max_out`); every row states this explicitly as
  `label.aggregation = "max_customers_out_over_window_samples"`, and no other
  aggregation is admissible.
- `customer_denominator.value` is `total_customers` for the county and must be
  at least **500**. Spec 02 drops counties with `total_customers < 500`, so a
  smaller denominator is unusable rather than merely small.

`outage_rate = observed_outage_customers / customer_denominator` and `positive`
is true when the rate is at least `0.05`. Only `label.status="computed"` may
carry a rate or `positive` value.

When native customer denominators vary by observation, retain their
`denominator_observations` summary (`present_rows`, `missing_rows`, `min`,
`max`) and mark the scalar label unavailable with
`unavailability_reason="dynamic_denominator_unsupported"`; coverage acceptance
does not depend on deriving a five-percent label.

## Provenance and source starter receipts

Every bundle identifies source receipts by ID. The receipt follows the repo's
existing source-receipt convention (`pipelines/hrrr.py`, `pipelines/tests/
fixtures/hrrr/PROVENANCE.json`) rather than forking a second one, so one reader
can read both kinds. Required, in the same sense as the HRRR receipt:

- `capture_method` — how the bytes were obtained; this is how a reader tells a
  byte-for-byte GET from a hand-edited extract.
- `verification` — an object recording at least
  `sha256_computed_from_response_body`; this is how a reader knows a hash was
  computed from the response body rather than typed in.
- `files` — logical name → `{url, bytes, sha256}` map. It may be `{}` when the
  receipt's single artifact is already described by `url`/`raw_sha256`/`bytes`.
- `uncertainty` — what this receipt does and does not establish.

Plus provider, URL, release/version, retrieval time, access/license terms, raw
and filtered SHA-256 when known, byte size or ETag when available, and the
research-specific additions this contract adds on top of the HRRR shape: units,
timezone conversion, filters, grid-index mapping, and `gaps`. The three shared
fields carry explicit suffixes here (`retrieved_at_utc`, `url`,
`license_or_access`) because bundles are hand-authored JSON where the UTC and
access-terms meaning has to be unmissable; the semantics are identical to the
HRRR receipt's `retrieved_at`, `source_url`, and `license_access`. Record
unavailable fields as `null` with an explanatory gap rather than inventing them.
Accepted rows cite their receipts through `provenance_receipt_ids`.

For an EAGLE-I receipt used to assert definitive outage coverage or an
`UncoveredLabel`, add `acquisition`: complete annual-stream method, source
system/file IDs and catalog bytes, integrity basis, and approved-storage URIs
plus SHA-256 values for raw source, source sidecar, and filtered artifact.
This is optional for ordinary/candidate receipts but required for decisive
EAGLE-I claims; raw bytes remain outside Git.

Each county-window also retains `source_row_keys`: stable keys for the exact
source rows used (for example provider, release, county FIPS, and timestamp),
and `source_slices`: receipt ID plus county/time slice. These are evidence
identities, not raw-file hashes: the same annual source file may legitimately
support many records. The final split audit uses them to detect source-row
reuse without guessing from an annual file hash.

Each key is formatted `<receipt_id>:<source-native-row-key>` and its receipt ID
must appear in `source_slices`. This makes the row key traceable to concrete
receipt/slice evidence without requiring an annual raw-file hash to be unique.

Set `source_evidence_status="available"` when a row claims matched coverage;
then both lists are nonempty. A candidate without fetched county rows uses
`source_evidence_status="unavailable"` with empty lists and explains the gap
through its coverage notes or uncertainty. Never invent a source-row key for a
candidate merely to satisfy the schema.

Use EAGLE-I for observed outage labels, NOAA HRRR for weather evidence, and
NCEI Storm Events for candidate discovery unless a hazard's documented source
is more specific. HRRR receipts name the run/init, lead, valid time, and f00
and f01 receipt IDs when those products are used.

## Replay and forecast

Every row declares `mode`.

- `replay` can use event-valid analyses and has
  `forecast_evaluation="not_forecast_scored"`.
- `forecast` has a `prediction_cutoff_utc` and per-input publication or
  availability time, run/init, lead, valid time, and retained f00/f01
  receipt IDs. Every input must be available by the cutoff. Treating an
  analysis as a perfect forecast is replay.

## Commands

`gate/pytest` already validates everything committed under `events/`. To
validate before you commit:

```bash
uv run python scripts/data/event_baseline_validate.py \
  --events-dir docs/data/event-baseline/events
```

or name individual bundles:

```bash
uv run python scripts/data/event_baseline_validate.py \
  docs/data/event-baseline/events/<hazard>/*.json
```

Assemble already validated bundles when the final-audit owner is ready:

```bash
uv run python scripts/data/event_baseline_assemble.py \
  --events-dir docs/data/event-baseline/events \
  --output /tmp/event_catalog.csv
```

The assembler refuses duplicate canonical identities and writes a deterministic
CSV with receipt IDs and uncertainty fields retained. It does not convert
uncovered labels to zeros or derive missing denominators.
