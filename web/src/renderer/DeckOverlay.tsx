import { useEffect } from "react";
import { MapboxOverlay } from "@deck.gl/mapbox";
import type { LayersList } from "@deck.gl/core";
import { useControl } from "react-map-gl/maplibre";

/** Interleaved deck canvas owned by MapLibre's WebGL context. */
export function DeckOverlay({ layers, onInitialized }: { readonly layers: LayersList; readonly onInitialized?: () => void }) {
  const overlay = useControl(() => new MapboxOverlay({ interleaved: true, layers }));
  useEffect(() => { overlay.setProps({ layers }); }, [overlay, layers]);
  useEffect(() => { onInitialized?.(); }, [onInitialized, overlay]);
  return null;
}
