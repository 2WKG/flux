# Flux design guidance

## Frozen contracts

These records are binding. Change them only through the process each one names;
the guidance below defers to them.

- [3D asset contract](3d-asset-contract.md) — the frozen archetype/material/status
  set for scene assets, enforced by `scripts/validate_asset_archetypes.py`.
- [Minnesota Gate 0 approval](minnesota-gate-0-approval.md) — the approved
  Minnesota vocabulary and the record of what was refused.
- [Minnesota demo narrative IA](minnesota-demo-narrative-ia.md) — the demo's
  information architecture and the display copy for every status.
- [Texas demo narrative IA](texas-demo-narrative-ia.md) — the Texas workspace
  information architecture and its status/provenance dimensions.

## Direction and reference

- [UI style guide](ui-style-guide.md) — Flux's current visual and interaction direction.
- [UI tokens](ui-tokens.css) — companion CSS custom-property reference; it is not imported by the application.
- [Texas workspace prototype](texas-workspace-prototype.html) — the shipped static
  prototype, with `texas-workspace-prototype-desktop.png` and
  `texas-workspace-prototype-mobile.png` as its captured views.

These design documents do not define API, data, geography, scenario, or provenance contracts. Follow the authority lattice in [the shared overview](../specs/00-overview.md) and its superseding specifications.
