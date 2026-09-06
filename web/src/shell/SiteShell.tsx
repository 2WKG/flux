import { Component, Suspense, lazy, useEffect, type ComponentType, type ReactNode } from "react";

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
export type PageLoader = () => Promise<{ readonly default: ComponentType }>;

/**
 * The route-id -> page-module binding, exported so it can be resolved and
 * rendered by a test. `test/routing.test.mjs` awaits each loader and asserts
 * the page it returns is the one the route names, which is the only thing that
 * distinguishes a route that reaches its page from a route that reaches
 * another page's component and still typechecks.
 */
export const PAGE_LOADERS: Record<RouteId, PageLoader> = {
  main: () => import("../pages/MainPage").then((module) => ({ default: module.App })),
  explainer: () => import("../pages/ExplainerPage").then((module) => ({ default: module.ExplainerPage })),
  minnesota: () => import("../minnesota/MinnesotaControlRoom").then((module) => ({ default: module.MinnesotaControlRoom })),
};

const PAGES: Record<RouteId, ComponentType> = {
  main: lazy(PAGE_LOADERS.main),
  explainer: lazy(PAGE_LOADERS.explainer),
  minnesota: lazy(PAGE_LOADERS.minnesota),
};

/** Keep failed lazy page imports inside the shared shell and recovery surface. */
class RouteFailureBoundary extends Component<
  { readonly routeId: RouteId; readonly children: ReactNode },
  { readonly failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidUpdate(previous: Readonly<{ routeId: RouteId }>) {
    if (previous.routeId !== this.props.routeId && this.state.failed) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="page-pending">
          <FailureState
            state={{ kind: "failed", message: "This page could not be loaded. The rest of the site is still available." }}
            onRetry={() => location.reload()}
          />
        </div>
      );
    }
    return this.props.children;
  }
}

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
      <RouteFailureBoundary routeId={route.id}>
        <Suspense
          fallback={
            <div className="page-pending">
              <FailureState state={{ kind: "loading", message: `Loading ${route.label}.` }} />
            </div>
          }
        >
          <Page />
        </Suspense>
      </RouteFailureBoundary>
      <TruthLegend statuses={route.truthLabels} note={route.truthNote} />
    </>
  );
}
