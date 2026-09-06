/**
 * The demo's route table and the smallest history router that can serve it.
 *
 * Why no router dependency: the site is two pages with no nested layouts, no
 * route parameters, and no data loaders. `react-router` (or `wouter`, or Vite
 * multi-page entries) would each add a dependency or a second HTML shell for
 * behaviour that is two `history.pushState` calls and one `popstate` listener.
 * The strict CSP in `web/index.html` also rules out anything that evaluates a
 * route string at runtime. So the table is data, the matcher is a pure
 * function, and the only browser API touched is `history`.
 *
 * Page weight is handled separately, by `src/shell/SiteShell.tsx`: each entry
 * here names a page module that is loaded as its own esbuild chunk, so a
 * visitor downloads one page's code, not both.
 */
import type { AssetStatus } from "../labels";

export interface Route {
  readonly id: RouteId;
  /** The path this page is served at. `web/server.mjs` answers it with the SPA shell. */
  readonly path: string;
  /** The nav's link text. */
  readonly label: string;
  /** The document title the page sets when it becomes current. */
  readonly title: string;
  /**
   * The truth-label tokens this page's data can actually assert. The shared
   * legend renders exactly these, so a page never displays a claim -- least of
   * all a source-supported one -- that its own data does not carry.
   */
  readonly truthLabels: readonly AssetStatus[];
  /** One line naming what those labels apply to on this page. */
  readonly truthNote: string;
}

export type RouteId = "main" | "explainer" | "minnesota";

export const ROUTES: readonly Route[] = [
  {
    id: "main",
    path: "/",
    label: "Scenario explorer",
    title: "Flux | Resilience desk",
    truthLabels: ["synthetic"],
    truthNote: "This page renders the backend-served static synthetic ACTIVSg2000 network artifact; it is not a numerical solve or a physical-grid claim.",
  },
  {
    id: "explainer",
    path: "/explainer",
    label: "How the math works",
    title: "Flux | How the math works",
    truthLabels: ["synthetic", "hypothetical", "unavailable"],
    truthNote:
      "This page replays a synthetic five-bus teaching cascade solved on the server by twin/toy_cascade.py, alongside synthetic teaching schematics, one hypothetical recorded experiment, and explicit unavailable states.",
  },
  {
    id: "minnesota",
    path: "/minnesota",
    label: "Minnesota aggregate",
    title: "Flux | Minnesota aggregate baseline",
    truthLabels: ["unavailable"],
    truthNote: "This shell names the accepted aggregate baseline and every server contract that is still unavailable.",
  },
];

export const DEFAULT_ROUTE: Route = ROUTES[0];

/**
 * The route a pathname serves. A trailing slash is the same page, and an
 * unmatched path falls back to the default route -- which is what the static
 * origin already does with the shell it serves for every path.
 */
export function routeForPath(pathname: string): Route {
  const normalized = pathname.replace(/\/+$/, "") || "/";
  return ROUTES.find((route) => route.path === normalized) ?? DEFAULT_ROUTE;
}
