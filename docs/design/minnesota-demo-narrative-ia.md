# Minnesota demo narrative and information architecture

**Status:** Gate 0 interaction and visual-prototype decision for 2WKG-363. This
document is a browser-design handoff, not an implementation, fixture, source
intake, or approval of a Minnesota model.

**Authoritative inputs:** the [Minnesota demo contract](../specs/10-minnesota-demo.md)
governs geography, model eligibility, claims, and API behavior. The
[shared overview](../specs/00-overview.md) governs the browser/server boundary;
the browser renders server artifacts and results and never reads DuckDB or
computes a result. The existing five-bus screen remains a separate abstract
synthetic preview; it must not be relabelled as this demo.

## Decision in one view

Flux answers a bounded question: **given approved Minnesota coverage and a
documented weather-stress artifact, what can the accepted model say about a
source-screened facility alternative, and what cannot it say?**

The story proceeds from coverage to evidence, not from a map-shaped claim to a
made-up network:

1. Establish the visible coverage boundary: documented utility/service-area
   geometry or explicitly named aggregate zones.
2. Show the weather-stress artifact inside that coverage, including its time,
   source, and limits.
3. Show exactly one accepted model result: initially the aggregate regional
   metric; topology results only after the network decision gate accepts a
   solver-complete Minnesota source.
4. Compare an already source-screened facility alternative inside that model's
   stated scope. It is a hypothetical comparison, not a project,
   interconnection request, permit finding, or construction recommendation.
5. Let the Copilot explain the result by exposing its tool outputs and citations
   alongside the same limits. It does not fill missing evidence with prose.

The initial default is **aggregate mode**. It uses a named regional metric,
formula, unit, artifact IDs, limitations, and an allocation basis supplied by
the server -- and where the server reports no accepted allocation, the scene
renders that fact rather than a number. That is today's live case, not a
hypothetical: the only Minnesota aggregate manifest on `master`
(`pipelines/fixtures/inputs/minnesota_aggregate_manifest_v1.json`) records
`"allocation_status": "unavailable"` with the limit "No reviewed complete,
non-overlapping BA-to-service-area crosswalk is available; MISO BA values are
not allocated to Minnesota geography." So the default scene shows the metric
beside an explicit unavailable allocation row, and never an inferred split. It never draws or implies buses, transmission lines, towers, loading,
flows, contingencies, trips, cascades, or statewide topology. A topology scene
is disabled until the `10-minnesota-demo.md` network decision gate is accepted;
the shipped five-bus fixture is not its fallback.

## Primary questions and scene modes

| Question the presenter can ask | Guided scene | Required server artifact/result | Must not imply | Delivered by (state on `master`) |
| --- | --- | --- | --- | --- |
| What part of Minnesota does this demo cover? | **Coverage** | Geometry artifact plus source, version, coverage statement, and precision limit | Statewide electrical coverage or inferred utility territory | `mn_geography_artifacts` exists (`pipelines/minnesota_schema.py`); rows planned by **2WKG-99** (fixture), read route planned by **2WKG-104/105** |
| What documented stress are we considering? | **Stress** | Weather-stress artifact with time window, location coverage, source, and limitation | An outage replay or causal attribution | `mn_scenario_artifacts` exists; intake **2WKG-137**; the producing "weather scenario execution" row in `10-minnesota-demo.md` carries **no ticket yet** |
| What does the model say here? | **Aggregate metric** (default) | Named metric, value, unit, formula, model mode, provenance, limitations, and either an accepted allocation basis or an explicit `unavailable` allocation row | Power flow, line loading, an outage simulation, or an interconnection study | `mn_model_results` exists; the producing "model adapter/validation" row in `10-minnesota-demo.md` carries **no ticket yet** |
| What changes when this facility alternative is compared? | **Facility comparison** | Ranked/compared artifact with metric components, regulatory label, model mode, evidence, and limitations | A siting recommendation, permitability, or commercial readiness | `mn_score_results` exists; planned by **2WKG-107** (contract) and **2WKG-112** (result integration) |
| Why should I trust or limit that answer? | **Evidence** | Exact artifact metadata, `cite` hits, tool results, and failure envelopes | A Copilot-generated number or legal conclusion | `mn_citation_hits` exists; corpus planned by **2WKG-128**; the Ask route and its stream are planned by **2WKG-147** and **2WKG-126** and **do not exist on `master`** |

