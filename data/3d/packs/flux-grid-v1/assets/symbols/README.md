# Flux category symbols

18 neutral white category pictograms keyed by the exact asset-archetype contract IDs. Transparent PNG atlases contain no status color or label.

- MapLibre sprite base: `symbols/flux-grid` (192×96 at 1x; 384×192 at 2x).
- Deck atlas: `symbols/flux-grid@2x.png`; use `deck-icon-mapping.json` with the loaded mapping object. Each 64px cell is centered at anchor `(32,32)`, `mask: true`.
- `svg/` contains every separate 24-unit SVG. `catalog.json` records semantics and provenance; `validation.json` records cell, alpha, and uniqueness checks.
- Source icons from Lucide React 0.545.0 use ISC / Feather MIT; see `LICENSE-LUCIDE.txt`. Original category geometry and battery polarity additions use CC0-1.0; see `LICENSE-ORIGINAL.txt`.
- Category glyphs must remain neutral in the runtime. Any operating or provenance status requires a separate readable label and marker. Battery polarity denotes chemistry/identity, never measured charge.

The downloadable pack includes the labeled proof sheet at `renders/flux_symbol_proof.png` and its SVG counterpart. It shows 32px and 24px symbols on dark graphite at actual display size. PNG atlases and rendered proof images stay in that pack, not this source-only Git directory; install them with the verified build-copy command in the pack README.
