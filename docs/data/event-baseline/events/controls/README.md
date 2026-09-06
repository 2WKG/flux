# Ordinary-weather controls and hazard near misses

This directory is the control-selection record for Linear 2WKG-472. It
contains a preselection plan, not a claim that either cohort is a causal
counterfactual. The plan was fixed before any EAGLE-I outage values are read.

There are two separate cohorts:

| cohort | purpose | selection rule | outcome use |
| --- | --- | --- | --- |
| `calendar_control` | representative ordinary-weather reference periods | deterministic sample from the complete eligible county-season-window frame | none during selection |
| `hazard_near_miss` | diagnostic weather-exposure comparison | documented weather episode, matched on hazard family/region/season/time to an accepted hazard event when one is available | none during selection |

`hazard_near_miss` is not a “low-outage” cohort. Its later EAGLE-I lookup can
only record label availability (`CoveredLabel` or `UncoveredLabel`) and source
coverage evidence. It cannot revise eligibility, selection order, or cohort
membership. A missing label remains `UncoveredLabel`, never zero; a missing
denominator is unavailable, never inferred from population.

The candidate frame, matching variables, exclusions, the `stratum_key`
serialization, IDs, and the explicitly unweighted choice are in
[preselection-plan.yaml](preselection-plan.yaml). That plan makes no
reproducible-rerun claim: selection order and record IDs were recorded by hand,
no selector script exists here, and the `ctrl-calendar-<hex>` IDs are opaque
names rather than recomputable digests. The
machine-readable row shape and preselection state are in
[controls-candidate-manifest.json](../../controls-metadata/controls-candidate-manifest.json). Selections
stay `pending_catalog_and_coverage` until the shared event contract and source
coverage receipt establish the county/window frame. This prevents claims of
accepted controls before matched weather and outage coverage are evidenced.

The separate [diagnostic-near-miss-candidates.json](../../controls-metadata/diagnostic-near-miss-candidates.json)
contains five NCEI-documented Minnesota convective-weather candidates. It records
event and episode IDs, county FIPS, UTC conversion, the exact source-file hash,
and selection order, but deliberately has no outage result. Those rows are
diagnostic candidates only. They require their own weather/outage coverage
decision before an event-baseline bundle may present them as accepted.

[eaglei-capture-audit.json](../../controls-metadata/eaglei-capture-audit.json) links the frozen plan to
the bounded EAGLE-I receipts produced afterward, which are committed under
`../../controls-metadata/eaglei-receipts/`. Each receipt is the extractor's
verbatim output, so its `filtered_artifact` field still names the machine-local
path it was written to; the repo-relative location and a recomputed digest of
each filtered slice are recorded in the audit's `filtered_artifact_path` and
`filtered_artifact_sha256_recomputed`. Those bounded captures are superseded as
outage evidence by the exhaustive full-annual scans each bundle now carries as
its own `eaglei-*` source receipt. The audit distinguishes
complete observations, partial observations, `UncoveredLabel`, and an extractor
error. None of those post-selection outcomes changes membership or makes a
diagnostic candidate a “low-outage” near miss.

## Frozen starter selection

The first five calendar candidates are frozen as one bundle each:
[calendar-control-mn-2021-spring-01.json](calendar-control-mn-2021-spring-01.json),
[calendar-control-mn-2021-summer-01.json](calendar-control-mn-2021-summer-01.json),
[calendar-control-mn-2021-autumn-01.json](calendar-control-mn-2021-autumn-01.json),
[calendar-control-mn-2022-spring-01.json](calendar-control-mn-2022-spring-01.json), and
[calendar-control-mn-2022-autumn-01.json](calendar-control-mn-2022-autumn-01.json).
They replaced a single pre-split `mn-calendar-controls-2021-2022.json` blob,
whose capture-time digest is kept under `superseded_selection_artifacts` in the
capture audit; that file is not in the tree. They are Hennepin County (`27053`),
one UTC six-hour window per predeclared season/year stratum. At selection time,
the known candidate envelopes received from the parallel winter, wind, water,
heat, fire, and PSPS streams were exclusion constraints. The selected windows
do not overlap those supplied envelopes. They remain `candidate_only` until
the shared catalog records their boundary vintage and source feasibility
records matched weather and outage coverage. No EAGLE-I value or denominator
was read to select them.

## Evidence sources for frame construction

- [NCEI Storm Events bulk CSV index](https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/) is the source for documented hazard episode candidates and source IDs.
- [NWS Twin Cities past-event archive](https://www.weather.gov/mpx/events) is a candidate source for Minnesota and western Wisconsin event timing and classification.
- [EAGLE-I dataset landing record](https://doi.ccs.ornl.gov/dataset/ccec86f0-e144-5de8-aee0-fb26028b26e1) is the intended label source; access/coverage is assessed separately and does not affect selection.

The plan starts with up to five candidates per cohort/stratum and prioritizes a
first tranche of up to three only where evidence permits. It does not require
three accepted rows when coverage evidence is unavailable.
