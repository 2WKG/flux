import { useCallback, useEffect, useState } from "react";

import { routeForPath, type Route } from "./index";

/**
 * The current route, plus the one way to change it.
 *
 * `navigate` changes the page path while retaining the current public search
 * and hash state. That keeps a bookmarkable demo state intact while the shell
 * moves between pages. `popstate` covers the back and forward buttons; a deep
 * link is served by `web/server.mjs`, which answers every path with the shell,
 * so the first render already reads the real path.
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
    const destination = `${path}${location.search}${location.hash}`;
    const current = `${location.pathname}${location.search}${location.hash}`;
    if (destination === current) return;
    history.pushState(null, "", destination);
    setPathname(path);
  }, []);

  return [routeForPath(pathname), navigate] as const;
}
