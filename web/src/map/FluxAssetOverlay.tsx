import { useEffect, useRef, useState } from 'react';
import { FluxMapboxOverlay } from './FluxMapboxOverlay';
import { useControl, useMap } from 'react-map-gl/maplibre';
import {
  FluxAssetCache, createFluxAssetLayers, loadFluxGroups, lodForZoom, fluxPlacementTooltip,
  type FluxAssetManifest, type FluxPlacement, type FluxLayerState, type LoadedFluxGroup, type LoadedFluxSymbols,
} from './layers/fluxGridAssets';

export interface FluxAssetOverlayProps {
  readonly manifest: FluxAssetManifest;
  readonly placements: readonly FluxPlacement[];
  readonly zoom: number;
  readonly mode?: FluxLayerState['mode'];
  readonly baseUrl?: string;
  readonly onSelect?: (placement: FluxPlacement) => void;
  /** Display a visible unavailable/error state in the host inspector. */
  readonly onError: (error: Error) => void;
}

/** Mount inside react-map-gl/maplibre Map. Mirrors the repository DeckOverlay convention. */
export function FluxAssetOverlay({ manifest, placements, zoom, mode = 'accepted', baseUrl, onSelect, onError }: FluxAssetOverlayProps) {
  const { current: map } = useMap();
  const [groups, setGroups] = useState<LoadedFluxGroup[]>([]);
  const [symbols, setSymbols] = useState<LoadedFluxSymbols>();
  const [beforeId, setBeforeId] = useState<string>();
  const cacheRef = useRef<FluxAssetCache | null>(null);
  const lod = lodForZoom(zoom);
  const overlay = useControl(() => new FluxMapboxOverlay({ interleaved: true, layers: [], getTooltip: fluxPlacementTooltip }));
  useEffect(() => {
    const cache = new FluxAssetCache(baseUrl);
    cacheRef.current = cache;
    return () => { cache.dispose(); cacheRef.current = null; };
  }, [baseUrl]);
  useEffect(() => {
    if (!map) return;
    const update = () => setBeforeId(map.getStyle().layers?.find(layer => layer.type === 'symbol')?.id);
    update(); map.on('styledata', update);
    return () => { map.off('styledata', update); };
  }, [map]);
  useEffect(() => {
    let current = true;
    const cache = cacheRef.current;
    if (!cache) return;
    setGroups([]);
    void Promise.all([loadFluxGroups(cache, manifest, placements, { zoom, mode }), cache.symbols(manifest)]).then(
      ([next, icons]) => { if (current) { setGroups(next); setSymbols(icons); } },
      error => { if (current) onError(error instanceof Error ? error : new Error(String(error))); },
    );
    return () => { current = false; };
  }, [baseUrl, manifest, placements, lod, mode, onError]);
  useEffect(() => {
    overlay.setProps({ layers: createFluxAssetLayers({ zoom, mode, beforeId, onSelect }, { placements, groups, symbols }) });
  }, [overlay, zoom, mode, beforeId, onSelect, placements, groups, symbols]);
  return null;
}
