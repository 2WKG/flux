import type { SymbolLayerSpecification } from 'maplibre-gl';

/** Native MapLibre alternative for the regional badge layer (not the GLB renderer).
 * First call map.addSprite('flux-grid', '/assets/flux-grid/symbols/flux-grid').
 * Source features must carry accepted archetype_id, label and status properties.
 * Use the existing inspector on hover/click to present label, artifact and scope.
 */
export function createFluxMapLibreSymbolLayer(sourceId: string, id = 'flux-category-symbols'): SymbolLayerSpecification {
  return {
    id, type: 'symbol', source: sourceId, maxzoom: 15,
    filter: ['in', ['get', 'status'], ['literal', ['source_supported', 'source_screened', 'hypothetical', 'synthetic']]],
    layout: {
      'icon-image': ['concat', 'flux-grid:', ['get', 'archetype_id']],
      'icon-size': 1,
      'icon-allow-overlap': true,
      'icon-ignore-placement': true,
      'icon-pitch-alignment': 'viewport',
      'icon-rotation-alignment': 'viewport',
    },
  };
}
