import { Suspense, lazy, useEffect, type ComponentType } from "react";

import { FailureState } from "../failure-states/FailureState";
import type { RouteId } from "../router";
import { useRoute } from "../router/useRoute";
import { SiteNav } from "./SiteNav";
import { TruthLegend } from "./TruthLegend";

/**
 * Each page is a dynamic import, which esbuild's code splitting emits as its
 * own chunk (`scripts/build.mjs`). The entry chunk holds this shell and the
 * shared pieces only, so the explainer never downloads the scenario page's
 * fixture and scene code, and the scenario page never downloads the explainer's
 * teaching bundle. That split is the reason the pages are separate modules; the
 * routing above it is only how a visitor gets between them.
 */
const PAGES: Record<RouteId, ComponentType> = {
  main: lazy(() => import("../pages/MainPage").then((module) => ({ default: module.App }))),
  explainer: lazy(() => import("../pages/ExplainerPage").then((module) => ({ default: module.ExplainerPage }))),
};

/** The one mounted root: shared navigation, the routed page, the shared legend. */
export function SiteShell() {
  const [route, navigate] = useRoute();
  const Page = PAGES[route.id];

  useEffect(() => {
    document.title = route.title;
  }, [route.title]);

  return (
    <>
      <SiteNav current={route} onNavigate={navigate} />
      <Suspense
        fallback={
          <div className="page-pending">
            <FailureState state={{ kind: "loading", message: `Loading ${route.label}.` }} />
          </div>
        }
      >
        <Page />
      </Suspense>
      <TruthLegend statuses={route.truthLabels} note={route.truthNote} />
    </>
  );
}