Every row above is a dependency statement, not a completion claim. Of the
routes this IA needs, no Minnesota read route and **no `/ask` route exist on
`master`** today: `copilot/app.py` mounts exactly five routers -- health,
layers, interventions, scenarios, predictions. The chat dock in the prototype
below is therefore entirely planned surface (2WKG-147 over the 2WKG-126 stream)
and must not be shown in a rehearsal as if it were live. Where this table says
"no ticket yet", the corresponding row in `10-minnesota-demo.md`'s execution
graph is unnumbered, which that spec defines as "a pending gap that must be
assigned before execution"; this IA does not assign it.

`Topology` is not a presentation fallback or a sixth default scene. When its
accepted source/model contract exists, it may be added as a separately labelled
scene. Until then, its control is disabled and explains which accepted artifact
is missing. The same rule applies to any facility scene with no accepted scoring
artifact: it shows an unavailable state rather than a ranking.

## Desktop visual prototype

The target rehearsal viewport is desktop-first: 1440 x 900 CSS pixels at 100%
zoom. It retains a 64 px top bar, a 300--360 px right inspector, a 320 px
expanded chat dock, and at least 640 px of visible coverage viewport. On a
narrow viewport, the inspector and chat dock become mutually exclusive sheets;
the status strip stays visible.

```text
+--------------------------------------------------------------------------------------------------+
| FLUX / MINNESOTA DEMO   [Coverage v] [Historical weather stress v] [Aggregate mode] [Evidence] |
| per region -- coverage: Source-supported | model: aggregate mode | facility: Hypothetical |
+-----------------------------------------------+------------------+-------------------------------+
| Guided scenes:  1 Coverage > 2 Stress > 3 Metric > 4 Facility > 5 Evidence                     |
+-----------------------------------------------+------------------+-------------------------------+
|                                               | INSPECTOR        |                               |
|                                               | 1. Selection     |                               |
|        COVERAGE VIEWPORT                      |    Named zone /  |                               |
|  [documented service-area geometry OR         |    facility      |                               |
|   labelled aggregate zones]                   | 2. Answer        |                               |
|                                               |    metric/value  |                               |
|  weather-stress overlay (when selected)       | 3. Why this is   |                               |
|  facility marker only if its artifact         |    visible       |                               |
|  defines location/coverage                     |    formula, unit |                               |
|                                               | 4. Evidence      |                               |
|  No inferred lines, towers, buses, or flow.   | 5. Limits/status|                               |
+-----------------------------------------------+------------------+-------------------------------+
| LAYERS: [coverage] [weather stress] [aggregate metric] [facility alternatives] [evidence]      |
| SCENARIO: time/region labels from selected artifact | model: aggregate | all controls artifact-bound |
+--------------------------------------------------------------------------------------------------+
| CHAT DOCK (collapsed by default)  Ask about this visible evidence... [Ask]                      |
| Tool trail: cite > model/scoring read > sql (only if invoked)     Citations / limits / done     |
+--------------------------------------------------------------------------------------------------+
```

The viewport is a coverage/evidence surface, not a visual substitute for a
network model. It may draw only geometry returned by an accepted server artifact:

- `coverage` is always first and includes the source/version label in its legend.
- `weather stress` is available only when the selected scenario artifact bounds
  its geography and time.
- `aggregate metric` renders named zones and server-provided values, units, and
  allocation labels; it never reuses a topology color scale or line glyph.
- `facility alternatives` renders only source-screened alternatives with an
  explicit regulatory/hypothetical label. A marker does not mean a viable site.
- `evidence` opens the provenance drawer; it does not add unverified map detail.

Layer controls are declarative visibility choices over returned artifacts. The
client may not join data, derive a score, interpolate missing values, estimate a
location, or silently substitute a fixture. If an artifact does not permit a
layer, that control is absent or disabled with its named reason.

## Inspector and interaction contract

The inspector has a fixed hierarchy so a visual highlight never becomes an
unsupported claim:

1. **Selection:** what the user selected, its coverage relationship, and its
   truth label. Selection can be a named zone, weather-stress artifact, or
   source-screened facility alternative; it is never an inferred line or bus.
2. **Answer:** the exact server-returned metric/comparison value, unit, model
   mode, and comparison basis. No client-side total, delta, ranking, or fallback
   number is allowed.
3. **Interpretation:** the returned formula/allocation basis and only the
   bounded statement that follows from it.
4. **Evidence:** artifact ID, source/version/retrieval time where supplied,
   input IDs, citation hits, and tool-result references.
