# Historical event baseline contract

This directory defines the collection contract for 2WKG-460. It records
research evidence; it does not establish a causal relationship, a grid model,
or a forecast score. Raw downloads and credentials stay in approved storage
outside Git.

## Layout and ownership

Each hazard owns only its bundle directory:

```text
docs/data/event-baseline/events/<hazard>/<event_id>.json
```

The bundle is JSON conforming to
`docs/data/event-baseline/event_baseline.schema.json`. The final audit owns
the assembled `event_catalog.csv` and split manifests. `event_baseline_assemble.py`
can assemble validated bundles into that catalog, but collection work must not
write a partial catalog at the repository root.

## Identity, time, and grouping

The canonical label identity is the tuple
`(county_fips, scenario_id, window_start_utc)`. `county_fips` is a five-digit
FIPS code and every row declares the boundary vintage used to resolve it.
`window_start_utc` and `window_end_utc` are UTC timestamps and define a
half-open six-hour interval `[start, end)`. Event, context, and recovery
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
cannot have `disposition="accepted"` or a computed/accepted label.

`covered` is a completeness claim, not merely a nonempty interval. For each
selected county-window, record `expected_samples`, `observed_samples`, and
`missing_timestamps`. An accepted row must have a positive expected count,
equal observed and expected counts, and no missing timestamps for EAGLE-I
outage labels and any weather `time_series_or_grid` evidence. An hourly
EAGLE-I six-hour window normally documents six samples, but record the actual
expected cadence/count rather than assuming it.

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
`county_outage_5pct_v1` computes `outage_rate = observed_outage_customers /
customer_denominator` and marks positive when the rate is at least `0.05`.
Only `label.status="computed"` may carry a rate or `positive` value.
When native customer denominators vary by observation, retain their
`denominator_observations` summary (`present_rows`, `missing_rows`, `min`,
`max`) and mark the scalar label unavailable with
`unavailability_reason="dynamic_denominator_unsupported"`; coverage acceptance
does not depend on deriving a five-percent label.

## Provenance and source starter receipts

Every bundle identifies source receipts by ID. A receipt records provider,
URL, release/version, retrieval time, access/license terms, raw and filtered
SHA-256 when known, byte size or ETag when available, units, timezone
conversion, filters, and grid-index mapping. Record unavailable fields as
`null` with an explanatory gap rather than inventing them. Accepted rows cite
their receipts through `provenance_receipt_ids`.

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

Validate one or more bundles before handoff:

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
