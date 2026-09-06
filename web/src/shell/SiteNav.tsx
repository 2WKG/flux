import type { MouseEvent } from "react";

import { ROUTES, type Route } from "../router";

/**
 * A modifier click, a middle click, or a right click is the browser's to
 * handle: the link carries a real `href`, so those keep working (new tab,
 * copy link) and only a plain left click is taken over by the router.
 */
function isPlainClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

/** The navigation shared by every page. It is rendered once, by the shell. */
export function SiteNav({ current, onNavigate }: { current: Route; onNavigate: (path: string) => void }) {
  return (
    <nav className="site-nav" aria-label="Pages">
      <span className="brand"><b>FLUX</b><span>Grid resilience demo</span></span>
      <ul className="site-links">
        {ROUTES.map((route) => {
          const isCurrent = route.id === current.id;
          return (
            <li key={route.id}>
              <a
                className={isCurrent ? "site-link current" : "site-link"}
                href={route.path}
                aria-current={isCurrent ? "page" : undefined}
                onClick={(event) => {
                  if (!isPlainClick(event)) return;
                  event.preventDefault();
                  onNavigate(route.path);
                }}
              >
                {route.label}
              </a>
            </li>
          );
        })}
        <li>
          <a className="site-link" href="/asset-lab/">Asset lab</a>
        </li>
      </ul>
    </nav>
  );
}
