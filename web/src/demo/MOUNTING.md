# ControlRoom mounting seam

In `web/src/main.tsx`, add this import alongside the existing panel imports:

```ts
import { ControlRoom, type ControlRoomProps } from "./demo";
```

Build `const controlRoomProps: ControlRoomProps` from the selected region's accepted
read-route artifacts, then place `<ControlRoom {...controlRoomProps} />` inside the
existing `<main>` before the chat dock. Pass `cascade` only when the selected scenario
contains source-provided available events. Pass Minnesota topology as displayable only
when the accepted topology/model decision is present; otherwise pass its aggregate or
unavailable status exactly as returned. The module performs no fetches and needs no
changes to the server or root stylesheet.
