---
title: "Texas workspace narrative and information architecture"
status: draft — geography and product-scope authority pending
issue: 2WKG-309
base: 880b55a2ec517bd71c3816ef6200459012c8f403
---

# Texas workspace narrative and information architecture

## Purpose and boundary

This is a reviewable interaction proposal, not a statement that a Texas
workspace, its geography, data, or effects are available. It may be used with
approved Texas inputs after the scope decision. Until then, every screen uses
labelled example fixtures and an unavailable geometry state.

The workspace follows a repeatable decision path:

1. orient to the current workspace and its evidence state;
2. select a declared scenario or comparison context;
3. inspect an asset, corridor, or place only when the delivered data identifies
   it;
4. compare a bounded proposal with its returned evidence; and
5. ask the copilot to explain returned results and their sources.

No example label in this document identifies a real facility, corridor,
location, score, result, or outcome.

## Information architecture

| Area | User purpose | Primary content | Empty/unavailable behavior |
| --- | --- | --- | --- |
| Workspace header | Establish context before interpretation | workspace name, scenario selector, timestamp, source/status strip | “Workspace context unavailable”; controls remain non-committal |
| Viewport | Orient and select delivered spatial entities | 3D scene, map fallback, selection focus, camera presets | A deliberately blank geometry field with an explicit unavailable label; never substitute a plausible map |
| Layer rail | Control visibility and interpret visual marks | layer names, legend, count, source/vintage/coverage/status | Retain each layer row and show unavailable or empty state rather than hide it |
| Inspector | Answer “what is selected, and what supports it?” | identity, attributes, provenance, uncertainty, linked evidence | Preserve selection context and name missing fields as unavailable |
| Scenario rail | Establish a comparison before results are read | selected scenario, baseline, timestamp, assumptions, reset | Disable comparison action with a reason and recovery path |
| Proposal tray | Frame a possible change without presenting it as approved | proposal inputs, validation state, returned comparison evidence | “No proposal result returned” with no implied benefit |
| Copilot dock | Explain product-returned evidence | prompt, tool trace, citations, result state | Explain that no answer can be grounded until a result/source is available |
| Guided scenes | Support a short review or demonstration | named visual presets and narration prompts | A preset may frame controls, but must not create geometry or metrics |

### Desktop hierarchy

