# PrimaryDemo mounting seam

In `web/src/main.tsx`, add this import alongside the existing panel imports:

```ts
import { PrimaryDemo, createPrimaryDemoRuntime } from "./demo";
```

Build `controlRoom` through `createPrimaryDemoRuntime` from selected, accepted read
artifacts, then mount one `<PrimaryDemo>` inside `<main>`. Pass `GridInventoryPanel`
as `spatialStage`, and pass inspector, historical count trajectory, and chat as slots.

Keep physical inventory and the Texas model separate: `spatialStage` has only
source-backed physical geometry; `texasModelScene` has only independently supplied
synthetic ACTIVSg2000 model IDs/coordinates. Supply cascade events only after an HTTP
readback has `playback_qualified` and the event IDs are verified against the synthetic
model scene. The module performs no fetches itself and does not need server or root
stylesheet edits.
