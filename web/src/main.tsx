/**
 * The one browser entry (`scripts/build.mjs` builds it to `assets/app.js`).
 *
 * It mounts the shared shell and nothing else: the pages themselves are
 * separate modules loaded on demand, so this entry chunk carries only what
 * every page needs -- the router, the navigation, the truth-label legend, and
 * the shared request-state components.
 */
import { createRoot } from "react-dom/client";

import { SiteShell } from "./shell/SiteShell";
import "./styles.css";

/** Mount only in a browser document; the render tests import the pages directly. */
const mountPoint = typeof document === "undefined" ? null : document.getElementById("root");
if (mountPoint) createRoot(mountPoint).render(<SiteShell />);