```
┌──────────────── workspace header + persistent evidence/status strip ────────────────┐
│ workspace | scenario | as-of | topology/source class | coverage | status | reset  │
├───────────────┬──────────────────────── viewport ─────────────────────┬─────────────┤
│ Layer rail    │ camera / scene / selection                             │ Inspector   │
│ legend        │                                                        │ identity    │
│ visibility    │  unavailable geometry is an intentional scene state    │ provenance  │
│ truth labels  │                                                        │ caveats     │
├───────────────┴──────────────────── scenario + proposal tray ──────────┴─────────────┤
│ guided scene steps                                              copilot dock          │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

On a narrower desktop, the inspector becomes a right-edge drawer and the
proposal tray stacks below the viewport. The evidence/status strip remains
visible in either layout.

## Narrative beats

| Beat | Question | Interaction | Required disclosure | Safe draft rendering |
| --- | --- | --- | --- | --- |
| 1. Orient | What am I looking at? | Open workspace and read the strip | source class, coverage, as-of, status | labelled fixture shell, geometry unavailable |
| 2. Focus | What can I inspect? | Select a layer or result returned by the product | identity and provenance before metrics | selection placeholder only |
| 3. Understand | Why is this visible? | Open inspector evidence tab | source, transformation/model state, caveats | “No delivered evidence” |
| 4. Compare | What changed under this declared proposal? | Set scenario and request comparison | baseline, proposal, assumptions, returned state | disabled comparison with reason |
| 5. Explain | Can the system substantiate the result? | Ask copilot; inspect tool trace/citations | result status and citations | unavailable-answer response |
| 6. Reorient | How do I return to a known context? | Reset scenario, selection, and camera | reset does not erase provenance | reset to unavailable fixture shell |

## Truth-label model

The renderer must accept the canonical 3D status vocabulary from the delivered
scene contract unchanged. The exact UI-status tokens are
`source_supported`, `source_screened`, `hypothetical`, `synthetic`,
`unavailable`, and `request_failed`. Artifact provenance remains a separate
three-value layer: `source_backed`, `synthetic`, or `unavailable`. A status is
shown both in the persistent strip and next to any selected entity or result.

The Linear request uses the words “source-backed, synthetic, illustrative,
unavailable, failure, and proposal.” They are not one interchangeable status
axis. The requested word **illustrative** conflicts with the frozen 3D
contract: no server field asserts it and the browser must not display or
synthesize it. Use the following contract-bound dimensions instead:

| Requested wording | UI dimension | Design treatment |
| --- | --- | --- |
| source-backed | artifact provenance | show source link/reference, vintage, coverage, and transformations; do not infer that a visual mark is geographically authoritative |
| synthetic | artifact provenance and UI status | identify synthetic content plainly wherever it is shown |
| illustrative | prohibited browser-invented status | it is not an approved UI or artifact token. Do not display or synthesize it; a decorative class would require a server field and a new work item |
| unavailable | UI status | retain context, name the unavailable dependency, and offer reset/retry when supported |
| failure | UI status `request_failed` | show the server-supplied cause, preserve safe context, and offer a recovery action |
| proposal | UI status `hypothetical` plus action lifecycle | distinguish an editable hypothetical proposal from an approved, executed, or evidenced result |

The UI must not map an unknown token to a visual default. A fixture label marks
the origin of this prototype content; it is not a substitute for a rendered
artifact status.

## Visual system

The prototype uses a dark field for spatial context, an off-white reading
surface for provenance, and high-contrast state chips. Shape and plain text,
not hue alone, carry state. The visual hierarchy is:

1. evidence/status strip before the viewport;
2. selected identity and provenance before analytic detail;
3. scenario and proposal inputs before a comparison result; and
4. citations/tool trace before copilot prose that relies on them.

Example fixture content is tinted and watermarked “EXAMPLE FIXTURE.” The
unavailable viewport is intentionally sparse: it contains no substitute
network, county boundary, asset pin, value, or placement.

## Guided-scene contract

Guided scenes are camera and panel presets only. A scene may request a layer,
selection, and copy key, but receives geometry and facts solely from product
data. The four neutral presets are:

- **Orientation:** show the evidence/status strip and layer legend.
- **Selection:** open the inspector after a product-delivered selection.
- **Comparison:** open scenario/proposal controls before any returned result.
- **Explanation:** expand copilot trace and citations for a returned result.

## Acceptance for the implementation handoff

- The viewport, inspector, layer rail, scenario/proposal controls, copilot
  dock, and guided scenes are all represented in the shell.
- The shell reserves a persistent source/status strip supplied by data props;
  it renders only `source_supported`, `source_screened`, `hypothetical`,
  `synthetic`, `unavailable`, or `request_failed`, and does not calculate
  provenance, geography, or effects.
- Each layer and inspector supports source/vintage/coverage/transformation or
  calibration/uncertainty/status disclosures when delivered.
- Unknown, empty, unavailable, malformed, and failure responses remain
  visible and distinguishable; no visual fallback implies missing geometry or
  results.
- A proposal is visibly editable and pending until a returned result names its
  state; no wording implies approval, execution, or benefit.
- Fixture examples are labelled as fixtures. The standalone prototype contains
  no Texas geographic feature, source-backed placement, metric, or effect
  claim.
- Keyboard focus reaches every visible control, state is expressed in text,
  and motion is optional.

## Review decisions still needed

1. Confirm whether Texas is the authorized primary product geography and what
   geography, if any, the first review build may render.
2. Confirm the API/scene payload location for the frozen canonical status and
   artifact-provenance fields so the prototype chips can bind without
   translation.
3. Confirm the authoritative provenance payload fields and which sources may
   be linked in the inspector.
4. Decide which proposal lifecycle states are product-supported. This design
   treats all proposals as pending until that contract exists.