5. **Limits and next step:** limitations, regulatory label, and an actionable
   next step for the returned failure envelope (`status` is `unavailable` or
   `error`). This section is never collapsed behind a
   success badge.

Interaction is one-way: guided-scene selection changes the visible artifact
selection and inspector focus; a viewport selection changes only the inspector
selection; a chat tool-result link may focus the matching server artifact. A
scene switch never changes model mode or scenario values by itself. Changing
scenario, region, or model mode sends an explicit read request and replaces the
view only with its returned payload, or with the failure envelope -- `master`
has no success envelope, so a successful read is an unwrapped payload
(`copilot/api/envelope.py`: "Only the failure envelope is returned from
routes"). The UI retains the prior result
with a `stale` disclosure while waiting; it does not fabricate an optimistic
preview.

The implementation state boundary is deliberately small:

```text
selectedScene + selectedArtifactId + selectedFeatureId + layerVisibility
+ selectedScenarioId + returnedServerPayloadOrFailureEnvelope
    -> rendered viewport, inspector, guide, and chat context

No browser state is a database handle, solver input, provenance generator,
score calculation, legal conclusion, or topology inference.
```

## Chat dock role

The chat dock is evidence-first and contextual, not a second analysis product.
It receives the current scene and artifact identifiers as context, while the
server remains the only caller of read-only tools. It shows this ordered trail:

1. question and current coverage/model context;
2. visible `tool_call` and `tool_result` events;
3. exact citation cards (document, title, page, chunk ID, score, text);
4. answer text that links back to the inspector artifacts; and
5. exactly one terminal state with the same limitations: either `done` or
   `error`, never both and never a third. An unavailable dependency is not a
   terminal state of its own -- it arrives as `error` whose `error.code` is
   `unavailable`, and is rendered with the Unavailable label. This is the closed
   contract in `../research/sse-event-schema.md` (the `done` and `error`
   sections, and "exactly one terminal event: one `done` or one `error`, never
   both"), which `00-overview.md` amendment A10 makes authoritative over this
   document: no route or client invents a second event shape.

The browser streams and displays the documented SSE events from the server. It
does not query DuckDB, call a solver, calculate a score, synthesize a citation,
or turn a provider failure into a canned answer. A static transcript is allowed
only as the contract's visibly labelled failure fallback with retained cited
artifacts.

**Reconciliation with `../specs/06-frontend.md`.** 06 remains the repo's frontend
spec and its Ask panel defines a map linkage that fires on tool names --
"`run_cascade` -> sets `hour` and plays the cascade", plus `score_site`,
`predict_outage`, and `top_lines` bindings (`06-frontend.md`, "Map linkage") --
and the shipped registry still exposes all nine tools
(`copilot/tools/schemas.py`). Applied unchanged to this surface, a single
`tool_call` for `run_cascade` would animate a cascade, which is the statewide
topology claim this document bans and `10-minnesota-demo.md` gates. So for the
Minnesota surface only, this IA supersedes 06's tool-to-map linkage: in
aggregate mode every tool outside {`cite`, `sql`, and the accepted Minnesota
model/scoring reads} renders as an inert evidence chip carrying its name and an
unavailable reason, and drives no scene, layer, hour, selection, or camera
change. 06's linkage continues to govern the existing Texas/five-bus screen
unchanged. This paragraph constrains a browser behaviour only; it changes no API,
no tool registry, and no event shape.

## Truth-label visual system

Every result-bearing surface--top-bar strip, map legend, inspector Answer,
facility card, chat result, and exported/rehearsal frame--carries one primary
state label. Text is mandatory; hue alone is never the signal. This IA defines
no machine-readable vocabulary of its own. Each UI label below is **derived
from a field that already exists on `master`**, named in the second column; a
label with no such producer is not in the system. The UI-side names are display
strings, and the server tokens quoted in the second column are the exact values
to switch on.

| UI label | Derived from (server field on `master`) | Visual treatment | Required accompanying copy | Meaning and interaction |
| --- | --- | --- | --- | --- |
| Source-supported | `mn_score_results.regulatory_label == "source_supported"` (`../specs/10-duckdb-contract.md`, `mn_score_results`) | solid teal label with check glyph | source/artifact ID and scope | Returned value or geometry directly supported by the recorded source; opens Evidence |
| Source-screened | `mn_score_results.regulatory_label == "source_screened"` (same row) | teal outline with half-check glyph | source/artifact ID, scope, and what screening did not establish | Screened against the recorded sources but not source-supported; never presented as a finding |
| Hypothetical | `mn_score_results.regulatory_label == "hypothetical"` (same row) | violet outline with arrow glyph | regulatory label and "not a recommendation" | An alternative compared inside the model's stated scope; never rendered as permitted, approved, or ready to build |
| Synthetic | `scenarios` response `source_kind` in `fixture`/`simulated` with `topology == "synthetic (ACTIVSg2000)"` (`copilot/routes/scenarios.py`) | indigo label with dotted fill | synthetic artifact ID and scope | Identified synthetic artifact only; never positioned or described as Minnesota infrastructure unless its own accepted contract says so |
| Unavailable | `mn_artifact_manifests.availability == "unavailable"`, or `FailureEnvelope.status == "unavailable"` (`copilot/api/envelope.py`), or an SSE terminal `error` whose `error.code == "unavailable"` | amber outline with blocked glyph | missing prerequisite and named next step | Required artifact is absent, unbuilt, stale, or ineligible; hide dependent value/layer |
| Request failed | `FailureEnvelope.status == "error"` (`copilot/api/envelope.py`), or an SSE terminal `error` with `status: "failed"` (`../research/sse-event-schema.md`) | red outline with error glyph | safe message, request ID if supplied, retry guidance | A request or provider failed; preserve last result as stale but do not call it current |

Two supporting facts, not labels of their own: `mn_artifact_manifests.model_mode`
(`topology`/`aggregate`/`not_applicable`) is shown as the mode chip, and
`mn_model_results.validation_status` gates whether a model result is shown at
all. An earlier draft of this table also carried an "Illustrative" label for
decorative, non-analytic visuals. It is deliberately removed: nothing on
`master` produces it, no ticket would, and a label the server cannot assert
would have to be invented by the browser -- exactly what the
`00-overview.md` boundary forbids. If a decoration is ever needed, it must
arrive with its own server field and its own work item first.

Status may be compounded only by nesting, never by replacing the primary claim:
for example, a Hypothetical facility card can contain a Source-supported
inventory field and an aggregate-mode result, but its header remains
Hypothetical. Any missing required evidence wins: the dependent card becomes
Unavailable; any request failure wins for the current attempt. The visual system
must meet text contrast requirements and pair every glyph/pattern with a
readable label.

## Rehearsal beats

| Beat | Presenter action | Audience sees | Required honest line |
| --- | --- | --- | --- |
| 1. Bound the view | Open Coverage | documented boundary or named zones, source badge, precision limit | "This is the coverage in this artifact, not statewide topology." |
| 2. Establish stress | Select the bounded winter weather artifact | time/location range, weather overlay, limitations | "This is documented weather stress, not an outage replay." |
| 3. State model boundary | Open Aggregate metric | metric, unit, formula, allocations, aggregate badge | "This is a regional aggregate model; it does not show flows, loading, or outages." |
| 4. Compare an alternative | Select a facility alternative | source-screened fields, comparison result if available, regulatory label | "This is a hypothetical comparison, not a siting or permitting recommendation." |
| 5. Prove the answer | Ask a primary question in chat | tool trail, citation card, links to inspector evidence | "The Copilot narrates returned evidence; it does not calculate." |
| 6. Show a hard stop | Select unavailable topology or disconnect provider | Unavailable or Request-failed card with named next step | "We do not substitute the abstract fixture or guess the missing result." |

Suggested questions are intentionally bounded: "What coverage does this artifact
support?", "What is the documented weather-stress window?", "What does the
aggregate metric measure?", and "What evidence and legal label limit this
facility comparison?" The UI must refuse/reframe questions that ask for a line
flow, trip, statewide topology conclusion, or permitting outcome without the
accepted artifact that would support it.

## Non-goals and handoff acceptance

This document does not select sources, approve topology, create a Minnesota
fixture, obtain data, design a component library, change APIs, or implement the
browser. It specifically does not make a statewide Minnesota topology claim.

A follow-on UI/API owner can treat this IA as satisfied only when a rehearsal
frame contains the prototype regions above, uses server-returned artifacts only,
keeps aggregate mode topology-free, renders every truth label whose server
producer exists in readable form (and renders no label that has none), and can
perform the six beats without replacing an Unavailable or Request-failed state
with synthetic content. Source/model eligibility and
response schemas remain the responsibility of their source-of-truth contracts,
not this document.
