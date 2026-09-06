import { useCallback, useEffect, useState } from "react";

import { routeForPath, type Route } from "./index";

/**
 * The current route, plus the one way to change it.
 *
 * `navigate` only ever replaces the *path*: a page's own URL state (search and
 * hash) belongs to that page, so it is left alone within a page and dropped
 * when the visitor moves to a different one. `popstate` covers the back and
 * forward buttons; a deep link is served by `web/server.mjs`, which answers
 * every path with the shell, so the first render already reads the real path.
 */
export function useRoute(): readonly [Route, (path: string) => void] {
  const [pathname, setPathname] = useState(() =>
    typeof location === "undefined" ? "/" : location.pathname,
  );

  useEffect(() => {
    const onPopState = () => setPathname(location.pathname);
    addEventListener("popstate", onPopState);
    return () => removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((path: string) => {
    if (path === location.pathname) return;
    history.pushState(null, "", path);
    setPathname(path);
  }, []);

  return [routeForPath(pathname), navigate] as const;
}
