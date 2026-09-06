# Minnesota demo amendment — canonical scope and execution contract

**Status:** planning authority for the hackathon Minnesota demo. This document changes
scope and contracts only; it does not authorize implementation, a source download, or a
relabel of the current offline fixture.

## Authority and boundaries

This amendment supersedes the Texas geography, ERCOT, Uri/Beryl/Helene scenarios,
ACTIVSg2000 topology, Texas/NY site framing, old model-provider defaults, and demo
acceptance language in specs 00–09 wherever they govern the Minnesota demo. Neutral
engineering patterns can be reused only after this document's source and model gates.

Do not call the existing five-bus fixture Minnesota, Texas, ERCOT, MISO, or an actual
interconnection model. Do not relabel ACTIVSg2000 as Minnesota. Minnesota is a bounded
hackathon demonstration, not a statewide operations platform, RTO EMS, regulatory
decision, or national platform.

The core pitch is a grounded **Copilot**. The map and scoring flow are evidence surfaces
for a Copilot answer, and each demo path ends in visible evidence and limits.

## Source basis and first decision gate

| Need | Primary starting source | Supports | Does not establish |
|---|---|---|---|
| Geography and service areas | [MnGeo public utilities information](https://mn.gov/mngeo/gis-data-and-maps/info-by-topic/utilities-telecommunications/utilities.jsp) | State utility information and service-area boundary availability | Complete redistributable electrical solver input |
| Plant/generator inventory | [EIA Form 860 detailed data](https://www.eia.gov/electricity/data/eia860/) | Generator capacity, status, fuel, and location | Bus mapping, ratings, impedance, or power-flow feasibility |
| Weather-stress candidate | [NWS January 2–4, 2023 heavy snow](https://www.weather.gov/fsd/20230103-HeavySnow-CWA) | Documented southwest-Minnesota weather event | Observed grid outage replay or causal attribution |
| Legal constraints | [Minn. Stat. §216B.243](https://www.revisor.mn.gov/statutes/cite/216B.243) and [MN PUC certificate-of-need guide](https://puc.eip.mn.gov/certificates-of-need) | Current certificate-of-need and construction constraint research | Legal feasibility from a score or physics result |

### Network decision gate

Mira/Ghadi produce a source decision record and manifest within one focused intake
session. Select topology mode only when one public or licensed source provides all items
below, with units, version, terms, and per-field provenance:

1. Bus identity and a Minnesota boundary/region mapping.
2. Branch identity, endpoints or unambiguous geometry, and electrical impedance/reactance.
3. Base MVA, load and generation allocation, and thermal ratings.
4. Terms permitting the intended fixture and demo use.
5. A documented mapping from source fields into the chosen solver.

If any item is absent, select aggregate mode. Aggregate mode publishes one named regional
stress metric, formula, units, regional allocation assumptions, and source/synthetic status.
It must not emit or imply bus flows, line ratings/loading, DC power flow, N-1 conclusions,
trips, cascades, or an interconnection study. The demo calls that path a Minnesota
aggregate stress model, not a grid twin.

This blocks topology-mode implementation until the record is accepted. Aggregate-mode work
may proceed once it has the transparent metric contract below; neither path is bypassed with
ACTIVSg2000, ERCOT records, or fabricated Minnesota topology.

### Existing teammate feasibility evidence

Open [PR 14](https://github.com/2WKG/flux/pull/14) records a teammate's parse of the MIT-licensed GridSFM release 2026_05_07:
Minnesota has 718 buses, 1,297 branch records, and 97 generators, with a reported
strict AC-OPF solve for its supplied snapshots. This is promising source evidence, not
automatic production acceptance. Its records are PowerModels/MATPOWER-structured JSON,
the supplied target is a July 2024 snapshot, and demand is population-allocated rather
than a winter time series. The source decision record must still verify its actual
bus/branch impedance, base-MVA, ratings, load/generation, unit, license, and converter
field mapping before model work consumes it. The converter is a named work item; no
existing Texas topology is reused.

## Geography, fixture, and scenario contract

The fixture owner creates a versioned source manifest before a data artifact. It records an
artifact ID, Minnesota geography, topology or aggregate model mode, source URL, retrieval
time, license/terms, geographic coverage, per-field provenance, and fallback label.

The map boundary is a documented Minnesota service-area/utility geometry or named
aggregate zones. The UI never shows precision beyond the boundary. EIA-860 may supply
candidate inventory attributes only with a preserved record version and matching method.
A candidate is an analytical alternative, not a project, interconnection request, permit
finding, or legal recommendation.

The initial candidate scenario is mn_winter_2023_snow, using the NWS event above. Before
it appears in a result, its exact time range, location coverage, and values are retained in
the manifest. It is labelled **historical weather stress**. It becomes an outage replay only
with a separate observed-outcome artifact and stated matching method; neither is assumed.

## Regulatory and intervention claim boundary

Minnesota Statutes §216B.243 currently states that the commission may not issue a
certificate of need for construction of a new nuclear-powered electric generating plant.
The same statute sets certificate-of-need requirements for large energy facilities.

- Nuclear additions are excluded from an actionable recommendation unless a current
  primary-law review changes that result.
- A physics or scoring output can be a **hypothetical model comparison** only. It cannot
  claim permitability, site legality, commercial viability, or construction readiness.
- The legal research artifact cites its governing source, retrieval date, and exact approved
  wording used by the Copilot and UI.
- Every intervention is labelled hypothetical, source-screened, or source-supported; none
  means permitted.

The 2026 nuclear-study session law is context, not a replacement for the direct statute.
The regulatory task rechecks the direct statute before rehearsal.

## Model and scoring contracts

### Topology mode

William owns an explicit base-MVA, units, source-to-model field mapping, solver version,
and input validation contract. A missing rating, reactance, load, generation, or region
mapping yields an unavailable result rather than a guessed value. A result contains model
mode, input artifact IDs, assumptions, and limitations.

### Aggregate mode

William owns a transparent regional calculation. Its result includes named metric, value,
unit, formula, named regions with their allocation basis, input artifact IDs, assumptions,
and a limitation that it is not a transmission-flow or outage simulation.

Site/intervention scoring ranks only within the selected model contract. It retains its
metric, artifacts, score components, model mode, and regulatory label. It cannot turn a
score into a construction recommendation.

## Stable APIs and required Copilot contract

Joshua owns backend/integration. Endpoints are versioned read surfaces over accepted
artifacts. Missing source, model, corpus, or configured provider returns a documented
unavailable result. Every available numeric/model result contains nonempty provenance, model
mode, and limitations. Documented consumer fields stay top-level.

**Envelope scope (D-1).** "Unavailable envelope with status, code, message, empty provenance and
a named next step" describes the **tool-result payload**
([`10-duckdb-contract.md`](10-duckdb-contract.md) §"Artifact availability on a tool result"), not
the HTTP response. On the wire the failure contract is
[`../api/envelopes.md`](../api/envelopes.md) / `copilot/api/envelope.py`, whose `FailureEnvelope`
is `extra="forbid"` and therefore carries no `availability`, `next_step`, top-level `code`,
`provenance`, or `limitations` field at all; the named cause travels in `error.details.reason`.
No tool on `master` emits the re-scoped payload shape either — it is the intended shape, tracked
as follow-up **FU-3** in the section linked above, not current behaviour.

The Copilot is required in the primary demo flow. Its provider/model comes from validated
runtime configuration; planning must not invent a model identifier or make a paid API call.
A configuration test proves only ready or unavailable behavior.

Copilot tool behaviors:

| Tool | Permitted behavior | Required evidence |
|---|---|---|
| cite(query, k) | Retrieve from versioned local corpus | doc, title, page, chunk ID, score, text |
| sql(query) | One read-only SELECT/WITH query against approved local views | query identifier, rows/columns, truncation |
| model/scoring reads | Fetch accepted Minnesota scenario/score artifact | artifact ID, model mode, limitations |

SQL uses a read-only connection, single-statement allowlist/denylist, row/time caps, and
no write/export/attach capability. The Copilot does not calculate, infer legal feasibility,
or state a numerical recommendation without tool evidence. Citation assertions match
returned cite fields exactly.

The ask endpoint streams browser-consumable SSE through fetch and ReadableStream with
text, tool_call, tool_result, citation, done, and error events. Browser acceptance proves a
streamed answer, visible tools, exact citation hit, and unavailable-provider path. A static
evidence card or prerecorded local transcript is a failure fallback only when visibly
labelled fallback and retaining its cited artifacts.

## Demo flow and acceptance

The external URL and offline/static fallback both show:

1. Minnesota boundary and source/provenance label.
2. Documented weather stress and limits.
3. Source-backed topology result or clearly marked aggregate metric.
4. Ranked intervention with regulatory label.
5. Copilot question answered through visible read-only tools and citation retrieval.
6. Unavailable source/model response that explains its boundary without guessing.

An independent browser rehearsal accepts the demo only when:

- External URL opens the flow and offline/static fallback opens without provider credentials.
- UI distinguishes source-backed, synthetic, aggregate, and unavailable data.
- A citation shows exact retrieved doc, title, page, chunk ID, score, and text.
- A read-only SQL tool exposes only approved capped output.
- A streamed response has tool/citation/done events; unconfigured provider returns unavailable.
- No screen, script, or Copilot answer calls the data Texas, New York, ERCOT, Uri, or
  ACTIVSg2000.

## Executable work graph and ownership

| Key | Owner | Predecessors | Output and acceptance gate |
|---|---|---|---|
| MN01 | Mira/Ghadi | — | Network source evidence matrix; choose topology only with solver-complete fields or aggregate fallback. |
| MN02 | Mira/Ghadi | — | Primary source/citation corpus manifest; each claimed number has evidence or a fallback label. |
| MN03 | Mira/Ghadi | — | Current regulatory/nuclear bounds and approved claim language. |
| MN04 | Joshua | MN02 | Copilot shared contract and provider-availability envelope. |
| MN05 | Mira/Ghadi | MN01, MN02 | Minnesota region/fixture mapping with version and fallback labels. |
| MN06 | William | MN01, MN05 | Validated topology or explicit aggregate model contract. |
| MN07 | William | MN02, MN05, MN06 | Time/location-bounded weather-stress scenario; no replay claim without outcome evidence. |
| MN08 | William | MN03, MN06, MN07 | Provenance-preserving score with regulatory status. |
| MN09 | Joshua | MN04, MN05, MN08 | Stable read API and unavailable envelopes. |
| MN10 | Joshua | MN05, MN09 | Map/scenario/score/Copilot browser integration. |
| MN11 | Joshua | MN04, MN10 | External URL, failure fallback, and independent rehearsal evidence. |

Critical path: **MN01 → MN05 → MN06 → MN07 → MN08 → MN09 → MN10 → MN11**.
MN02, MN03, and MN04 run in parallel at the front; MN04 joins MN09 and MN11. Files shared
by model, fixtures, schemas/configuration, or deployment state remain serial at their
dependency gate.

## Handoff evidence

Before implementation begins, the owner attaches selected model mode/source decision,
artifact IDs and URLs, input/output envelope and unavailable behavior, and focused
verification tied to the acceptance gate. This replaces legacy Texas execution queues.
Existing work remains reviewable on its own branch; it is not silently repurposed as
Minnesota work.

## Execution graph amendment: granular Linear work units

The keys MN01–MN11 above are delivery milestones, not a reason to collapse existing
children into large assignments. The executable graph below reuses the live board's
children. Parent records 10, 13, 89, 92, 94, and 95 are progress rollups, not implementation
dependencies. It is a dependency map, not a completion claim: an unnumbered row is a
pending gap that must be assigned before execution, and a numbered row remains pending
until its own acceptance evidence exists.

Verification snapshot, 5 September 2026: source work 134 and 135 has open PRs
[38](https://github.com/2WKG/flux/pull/38) and [34](https://github.com/2WKG/flux/pull/34);
134, 135, 137, and 140 are independently ready after removal of the prior source-cycle.
97, 103, 124, 125, and 101 have open PRs
[20](https://github.com/2WKG/flux/pull/20), [17](https://github.com/2WKG/flux/pull/17),
[10](https://github.com/2WKG/flux/pull/10), [19](https://github.com/2WKG/flux/pull/19),
and draft [41](https://github.com/2WKG/flux/pull/41), respectively. The current
fixture foundation is 156 in open [PR 23](https://github.com/2WKG/flux/pull/23),
with follow-on fixture work in PR 26. PR 20 and the current ingestion stream
([PR 27](https://github.com/2WKG/flux/pull/27)) require
the separately assigned 2WKG-293 collision reconciliation before they are integrated;
that existing work is assigned to Joshua and must not be duplicated.
No active regulatory-boundary work item was verified; that row is deliberately pending.

| Work unit | Owner | Immediate predecessors | Output / file boundary |
|---|---|---|---|
| 134 source/citation inventory | Mira | — | Primary-source manifest and corpus intake list |
| 135 source/model feasibility | Mira | — | Solver-field/license matrix and source-adapter decision |
| 137 weather/geography evidence intake | Mira | — | Bounded weather and geographic evidence for scenario selection |
| 140 demand-history/geography assessment | Mira | — | Usable demand-history and geographic resolution decision |
| regulatory scenario bounds **(PENDING: no active work item verified)** | Mira/Ghadi | — | Current-law claim language and weather evidence boundary |
| 97 target data contract | William | — | Deterministic input/rebuild contract |
| 98 typed data schema | William | 97 | Shared Minnesota artifact schema |
| 103 shared envelopes | William | — | Available/unavailable result envelopes |
| 124 Copilot contracts | Joshua | — | Top-level tool/result/provenance contracts; existing review remains distinct |
| 99 Minnesota fixture | Mira | 97, 98, 135 | Versioned fixture and region mapping; source adapter cannot proceed before feasibility (current fixture foundation: 156 / PR 23) |
| model adapter/validation | William | 98, 99, 135 | Topology validation or aggregate metric contract |
| weather scenario execution | William | 99, model adapter/validation | Time/location-bounded scenario artifact |
| 107 scoring artifact contract | Mira | 98, 99, model adapter/validation | Provenance and score-field contract |
| 108/109 scoring inputs and semantics | William | 107, weather scenario execution, regulatory scenario bounds | Bounded intervention inputs and claim labels |
| 110 calculation implementation | William | 108/109 | Validated calculation over accepted artifacts |
| 112 scoring result integration | William | 110 | Intervention comparison with claim label |
| 128 corpus implementation | Joshua | 98, 124, 134 | Versioned local corpus and exact retrieval metadata; Mira owns source collection 134 |
| 123 read-only SQL | Joshua | 97, 98, 124 | Approved views, read-only guard, capped outputs |
| 125 provider/config | Joshua | — | Ready/unavailable provider configuration behavior |
| 126 SSE transport | Joshua | 103, 125 | Browser stream events and provider-mock behavior |
| 127 narration/tool runtime draft | Joshua | 124, 125 | Grounded tool loop and evidence rules against stable contracts |
| real-tool narration acceptance | Joshua | 123, 127, 128, 104/105 | Evidence from real bounded tools, not mock-only narration |
| 101 API scaffold | Joshua | 97, 98, 103 | Read API skeleton and response validation |
| 104/105 real API routes | Joshua | 99, 112 scoring result integration, 101 | Fixture/model/scoring read routes |
| UI scaffold | Joshua | 103 | Status-labelled map and Copilot shell |
| 92 Copilot runtime | Joshua | 123, 125, 126, 127, 128, real-tool narration acceptance | Joined Copilot service; parent rollup only |
| 89 API integration | Joshua | 101, 104/105 | Joined API; parent rollup only |
| 94 browser integration | Joshua | 89 API integration, 92 Copilot runtime, UI scaffold | Real map/API/Copilot browser flow |
| 147 Ask endpoint | Joshua | 123, 125, 126, 127, 128 | Copilot Ask endpoint over the real runtime |
| 129 end-to-end evidence | Joshua | 94 browser integration, 104/105 real API, 112 scoring result integration, 126, 127, 128, 147 | Browser evidence for real tools, citations, and unavailable state |
| 17 integration/rehearsal children | Joshua | 94 browser integration, 129 end-to-end evidence | Existing integration/rehearsal work; do not create a duplicate |
| 87 freeze check | Joshua | 17 integration/rehearsal children | Existing demo-freeze evidence |
| 149 provisioning/domain preparation | William | 124, 125 | Environment and domain preparation; may start before real browser evidence |
| 84–86 deployment checks | William | 87 freeze check, 149 provisioning/domain preparation | Existing deployment checks |
| 95 deployment/rehearsal | William | 84–86 deployment checks | Cutover, external URL, scripted offline/static fallback |

Initial parallel frontier is 134, 135, 137, 140, regulatory scenario bounds, 97, 103, 124,
and 125. The typed schema follows the target data contract. The only source-specific wait is
the real fixture/source adapter. SQL does not wait for
the citation corpus; corpus construction does not wait for provider setup; narration does
not wait for transport. Causal research, predictive ML, nationwide-grid work, and real-time
ingest are stretch work and do not gate this demo.
