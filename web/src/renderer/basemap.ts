import type { StyleSpecification } from "maplibre-gl";

/**
 * The basemap for the checked-in synthetic demo.
 *
 * It has no `sources`, no `glyphs`, no `sprite`, and no layer that references
 * any of those, so MapLibre resolves the whole style without issuing a single
 * network request. That is the point: the static demo discloses itself as
 * "no API required" and "Not a Minnesota or Texas topology", and a remote
 * vector basemap contradicted both -- it painted real Minnesota geography at
 * z5 from a third-party CDN under a heading that promised none.
 *
 * `index.html` backs this with `connect-src 'self'`, so a style URL
 * reintroduced by accident is blocked by the browser rather than silently
 * fetched.
 */
export const OFFLINE_BASEMAP_STYLE: StyleSpecification = {
  version: 8,
  name: "Flux offline geometry-free basemap",
  sources: {},
  layers: [
    { id: "background", type: "background", paint: { "background-color": "#071221" } },
  ],
};
