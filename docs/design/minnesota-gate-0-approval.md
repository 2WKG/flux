# Gate 0 — Minnesota scope, contracts, and truth labels

**Gate:** 2WKG-354. **Inputs:** 2WKG-363 (narrative and IA), 2WKG-364 (accepted
artifact inventory), 2WKG-365 (3D visual and model-production contract).

This record freezes what later Minnesota work may rely on. It approves a
**boundary**, not a demo: it does not accept new data, produce geometry, or
assert that a renderable Minnesota scene exists.

| Input | Artifact on `master` |
| --- | --- |
| 2WKG-363 | [`minnesota-demo-narrative-ia.md`](minnesota-demo-narrative-ia.md) |
| 2WKG-364 | [`data/sources/minnesota-accepted-artifact-inventory.json`](../../data/sources/minnesota-accepted-artifact-inventory.json) |
| 2WKG-365 | [`3d-asset-contract.md`](3d-asset-contract.md), [`data/3d/asset-archetypes-v1.json`](../../data/3d/asset-archetypes-v1.json) |

`tests/test_minnesota_gate0_approval.py` enforces every frozen claim below, so a
later change that breaks one fails a test instead of quietly widening the gate.

## 1. The five-bus preview is not Minnesota

Recorded in the inventory under `not_accepted_as_current_product_coverage` as
`synthetic_power_balance_preview` (`data/demo/bundle.json`), default truth label
**`synthetic`**, with the rule: *"May be shown only as an abstract offline
preview. It is not Minnesota, Texas, ERCOT, MISO, or an actual interconnection
model."*

It may never be relabelled, positioned, or narrated as Minnesota infrastructure,
and it is not a fallback for a Minnesota topology scene.

## 2. Accepted Minnesota coverage, in full

Four artifacts are accepted, all **aggregate-mode metadata**:

| Artifact | Label | What it may support |
| --- | --- | --- |
| `mn:aggregate:manifest:v1` | source_backed | provenance/coverage display, aggregate-mode gating |
| `mn:facility_capacity:county:2024` | source_backed | county capacity context |
| `mn:facility_context:unassigned:2024` | source_backed | unassigned-plant context |
| `mn:ba_context:miso:2024-h1` | source_backed | MISO BA context (**not** Minnesota demand) |

**What is therefore not accepted:** no geometry, no topology, no facility points,
no allocation. The inventory records raw geometry, GridSFM feasibility, and any
Minnesota network as `unavailable`. Consequently:

- **Topology scenes stay disabled** until the `10-minnesota-demo.md` network
  decision gate accepts a solver-complete source. Aggregate mode is the default
  and only mode.
- A missing county is **neither zero nor an asset**.
- MISO BA values are **never allocated** to Minnesota counties or service areas.

## 3. Truth labels — two layers, frozen

The inputs use two vocabularies at two layers. They are complementary, not
competing, and Gate 0 freezes both.

**Artifact-level** — what a piece of evidence *is* (inventory policy):

`source_backed` · `synthetic` · `unavailable`

**UI status** — what the browser *renders about a result*, each bound to a real
server field (narrative-IA status table):

`source_supported` · `source_screened` · `hypothetical` · `synthetic` ·
`unavailable` · `request_failed`

The 3D contract's `MAT_STATUS` slot binds exactly the UI set.

### `illustrative` is not approved

The Gate 0 issue text and the inventory's `truth_labels` list both mention
`illustrative`. It is **not** part of the frozen set, for reasons already
recorded in the inputs:

- **No artifact carries it.** Every entry in the inventory resolves to
  `source_backed`, `synthetic`, or `unavailable`; `illustrative` is declared in
  the vocabulary list but never assigned.
- **No server field asserts it.** The narrative-IA removed it deliberately: a
  label the browser invents would breach the `00-overview.md` browser/server
  boundary.

It survives in the inventory only inside a prohibition — *"Synthetic and
illustrative points must never imply a Minnesota facility"* — which this record
keeps. If a decorative class is ever needed it must arrive with its own server
field and its own work item first. **This record supersedes the label list in the
2WKG-354 issue description.**

## 4. Browser/server boundary

Per `docs/specs/00-overview.md`: the browser renders server artifacts and
results. It never reads DuckDB, computes a result, or invents a label. Every
status shown must trace to a server field; where a required artifact is absent,
the scene renders the **unavailable** fact rather than a number.

## 5. Integrity of evidence identity

From the inventory's integrity policy, and consistent with the repository-wide
`.gitattributes`:

- **Committed text evidence** is digested as SHA-256 over UTF-8 content with CRLF
  normalised to LF, so a Windows checkout cannot change an evidence identity.
- **`upstream_sha256_unverified_offline`** values are recorded author-download
  claims. The upstream files are not committed and their bytes are not
  re-verified here; they must not be promoted to verified raw data.

## What later tasks may now rely on

- The accepted artifact list, their labels, and their prohibited uses are stable
  inputs (2WKG-367 adapter, 2WKG-373 layer controls, 2WKG-394 inspector).
- The two label vocabularies are fixed; a component binds one of them and never
  invents a third (2WKG-373, 2WKG-405).
- The 3D archetype catalog and its import invariants are stable (2WKG-374
  placement, 2WKG-376–393 modelling).
- Aggregate mode is the default; **no task may assume topology, geometry, or
  facility coordinates exist.** 2WKG-367 additionally remains blocked on
  2WKG-99 and 2WKG-102, which are not complete.

## What this gate does not approve

New sources, geometry, a Minnesota network, an allocation basis, a rendered map,
or any of the eighteen 3D models. None exist in this repository. Gate 0 approves
the boundary within which that work may proceed.

## Verification

```
python -m pytest tests/test_minnesota_gate0_approval.py -q
```
