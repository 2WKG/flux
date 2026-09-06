# Texas physical-grid source authority ledger

[`data/sources/texas-physical-grid-source-ledger-v1.json`](../../data/sources/texas-physical-grid-source-ledger-v1.json)
is the P1 Texas source decision record. It records what each source can prove
before a worker acquires or normalizes a physical-grid artifact. It is not a
map, a source snapshot, or a claim that Texas asset classes are complete.

## Source decisions

| Physical class | Source of record or acquisition lead | Current outcome |
| --- | --- | --- |
| Plants, generators, storage | EIA Form 860 annual ZIP | Public, authoritative and machine-readable. EIA-860 reports plant identity and coordinates, but not an interconnection. The generation inventory worker owns its artifact. |
| Transmission routes | HIFLD U.S. Electric Power Transmission Lines archive | Public native polylines with per-feature source/validation fields; archive last updated 2024-09-30. It is a partial, stale overlay, not a Texas completeness source. |
| Substations | HIFLD/USGS-derived Texas Wind Energy Infrastructure metadata | The identified 2017 endpoint required an ArcGIS token during this audit. Record the restriction; do not replace it with an unverified copy or infer substations from line ends. |
| Utility/owner geography | PUCT Project 55225 service-area filings | Useful for tracking owner acquisition attempts only. The PUCT calls these submitted boundaries approximate. They are not an asset or connectivity layer. |
| Distribution conductors/devices | No verified statewide public authoritative source | Unavailable. The denominator is null; no zero count or completeness statement follows. |
| Real electrical terminals/edges | No verified public source | Unavailable. Line endpoint names, proximity, imagery, and ACTIVSg2000 cannot create edges. |

## Exact counts are deliberately narrow

The 2025 EIA-860 early-release workbook was directly inspected on 2026-09-06:
it contained 1,514 Texas plant rows (none missing a reported latitude or
longitude), 2,376 operable-generator rows, 643 proposed-generator rows, and
207 operable-storage rows. EIA itself says the release is not fully edited,
may exclude pending-validation records, and is inappropriate for aggregation.
Those are source-workbook observations only, not statewide coverage
denominators. Use final EIA-860 with a retained checksum for a reproducible
inventory.

The HIFLD archive returned 94,619 national features. A Texas bounding-envelope
query returned 10,239 intersecting features, but the envelope includes
neighboring states. This number must never be displayed as a Texas total,
denominator, or coverage percentage. A later corridor artifact must select the
actual Texas polygon and preserve each feature's `ID`, `SOURCE`, `SOURCEDATE`,
`VAL_METHOD`, `VAL_DATE`, and `INFERRED` fields along with its native geometry.

## Handoff for the next focused work

The corridor/substation worker may acquire a polygon-selected HIFLD line
snapshot and make a `physical_observed` artifact only if it preserves source
feature identity, native geometry, field-level validation basis, retrieval
metadata, and the archive/version limitation. It must keep coverage
`partial_stale_public_overlay`; it cannot construct substation points or
connectivity from `SUB_1`/`SUB_2` values.

The inventory contract must map this ledger's source-decision rows to its
canonical class names (`line`, `generation`, `distribution_feeder`, and
`terminal`) before ingestion. All unknown or unavailable physical classes
retain a null denominator and null counts. The audit accepted zero
source-backed edges; that is an artifact-set observation, not a claim that the
Texas grid has zero connections.
