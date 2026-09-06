import { createRoot } from "react-dom/client";
import { RunTraceHarness } from "./RunTrace";
import type { RunEvent, RunIdentity, SourceStatus } from "./types";

/**
 * A browser-only mount point for a recorded parser trace. It is intentionally
 * data-driven: callers must pass observed SSE events and may not label them as
 * a live provider trace. It gives reviewers a real DOM surface for ordered,
 * stale, cancel, and error paths without coupling the component to transport.
 */
export function mountRunTraceHarness(target: Element, input: { identity: RunIdentity; sourceStatus: SourceStatus; events: readonly RunEvent[]; onCancel?: (identity: RunIdentity) => void }) {
  createRoot(target).render(<RunTraceHarness {...input} />);
}
