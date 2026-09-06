import { MapboxOverlay } from '@deck.gl/mapbox';
import { VERSION as DECK_VERSION } from '@deck.gl/core';
import { getVersion as getMapLibreVersion } from 'maplibre-gl';

type PublicMap = {
  transform?: { readonly height: number; readonly elevation: number };
  getContainer(): HTMLElement;
  getCenterElevation?: () => number;
};
type CompatibilityEntry = { count: number; facade: NonNullable<PublicMap['transform']>; original?: PropertyDescriptor };
const compatibility = new WeakMap<PublicMap, CompatibilityEntry>();

function attachCompatibility(target: PublicMap): (() => void) | undefined {
  if (!/^6\./.test(getMapLibreVersion()) || !/^9\.3\./.test(DECK_VERSION)) return;
  let entry = compatibility.get(target);
  if (entry) entry.count += 1;
  else if (!target.transform && target.getCenterElevation) {
    const original = Object.getOwnPropertyDescriptor(target, 'transform');
    if (original && !original.configurable) throw new Error('Map transform facade is not configurable.');
    const facade = {
      get height() { return target.getContainer().clientHeight; },
      get elevation() { return target.getCenterElevation?.() ?? 0; },
    };
    entry = { count: 1, facade, original };
    Object.defineProperty(target, 'transform', { configurable: true, get: () => facade });
    compatibility.set(target, entry);
  }
  if (!entry) return;
  return () => {
    if (--entry.count > 0) return;
    if (target.transform === entry.facade) {
      if (entry.original) Object.defineProperty(target, 'transform', entry.original);
      else Reflect.deleteProperty(target, 'transform');
    }
    compatibility.delete(target);
  };
}

/** deck.gl 9.3.11 still reads map.transform.height/elevation; MapLibre 6 removed
 * that private field. Supply those read-only values through public MapLibre APIs.
 * No camera matrices or private _camera values are borrowed or overwritten.
 * Remove this adapter after upgrading to a deck.gl release supporting MapLibre 6.
 * https://github.com/visgl/deck.gl/issues/10501
 */
export class FluxMapboxOverlay extends MapboxOverlay {
  private removeCompatibility?: () => void;

  onAdd(map: Parameters<MapboxOverlay['onAdd']>[0]): HTMLDivElement {
    const target = map as unknown as PublicMap;
    this.removeCompatibility = attachCompatibility(target);
    try { return super.onAdd(map); }
    catch (error) { this.removeCompatibility?.(); this.removeCompatibility = undefined; throw error; }
  }

  onRemove(): void {
    try { super.onRemove(); }
    finally { this.removeCompatibility?.(); this.removeCompatibility = undefined; }
  }
}
