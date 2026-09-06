# Synthetic Texas model scene handoff

Import `SyntheticModelScene` into the primary Texas model visual only. Pass the exact `data.elements` from `/demo/model`, the selected model element ID, any qualified cascade stage IDs as `highlightedElementIds`, and the primary scene's selected-component callback as `onSelectElement`.

The component accepts only resolved canonical model geometry, marks its topology as synthetic ACTIVSg2000, and has no physical-inventory binding. It renders generic columns for generator/load roles because `/demo/model` supplies no fuel or measured capacity. If geometry or WebGL is unavailable, pass the existing 2D model visual through `fallback`.
