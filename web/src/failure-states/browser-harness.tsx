import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";

/** Mounts a supplied fixture tree for browser verification; it makes no request. */
export function mountFailureStateHarness(target: Element, tree: ReactNode) {
  createRoot(target).render(tree);
}
