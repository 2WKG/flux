import { useEffect, useRef } from "react";
import { MapboxOverlay } from "@deck.gl/mapbox";
import type { LayersList } from "@deck.gl/core";
import { useControl } from "react-map-gl/maplibre";

/**
 * A deck canvas over MapLibre's WebGL canvas.
 *
 * MapLibre renders the base map independently in this mode.  The interleaved
 * control path requires a Mapbox render context that is not present in the
 * offline MapLibre setup, and can throw during its viewport calculation.
 *
 * `onInitialized` is wired to deck's own `onLoad`, which fires once deck has a
 * device and its resources are ready -- not on React mount. A mount effect
 * would report "initialized" for an overlay that never acquired a GL context,
 * which is a plausible default about the app's own health. `onFailed` carries
 * deck's `onError` instead, so a broken overlay is reported as
 * `request_failed` rather than as success.
 */
export function DeckOverlay({
  layers,
  onInitialized,
  onFailed,
}: {
  readonly layers: LayersList;
  readonly onInitialized?: () => void;
  readonly onFailed?: (message: string) => void;
}) {
  // Refs so the callbacks stay current without re-creating the overlay control.
  const initialized = useRef(onInitialized);
  const failed = useRef(onFailed);
  initialized.current = onInitialized;
  failed.current = onFailed;

  const overlay = useControl(() => new MapboxOverlay({
    layers,
    onLoad: () => initialized.current?.(),
    onError: (error: unknown) => failed.current?.(error instanceof Error ? error.message : String(error)),
  }));
  useEffect(() => { overlay.setProps({ layers }); }, [overlay, layers]);
  return null;
}
