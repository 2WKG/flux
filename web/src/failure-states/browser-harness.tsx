import { createRoot } from "react-dom/client";
import { FailureState } from "./FailureState";
import type { FailureStateProps } from "./types";

/** Mounts supplied fixture states for browser verification; it makes no request. */
export function mountFailureStateHarness(target: Element, props: FailureStateProps) {
  createRoot(target).render(<FailureState {...props} />);
}
