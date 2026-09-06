# Flux UI style guide

Design proposal · 6 September 2026 · Power-grid exploration

Flux should feel like a clear, welcoming workspace surrounding a luminous infrastructure model. Start with a light, opaque interface and a dark 3D scene. At facility scale, reveal translucent surfaces, readable internal forms, and a precise glowing silhouette. Keep navigation, language, and decisions calm and familiar.

> **Scope.** This guide is Flux's current visual and interaction direction. It does not alter the API, data, geography, scenario, or provenance contracts, which are governed by the [shared overview](../specs/00-overview.md) and its superseding specifications. The evidence discussion below uses existing status and truth vocabularies as display guidance; it introduces no values or mappings.

The defining experience is **Explore → Try a change → Compare**. A person should understand where they are, what they selected, and what they can do next without learning a specialist console. This guide proposes a visual and interaction contract; any companion visual preview is styling only, not a working power-system simulation.

## Reference interpretation

The Air Force reference is **Aircade and its interactive experiences**. Its spatial interfaces vary between dark and pale stages. The strongest common patterns are one dominant object, spare navigation, guided entry points, and detail revealed through interaction.

| Observed reference | Useful translation for Flux |
|---|---|
| [Aircade hub](https://airforceaircade.com/) — midnight/navy stage, offset game artwork, fine contours and particles, hollow/solid display lettering, small pale-gold accents, short mission summary | Make the scene the visual center; give it a short explanation and a clear entry action. Reduce display lettering and particles inside the working app. |
| [Command the Stack](https://commandthestack.com/) — three translucent spatial discs with icy rim light, charcoal backdrop, grounded pedestal, sparse navigation | Use layered translucent volume and precise edge light to make spatial relationships inviting to inspect. |
| [Air Base](https://airforceaircade.com/air-base/play) — detailed aircraft on a pale contour-map stage, a few concentric hotspot controls, a visible animation pause control | Offer a few meaningful inspection points and easy motion control. A clicked hotspot revealed an opaque callout connected by a thin cyan dotted leader. |
| [E.C.H.O. overview](https://airforceaircade.com/echo) describes three guided cognitive games; its [title screen](https://airforceaircade.com/echo/play) uses a pale background, fine flowing lines, and accessibility/caption controls | Teach one interaction at a time and keep help available. The title screen was inspected; signed-in gameplay was not tested. |

Borrow these relationships rather than their aircraft, logos, literal ring controls, or game vocabulary. Air Base's aircraft is opaque; Flux's translucent infrastructure is a design extension. The pale shell and dark close-up scene combine the references into a workspace suited to sustained reading.

In Palantir's linked track example, a subdued grayscale basemap supports thin translucent colored paths, brighter position dots, and crisp outlined direction markers. The documentation distinguishes track lines, recorded-position breadcrumbs, and the current-position icon; it also documents interpolation and breaks across excessive time gaps. Flux can borrow the hierarchy of quiet context and clearly distinguished evidence. Electrical connections must retain their own grid meaning; vessel-track marks are not a template for inventing power flow. [Palantir: track displays](https://www.palantir.com/docs/foundry/map/visualize-tracks)

Palantir also documents map selection, zoom-dependent display styling, and timeline interactions. These support linked inspection, progressive detail, and a single time context in Flux. The luminous, transparent 3D building treatment below is an original Flux recommendation, not a claim about the linked Palantir example. [Selection](https://www.palantir.com/docs/foundry/map/selection), [display styling](https://www.palantir.com/docs/foundry/map/visualize-objects), [timeline](https://www.palantir.com/docs/foundry/map/timeline)

## Composition and simplicity

On a typical desktop, reserve roughly 70% of the workspace for the scene when inspection is open. Use a compact header, search, a small group of named scene tools, and one 320–360px inspector. Let the scene expand when the inspector closes. At laptop widths, collapse secondary controls into labeled menus. On small screens, use a bottom sheet or list-first view with a deliberate way to return to the scene.

The header contains Flux, the current dataset or region, and workspace actions. A breadcrumb such as “Region / Corridor / Substation” identifies scale. Keep “Reset view” visible. Search supports facilities and places, with source coverage stated in results. Avoid persistent left and right panels competing with a chat column.

The inspector starts with the object's name and type, then its plain-language status, a small set of relevant facts, and one primary action. Put connections, source details, and technical fields below. “Ask about this” opens help with the selection already attached; show that context as an editable chip. Present an answer and its sources before optional tool details.

Do not require drag gestures to complete a task. Selecting a proposal location should also be possible from search or a list. Preserve the user's camera and filters when opening help, changing inspector tabs, or encountering an error. Use overlays sparingly and keep essential text on solid surfaces.

## Visual tokens

These are proposed Flux colors, not measured Palantir or Air Force brand values. The companion [`ui-tokens.css`](ui-tokens.css) scopes tokens under `data-flux-theme="light"` or `"dark"`; it imports no fonts and applies no global reset. The scene palette remains dark in both shell themes.

**The app has one token vocabulary, and it is not this file.** `web/src/styles.css` `:root` owns the tokens the application actually renders — `--ink`, `--muted`, `--dim`, `--line`, `--line-strong`, `--line-soft`, `--panel`, `--panel-solid`, `--panel-raised`, `--panel-sunken`, `--accent`, `--low`, `--mid`, `--high`, `--relief`, `--amber`, `--red`, `--green`, `--font-sans`, `--font-mono` — after #252 collapsed the rival panel colours, borders and inks onto that single sheet. `ui-tokens.css` is a design reference: every name in it is `--flux-`-prefixed so it can never shadow one of those, it is imported by nothing under `web/`, and it ships no runtime value. When this direction lands in the product it lands by changing the values behind `web/src/styles.css` `:root`, never by adding a second set of names beside them. `web/src/status-vocabulary.test.mjs` fails if `ui-tokens.css` grows an unprefixed token, is imported by browser code, or drifts from the prototype's font stacks.

| Role | Light shell | Dark shell / scene |
|---|---|---|
| Workspace / scene ground | Chalk `#F4F7F8` | Midnight `#0B141E` |
| Opaque panel | White `#FFFFFF` | Slate `#17232E` |
| Primary text | Ink `#182B37` | Pale ink `#EAF2F5` |
| Secondary text | `#536778` | `#A9B9C6` |
| Decorative divider | `#D5DFE5` | `#354858` |
| Primary action | `#2563EB`, white text | `#A5C4FF`, dark ink text |
| Selected 3D object | — | Cyan `#73D9EB` |
| Positive / caution / critical scene cue | — | `#80CBA6` / `#EABD71` / `#F08C8C` |

Keep action, selection, and operational status as independent channels. A selected facility gets a cyan contour; its amber warning remains an amber badge and symbol. A proposal gets a dashed footprint plus the word “Proposal.” Selection must never make a warning disappear. Pale scene colors are not suitable as small text on white; the CSS provides darker status inks for the light shell.

Use the platform’s own fonts: `ui-sans-serif, system-ui, sans-serif` for the interface and `ui-monospace, monospace` for data, exactly as [`texas-workspace-prototype.html`](texas-workspace-prototype.html) already ships them. [`ui-tokens.css`](ui-tokens.css) adds older-browser fallbacks after those first entries and changes no leading family. Name no downloadable family first — a face that is installed on one machine and missing on another makes metrics machine-dependent, and Flux loads zero third-party font requests. The `fonts.googleapis.com` import that `web/src/styles.css` still carries on `master` (Manrope, DM Mono) is superseded by this stack; its removal belongs to #252, which owns that file. Default controls to 14px/20px, body copy to 16px/24px, and panel headings to 24px/30px. Use 12px captions only for secondary information. Use tabular numerals for comparisons and reserve monospace for identifiers. Prefer sentence case and medium weights.

Use a 4, 8, 12, 16, 24, 32px spacing scale; 10px control corners; 14px panel corners; and 44px interactive targets. An inspector generally needs 24px padding and 16px between related sections. Use restrained shadows and separators. Decorative separators may be subtle; boundaries required to identify controls need stronger dedicated tokens.

## Close-range 3D materials

Build each detailed asset from a readable core, a translucent shell, and clean structural edges. A substation should remain recognizable when its glow is disabled. Favor simplified engineering forms over dense wireframes: transformer blocks, a few bus structures, and a coherent yard boundary. Towers need legible silhouettes; line spans need consistent attachment points.

| Material component | Starting values | Purpose |
|---|---|---|
| Shell faces, idle | Opacity 0.10–0.22; default 0.16 | Reveal form without obscuring the core |
| Shell faces, focused | Opacity 0.22–0.32; default 0.28 | Make the selected volume readable |
| Core | Opacity 0.85–1.0; default 0.90 | Preserve mass, depth, and identity |
| Structural edges | Opacity 0.65–0.95 | Establish a clear silhouette |
| Selected halo | Approx. 6–12px screen-space spread, low alpha; default 8px / 0.14 | Gently separate the selected asset |
| Surrounding assets | Neutral edges, minimal emission | Retain nearby context |

These values are tuning starting points. A halo's screen-space appearance depends on resolution, tone mapping, and the renderer; the CSS radius is not a universal bloom parameter. Apply bloom selectively to scene geometry. UI, labels, text, and status badges should stay crisp. Avoid whole-screen haze, glowing ground grids, lens flare, and continuous pulses.

Use shallow highlights to reveal shape, with stronger edges facing the viewer. Keep essential inner geometry opaque enough to read. Render opaque cores first, then manage translucent surfaces using appropriate sorting or transparency techniques for the renderer. Test overlapping shells, camera orbits, terrain intersections, and near-plane clipping. Transparency must not accidentally expose every distant object through every building.

A focus action can provide a labeled cutaway or isolated asset view. Otherwise respect normal depth and occlusion. If a selected asset is hidden, provide an indicator and “Bring into view”; do not silently turn the scene into an X-ray. Material opacity expresses visual hierarchy, never source confidence or numerical uncertainty.

Asset archetypes should include substation, tower, hospital, military base, water plant, and proposed SMR. Give each a distinct silhouette and a text label. Use generic facility forms when geometry is synthetic rather than source-supported. Avoid borrowed logos, aircraft replicas, weapon imagery, and tactical jargon. A military base remains a critical facility within the grid story.

## Detail across scale

Gate detail by screen size and legibility, not a single hard-coded camera height. Add hysteresis or a short crossfade so objects do not flicker at thresholds.

| View | Show | Hide or simplify |
|---|---|---|
| Region | Accepted boundaries, a few major corridors, grouped facilities, coverage label | Individual towers, interiors, most labels, bloom |
| Corridor | Selected connection, connected facilities, a few key labels | Unrelated small assets and dense line furniture |
| Facility | Detailed silhouette, translucent shell, useful internal forms, inspector | Distant detail, overlapping labels, decorative particles |

Keep labels upright in screen space with opaque dark backplates. Prioritize selected objects, then their immediate connections. Resolve collisions instead of shrinking all labels. Increase hit targets independently of the rendered line width. Preserve the selected object while changing scale.

Flow arrows or particles require a supported, named metric and time context. An animated line must not imply live telemetry. Do not connect across missing geometry or time coverage. In aggregate coverage mode, show documented areas or zones rather than inferred towers, transmission paths, loading, or flows.

## Scenario states and language

Keep the baseline available throughout the workflow. A change first creates a proposal; only a matching server result changes the comparison. “Solved” means the computation completed, not that every outcome improved. Show units, baseline, proposed value, and direction of change together.

| State | Visual behavior | Friendly copy / next action |
|---|---|---|
| Baseline | Neutral scene; clear baseline label | “Explore this network.” |
| Proposal | Dashed footprint and labeled proposal chip | “Ready to try this change.” / “Run comparison” |
| Solving | Keep baseline visible; bounded progress region | “Comparing your change with the baseline…” |
| Success | Display matching returned results; mark improvements and regressions individually | “Comparison ready.” / “See what changed” |
| Failed | Preserve inputs and previous valid view; explicit failure message | “We couldn't finish this comparison.” / “Try again” |
| Stale | Retain old results with an unmistakable stale label | “These results are from your previous setup.” / “Run again” |

This is the run lifecycle, not the status axis, and the two are not interchangeable. The **Failed** row renders the IA’s `request_failed` status with its required display copy (“Request failed”) and its accompanying detail; the friendly sentence here is supporting copy beside that label, never the label itself and never a bare sentence on its own.

Do not replace numerical values with guessed progress or animate invented intermediate results. Use a spinner only where work is pending, with an accessible text status; do not claim a percentage unless supplied meaningfully. If a run is canceled or returns out of order, keep the current selection and scenario version intact.

Prefer “Try a change,” “Show connections,” “Back to region,” and “What changed?” Make error messages state what happened, what remains available, and the next action. “Coverage is not available here yet. Explore available areas” is more useful than an empty canvas. Explain “small modular reactor” before using “SMR” with unfamiliar users.

## Evidence and truthful presentation

Keep provenance separate from operational status. Use the existing two axes, not a new unified badge vocabulary: browser-result status uses the six `AssetStatus` values in [`web/src/labels.ts`](../../web/src/labels.ts), while artifact truth remains `source_backed`, `synthetic`, or `unavailable` as defined by the [shared overview’s truth-vocabulary section](../specs/00-overview.md#43-truth-vocabularies--two-axes-not-one-d-7). Do not mechanically map `source_backed` to `source_supported`. A design preview is a preview, not a status: describe it as one, and never invent a status word for it. Use the [narrative IA’s existing display copy](minnesota-demo-narrative-ia.md) for any implemented label, and explain its meaning on demand; a green badge must not imply a source was independently verified.

Geometry, identity, placement, and scenario values can have different provenance. A sourced facility location may use a synthetic building model. The inspector should disclose that distinction and provide source title, source date when known, and coverage limits. Show “Live” only when a source supports that claim and freshness is visible.

When the abstract five-bus fixture is used, present it as an offline example, not Texas, Minnesota, ERCOT, MISO, or a real interconnection. Never place it over a real basemap as if it were accepted regional topology. A style preview should prominently state “Synthetic · No live grid data.” — “Synthetic” is the IA’s own display copy for the `synthetic` token (`web/src/source-truth.ts` `STATUS_COPY`, the [narrative IA](minnesota-demo-narrative-ia.md) “Synthetic” row), so the preview names an approved state instead of inventing one. The browser presents server geometry and solved results; it does not generate simulation values, scores, or invented network connections.

The decorative status word that [`3d-asset-contract.md`](3d-asset-contract.md) refuses (“There is deliberately no decorative … state”), that [`texas-demo-narrative-ia.md`](texas-demo-narrative-ia.md) marks prohibited, and that [`minnesota-gate-0-approval.md`](minnesota-gate-0-approval.md) records as not approved must never appear in this guide or in any design document that is not one of those contracts — not as a label, not beside one, and not as prose. `web/src/status-vocabulary.test.mjs` scans `docs/design/**` and fails if it comes back.

## Accessibility, motion, and rendering

Target at least 4.5:1 contrast for ordinary text and 3:1 for large text. Required control boundaries and meaningful graphics need 3:1 against adjacent colors; keep focus clearly visible. Check composited scenes as well as swatches, and pair color with text, shapes, patterns, or icons. [W3C text contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), [non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)

Token checks found 13.55:1 for ink `#182B37` on the light chalk ground `#F4F7F8`, 5.45:1 for secondary `#536778` on that same ground, 14.07:1 for pale ink `#EAF2F5` on the dark slate panel `#17232E` (16.34:1 on the darker midnight scene ground `#0B141E`), and 5.17:1 for white on the blue action `#2563EB`. Control borders exceed 3:1 on their intended surfaces. These checks verify color pairs, not complete interface accessibility. Cyan on chalk is only 1.52:1; keep it out of light-shell text.

Offer a keyboard-operable facility list synchronized with scene selection and an accessible scene synopsis. Essential details must not depend on hover or orbiting a model. Maintain visible focus, predictable tab order, explicit button names, and screen-reader announcements for new results. Announce changes, not every rendered frame.

Use roughly 160ms control feedback, 220ms panel transitions, and 480ms camera focus as starting timings. Stop camera motion when the user intervenes. Honor reduced motion by removing camera travel, animated flows, and ornamental loops while retaining all information. The renderer must consume the motion preference; CSS variables alone cannot stop WebGL animation.

Aim for 60fps on the chosen demo hardware, with a stable 30fps fallback; these are design targets, not measured guarantees. Adapt glow, detail, shadows, and render resolution before compromising input response. Use instancing, culling, and level of detail appropriate to the scene. On WebGL failure, preserve selection and provide a useful list or 2D view with “Reload 3D.”

## Implementation and acceptance

1. Build the opaque shell, tokens, typography, inspector, selection, and keyboard list using an explicitly labeled fixture.
2. Tune one substation and one corridor through region, corridor, and facility views; validate silhouettes with glow off.
3. Add source labels and baseline/proposal states, then connect versioned server results and recovery states.
4. Expand the asset catalog, tune performance on actual hardware, and verify accessibility across both shell themes.

Accept the direction when a first-time viewer can identify their location, selected object, source basis, and next action without explanation; selected geometry remains legible over overlapping assets; the facility view feels translucent and luminous; labels stay crisp; and a failed or stale comparison is impossible to mistake for a current result. Test at desktop and laptop widths, reduced motion, keyboard-only navigation, low rendering quality, and unavailable coverage.

Reference review date: 6 September 2026. Flux constraints follow the [shared overview](../specs/00-overview.md) and [Minnesota narrative IA](minnesota-demo-narrative-ia.md); source research began from saved Minnesota and Texas UI roadmaps, with the explicit abstract-fixture boundary used here. Visual palette, material values, component dimensions, motion timings, and performance targets are original design recommendations and require implementation review.
