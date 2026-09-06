# Minnesota accepted artifact inventory (v1)

This inventory is limited to current, checked-in Minnesota evidence. It is a
coverage and truth-label boundary, not a source download, topology conversion,
or a claim that a renderable Minnesota map exists.

## Integrity and label policy

The only truth labels are `source_backed`, `synthetic`, `illustrative`, and
`unavailable`. For committed text evidence, the listed SHA-256 is calculated
over UTF-8 content after normalizing CRLF to LF. This is the repository form
and prevents a Windows checkout line-ending conversion from changing identity.

The aggregate manifest's `upstream_sha256_unverified_offline` values are
author-download claims: their raw upstream files are not checked in and this
inventory does not re-verify them. The manifest's pinned local evidence files
are checked below instead.

## Accepted current product artifacts

| Artifact | Checked-in evidence and canonical SHA-256 | Coverage and coordinates | License/terms | Truth-label policy |
| --- | --- | --- | --- | --- |
| `mn:aggregate:manifest:v1` | `pipelines/fixtures/inputs/minnesota_aggregate_manifest_v1.json` — `f287a1dfbafddff8bd9f0ec989d488ad6743609280b19338eca048c3d5858e05` | Aggregate-mode source metadata. TIGER is declared EPSG:4269 and MnGeo service areas EPSG:26915, but no corresponding geometry is checked in as a renderable product artifact. | Source URLs are recorded, but reusable terms are not preserved in the checked-in manifest. | `source_backed` metadata only; do not promote unverified-offline raw digests to verified raw data. No boundary/service-area render, topology, flow, loading, trip, or outage claim. |
| `mn:facility_capacity:county:2024` | `pipelines/fixtures/inputs/mn_county_plant_capacity_2024.csv` — `7757c6ece5c36a0ae15573acfe4dd2e02cb42e13a0aa9f8ac142663977e7d573` | EIA-860 2024 aggregate context: 73 counties with at least one uniquely assigned plant; 836 assigned plants and 18,211.53 MW. An absent county is not a zero-capacity claim. No geometry or facility coordinates. | The research inventory describes EIA data as public; this output retains no license text. | `source_backed` county aggregate only. It may support clearly labelled aggregate encoding once accepted county geometry exists; never facility placement, demand/dispatch, topology, interconnection, flow, or loading inference. |
| `mn:facility_context:unassigned:2024` | `pipelines/fixtures/inputs/mn_unassigned_plant_capacity_2024.csv` — `926f6fb65715df19af1eb833df1560c6e592827d7ea47ed54091cf3cf08a4ed6` | One EIA-860 plant with 1.0 MW retained as unassigned because no exactly-one containing county was established. Latitude/longitude fields are present, but their coordinate reference is not retained here. | The research inventory describes EIA data as public; this output retains no license text. | Facility identity/capacity context is `source_backed`; coordinate use is `unavailable`. Never map it, assign a county, or infer topology/interconnection. |
| `mn:ba_context:miso:2024-h1` | `pipelines/fixtures/inputs/miso_ba_context_2024_h1.csv` — `395dad9aea19226744f8be5f91ca30c783ab776d1720e6486ff64880b8366e6f` | 4,368 EIA-930 MISO balancing-authority records for 2024 H1, UTC end-of-hour and MW. It is explicitly not Minnesota demand and has no geometry. | The research inventory describes EIA data as public; this output retains no license text. | `source_backed` only when displayed as MISO BA context. Any Minnesota/county/service-area/facility allocation or topology/flow/loading/outage inference is `unavailable`. |

## Explicitly not accepted as current Minnesota product coverage

| Evidence | Truth-label policy | Boundary |
| --- | --- | --- |
| `synthetic_power_balance_preview` in `data/demo/bundle.json` | `synthetic` only. | An abstract offline preview, not Minnesota, Texas, ERCOT, MISO, or an actual interconnection. It cannot supply Minnesota topology, geography, facility, scenario, or conclusion coverage. |
| `gridsfm_minnesota_feasibility` in `docs/research/minnesota/solver-network-feasibility.md` | `unavailable` for product coverage. | GridSFM is feasibility evidence only. Its fields, units, version, terms, and converter mapping need a separate accepted decision before any topology value can be `source_backed`. |
| Raw TIGER or MnGeo geometry declared in the aggregate manifest | `unavailable` for rendering. | A declared CRS without checked-in source/derived geometry is not geographic coverage. |

## 3D asset taxonomy

| Class | Required fields | Truth-label policy | Current availability |
| --- | --- | --- | --- |
| `county_capacity_context` | `county_fips`, `plant_count`, `summer_capacity_mw`, `truth_label` | `source_backed` only for the accepted EIA-860 aggregate; missing counties are neither zero nor assets. | Available without geometry. |
| `facility_point` | `facility_id`, `name`, `longitude`, `latitude`, `coordinate_reference`, `truth_label` | `source_backed` only with accepted facility identity, CRS, and coverage; otherwise `unavailable`. Synthetic/illustrative points must not imply a Minnesota facility. | Unavailable. |
| `service_area_surface` | `service_area_id`, `geometry`, `coordinate_reference`, `source_artifact_id`, `truth_label` | `source_backed` only from accepted versioned geometry; it is retail-service geography, never a BA map, network, or allocation crosswalk. | Unavailable. |
| `topology_node` | `node_id`, `geometry`, `coordinate_reference`, `source_artifact_id`, `truth_label` | `source_backed` only after the topology decision gate verifies identity, mapping, and terms; otherwise `unavailable`. | Unavailable. |
| `topology_edge` | `edge_id`, `from_node_id`, `to_node_id`, `geometry`, `source_artifact_id`, `truth_label` | `source_backed` only after accepted endpoints or unambiguous geometry and electrical-field provenance; otherwise `unavailable`. | Unavailable. |
| `operating_overlay` | `asset_id`, `metric`, `unit`, `time`, `source_artifact_id`, `truth_label` | Flows, loading, trips, and outages are `unavailable` unless an accepted artifact supplies them; never infer them from service areas, county capacity, or MISO aggregates. | Unavailable. |
| `regional_time_context` | `series_id`, `balancing_authority`, `time`, `value`, `unit`, `truth_label` | `source_backed` only when displayed as MISO BA context; Minnesota geographic allocation is `unavailable`. | Available without geometry. |
| `synthetic_preview_network` | `fixture_id`, `model_mode`, `truth_label` | `synthetic` only; it is a non-Minnesota abstract preview and cannot combine with Minnesota geography or conclusions. | Available outside Minnesota product coverage. |
