/** Flux geometry only. Bind identities and status labels from accepted server artifacts. */
import { COORDINATE_SYSTEM, type Layer, type PickingInfo } from '@deck.gl/core';
import { IconLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import { ScenegraphLayer } from 'deck.gl';

export const STATUS_PRESENTATION = {
  source_supported: { label: 'Source-supported', glyph: '✓', color: [73, 205, 187] },
  source_screened: { label: 'Source-screened', glyph: '◒', color: [104, 204, 192] },
  hypothetical: { label: 'Hypothetical', glyph: '↗', color: [183, 144, 237] },
  synthetic: { label: 'Synthetic', glyph: '⋯', color: [137, 151, 238] },
  unavailable: { label: 'Unavailable', glyph: '⊘', color: [236, 184, 100] },
  request_failed: { label: 'Request failed', glyph: '×', color: [238, 117, 133] },
} as const;

export type StatusLabel = keyof typeof STATUS_PRESENTATION;
export type Lod = 'lod0' | 'lod1' | 'lod2';
export type Position = [longitude: number, latitude: number, altitudeMeters: number];

export interface FluxPlacement {
  readonly id: string;
  readonly archetype_id: string;
  readonly position: Position;
  /** Clockwise degrees from north. Zero aligns author -Z with map north. */
  readonly heading_degrees: number;
  readonly label: string;
  /** Null is allowed only in a geometry catalogue, never for a placed server feature. */
  readonly status: StatusLabel | null;
  readonly artifact_id: string;
}

export interface AssetResource {
  readonly path: string;
  readonly sha256: string;
  readonly bytes: number;
}
export interface AssetFile extends AssetResource {
  readonly triangles: number;
}

export interface FluxAsset {
  readonly archetype_id: string;
  readonly semantic_name: string;
  readonly category: string;
  readonly footprint_m: { readonly width: number; readonly length: number };
  readonly bounds_m?: { readonly min: [number, number, number]; readonly max: [number, number, number] };
  readonly lods: Readonly<Record<Lod, AssetFile>>;
  readonly preview: string;
  readonly metadata: string;
}

export interface FluxAssetManifest {
  readonly schema_version: 1;
  readonly contract_id: 'flux:3d-asset-archetypes:v1';
  readonly transform: { readonly unit: 'meter'; readonly up: 'Y'; readonly forward: '-Z'; readonly pivot: 'ground_center' };
  readonly assets: readonly FluxAsset[];
  readonly symbols: { readonly atlas: AssetResource; readonly mapping: AssetResource; readonly maplibre_sprite: string };
}

export interface LoadedFluxSymbols {
  readonly atlas: string;
  readonly mapping: Record<string, { x: number; y: number; width: number; height: number; anchorX: number; anchorY: number; mask: boolean }>;
}

export interface FluxLayerState {
  readonly zoom: number;
  /** Accept only real server coordinates in accepted mode. Catalogue positions are a local test grid. */
  readonly mode: 'accepted' | 'catalogue';
  readonly beforeId?: string;
  readonly forcedLod?: Lod;
  readonly selectedId?: string;
  readonly onSelect?: (placement: FluxPlacement) => void;
}

export interface LoadedFluxGroup {
  readonly key: string;
  readonly asset: FluxAsset;
  readonly lod: Lod;
  readonly status: StatusLabel | null;
  readonly placements: FluxPlacement[];
  readonly scenegraph: string;
}

/** Presentation defaults, not geography-specific rules. Keep symbols at regional zoom. */
export function lodForZoom(zoom: number): Lod | 'symbol' {
  return zoom < 12 ? 'symbol' : zoom < 15 ? 'lod2' : zoom < 17 ? 'lod1' : 'lod0';
}

/** glTF (X right, Y up, -Z forward) -> deck ENU (X east, Y north, Z up).
 * Column-major; applies the axis conversion once and then clockwise heading.
 * Do not also add modelMatrix rotateX, getOrientation, or an asset-specific scale.
 */
export function gltfToMapMatrix(headingDegrees: number): number[] {
  if (!Number.isFinite(headingDegrees)) throw new Error('Heading must be finite degrees.');
  const angle = headingDegrees * Math.PI / 180;
  const c = Math.cos(angle), s = Math.sin(angle);
  return [c, -s, 0, 0, 0, 0, 1, 0, -s, -c, 0, 0, 0, 0, 0, 1];
}

export function assertPlacements(placements: readonly FluxPlacement[], mode: FluxLayerState['mode']): void {
  const ids = new Set<string>();
  for (const p of placements) {
    if (!p.id || ids.has(p.id)) throw new Error(`Missing or duplicate placement ID: ${p.id}`);
    ids.add(p.id);
    if (!p.artifact_id || !p.label) throw new Error(`Placement ${p.id} lacks artifact identity or readable label.`);
    if (p.position.length !== 3 || !p.position.every(Number.isFinite) || Math.abs(p.position[0]) > 180 || Math.abs(p.position[1]) >= 85.051129) {
      throw new Error(`Placement ${p.id} requires [longitude, latitude, altitudeMeters] in Web Mercator range.`);
    }
    if (!Number.isFinite(p.heading_degrees)) throw new Error(`Placement ${p.id} has invalid heading.`);
    if (p.status === null ? mode !== 'catalogue' : !Object.prototype.hasOwnProperty.call(STATUS_PRESENTATION, p.status)) {
      throw new Error(`Placement ${p.id} requires an accepted status token.`);
    }
  }
}

type GlbMaterial = { name?: string; pbrMetallicRoughness?: { baseColorFactor?: number[] }; emissiveFactor?: number[] };
type GlbDocument = { materials?: GlbMaterial[]; buffers?: { uri?: string }[]; images?: { uri?: string }[] };

/** Rewrite only MAT_STATUS in an in-memory GLB. Authored accent/shell materials are untouched. */
export function statusVariantGlb(source: ArrayBuffer, status: StatusLabel | null): ArrayBuffer {
  const view = new DataView(source);
  if (source.byteLength < 20 || view.getUint32(0, true) !== 0x46546c67 || view.getUint32(4, true) !== 2 || view.getUint32(8, true) !== source.byteLength) {
    throw new Error('Invalid glTF 2.0 binary header.');
  }
  const jsonLength = view.getUint32(12, true);
  if (view.getUint32(16, true) !== 0x4e4f534a || 20 + jsonLength > source.byteLength) throw new Error('Invalid GLB JSON chunk.');
  const document = JSON.parse(new TextDecoder().decode(new Uint8Array(source, 20, jsonLength))) as GlbDocument;
  if (document.buffers?.some(x => x.uri) || document.images?.some(x => x.uri)) throw new Error('Flux models must have no external sidecar resources.');
  const material = document.materials?.find(x => x.name === 'MAT_STATUS');
  if (!material) throw new Error('Asset lacks the neutral MAT_STATUS material slot.');
  if (status === null) return source.slice(0);
  const rgb = STATUS_PRESENTATION[status].color.map(channel => channel / 255);
  material.pbrMetallicRoughness ??= {};
  const alpha = material.pbrMetallicRoughness.baseColorFactor?.[3] ?? 1;
  material.pbrMetallicRoughness.baseColorFactor = [...rgb, alpha];
  material.emissiveFactor = rgb.map(channel => channel * 0.35);
  const json = new TextEncoder().encode(JSON.stringify(document));
  const paddedLength = Math.ceil(json.length / 4) * 4;
  const remaining = new Uint8Array(source, 20 + jsonLength);
  const result = new ArrayBuffer(20 + paddedLength + remaining.byteLength);
  const targetView = new DataView(result);
  targetView.setUint32(0, 0x46546c67, true); targetView.setUint32(4, 2, true);
  targetView.setUint32(8, result.byteLength, true); targetView.setUint32(12, paddedLength, true);
  targetView.setUint32(16, 0x4e4f534a, true);
  new Uint8Array(result, 20, paddedLength).fill(32);
  new Uint8Array(result, 20, json.length).set(json);
  new Uint8Array(result, 20 + paddedLength).set(remaining);
  return result;
}

export class FluxAssetCache {
  private originals = new Map<string, Promise<ArrayBuffer>>();
  private variants = new Map<string, Promise<string>>();
  private objectUrls = new Set<string>();
  private symbolSets = new Map<string, Promise<LoadedFluxSymbols>>();
  private disposed = false;
  constructor(private readonly baseUrl = '/assets/flux-grid/') {}

  private bytes(file: AssetResource): Promise<ArrayBuffer> {
    const key = `${file.path}:${file.sha256}`;
    let pending = this.originals.get(key);
    if (!pending) {
      pending = (async () => {
        const response = await fetch(`${this.baseUrl.replace(/\/$/, '')}/${file.path}`);
        if (!response.ok) throw new Error(`Asset request failed (${response.status}): ${file.path}`);
        const buffer = await response.arrayBuffer();
        if (buffer.byteLength !== file.bytes) throw new Error(`Asset size mismatch: ${file.path}`);
        const digest = await crypto.subtle.digest('SHA-256', buffer);
        const hex = Array.from(new Uint8Array(digest), x => x.toString(16).padStart(2, '0')).join('');
        if (hex !== file.sha256) throw new Error(`Asset checksum mismatch: ${file.path}`);
        return buffer;
      })();
      this.originals.set(key, pending);
      void pending.catch(() => this.originals.delete(key));
    }
    return pending;
  }

  async symbols(manifest: FluxAssetManifest): Promise<LoadedFluxSymbols> {
    if (this.disposed) throw new Error('Asset cache has been disposed.');
    if (!manifest.symbols) throw new Error('Flux category symbol atlas is unavailable.');
    const { atlas, mapping } = manifest.symbols;
    const key = `${atlas.sha256}:${mapping.sha256}`;
    let pending = this.symbolSets.get(key);
    if (!pending) {
      pending = Promise.all([this.bytes(atlas), this.bytes(mapping)]).then(([imageBytes, mappingBytes]) => {
        if (this.disposed) throw new Error('Asset cache has been disposed.');
        const parsed = JSON.parse(new TextDecoder().decode(mappingBytes)) as LoadedFluxSymbols['mapping'];
        for (const asset of manifest.assets) {
          const icon = Object.prototype.hasOwnProperty.call(parsed, asset.archetype_id) && parsed[asset.archetype_id];
          if (!icon || ![icon.x, icon.y, icon.width, icon.height].every(Number.isFinite) || icon.width <= 0 || icon.height <= 0) throw new Error(`Missing or invalid category symbol: ${asset.archetype_id}`);
        }
        const url = URL.createObjectURL(new Blob([imageBytes], { type: 'image/png' }));
        this.objectUrls.add(url);
        return { atlas: url, mapping: parsed };
      });
      this.symbolSets.set(key, pending);
      void pending.catch(() => this.symbolSets.delete(key));
    }
    return pending;
  }

  async url(file: AssetFile, status: StatusLabel | null): Promise<string> {
    if (this.disposed) throw new Error('Asset cache has been disposed.');
    const key = `${file.path}:${file.sha256}:${status ?? 'neutral'}`;
    let pending = this.variants.get(key);
    if (!pending) {
      pending = this.bytes(file).then(buffer => {
        if (this.disposed) throw new Error('Asset cache has been disposed.');
        const url = URL.createObjectURL(new Blob([statusVariantGlb(buffer, status)], { type: 'model/gltf-binary' }));
        this.objectUrls.add(url);
        return url;
      });
      this.variants.set(key, pending);
      void pending.catch(() => this.variants.delete(key));
    }
    return pending;
  }

  dispose(): void {
    this.disposed = true;
    for (const url of this.objectUrls) URL.revokeObjectURL(url);
    this.objectUrls.clear(); this.originals.clear(); this.variants.clear(); this.symbolSets.clear();
  }
}

/** Grouping is instancing: one ScenegraphLayer per archetype / LOD / status. */
export async function loadFluxGroups(
  cache: FluxAssetCache, manifest: FluxAssetManifest, placements: readonly FluxPlacement[], state: FluxLayerState,
): Promise<LoadedFluxGroup[]> {
  assertPlacements(placements, state.mode);
  for (const placement of placements) {
    if (!manifest.assets.some(asset => asset.archetype_id === placement.archetype_id)) throw new Error(`Unknown archetype: ${placement.archetype_id}`);
  }
  const lod = state.forcedLod ?? lodForZoom(state.zoom);
  if (lod === 'symbol') return [];
  const groups = new Map<string, Omit<LoadedFluxGroup, 'scenegraph'>>();
  for (const p of placements) {
    // An unavailable/failed artifact must not gain a physical placement through a fallback.
    if (p.status === 'unavailable' || p.status === 'request_failed') continue;
    const asset = manifest.assets.find(x => x.archetype_id === p.archetype_id);
    if (!asset) throw new Error(`Unknown archetype: ${p.archetype_id}`);
    const key = `${p.archetype_id}-${lod}-${p.status ?? 'neutral'}`;
    let group = groups.get(key);
    if (!group) { group = { key, asset, lod, status: p.status, placements: [] }; groups.set(key, group); }
    group.placements.push(p);
  }
  const triangles = Array.from(groups.values()).reduce((total, group) => total + group.asset.lods[lod].triangles * group.placements.length, 0);
  if (triangles > 4_000_000) throw new Error(`Flux scene exceeds the 4,000,000 triangle contract (${triangles}); cull placements or select a lower LOD.`);
  return Promise.all(Array.from(groups.values(), async group => ({ ...group, scenegraph: await cache.url(group.asset.lods[lod], group.status) })));
}

/** Spec 06 layer factory. Pass only viewport-culled placements, keep data references stable. */
export function createFluxAssetLayers(
  state: FluxLayerState,
  data: { readonly placements: readonly FluxPlacement[]; readonly groups: readonly LoadedFluxGroup[]; readonly symbols?: LoadedFluxSymbols },
): Layer[] {
  assertPlacements(data.placements, state.mode);
  const visible = data.placements.filter(p => p.status !== 'unavailable' && p.status !== 'request_failed');
  const onClick = (info: PickingInfo<FluxPlacement>) => { if (info.object) state.onSelect?.(info.object); };
  const common = { coordinateSystem: COORDINATE_SYSTEM.LNGLAT, pickable: true, onClick, beforeId: state.beforeId };
  const lod = state.forcedLod ?? lodForZoom(state.zoom);
  const badges: Layer[] = data.symbols ? [
    new ScatterplotLayer<FluxPlacement>({
      ...common, id: 'flux-assets-identity-backplates', data: visible,
      getPosition: p => p.position, radiusUnits: 'pixels', getRadius: 21,
      stroked: true, getLineColor: [106, 165, 184, 185], lineWidthUnits: 'pixels', getLineWidth: 1,
      getFillColor: [5, 17, 26, 242], billboard: true,
      parameters: { depthCompare: 'always', depthWriteEnabled: false },
    }),
    new IconLayer<FluxPlacement>({
      ...common, id: 'flux-assets-category-icons', data: visible,
      iconAtlas: data.symbols.atlas, iconMapping: data.symbols.mapping,
      getIcon: p => p.archetype_id, getPosition: p => p.position,
      sizeUnits: 'pixels', getSize: 32, sizeMinPixels: 24, billboard: true,
      // Category identity is neutral. Artifact status remains separate text/glyph/material.
      getColor: [222, 246, 251, 255],
      parameters: { depthCompare: 'always', depthWriteEnabled: false },
    }),
  ] : [];
  if (lod === 'symbol') return [...badges,
    new TextLayer<FluxPlacement>({
      ...common, id: 'flux-assets-symbol-labels', data: visible,
      getPosition: p => p.position, getText: p => p.status ? `${p.label}\n${STATUS_PRESENTATION[p.status].glyph} ${STATUS_PRESENTATION[p.status].label}` : p.label,
      getSize: 12, getColor: [217, 234, 243, 255], getPixelOffset: [28, 0], getTextAnchor: 'start',
      fontFamily: 'Arial, sans-serif', background: true, getBackgroundColor: [9, 19, 29, 215], backgroundPadding: [5, 3],
      parameters: { depthCompare: 'always', depthWriteEnabled: false },
    }),
  ];
  const sceneLayers: Layer[] = data.groups.filter(group => group.lod === lod).map(group => new ScenegraphLayer<FluxPlacement>({
    ...common, id: `flux-assets-${group.key}`, data: group.placements,
    scenegraph: group.scenegraph, getPosition: p => p.position,
    getTransformMatrix: p => gltfToMapMatrix(p.heading_degrees),
    getColor: [255, 255, 255, 255], sizeScale: 1,
    _lighting: 'pbr', _animations: null,
    // GLB alphaMode controls material blending. No layer-wide opacity or bloom assumption.
  }));
  if (lod === 'lod2') sceneLayers.push(...badges);
  sceneLayers.push(new TextLayer<FluxPlacement>({
    ...common, id: 'flux-assets-status-labels', data: visible.filter(p => p.status !== null),
    getPosition: p => p.position,
    getText: p => p.status ? `${STATUS_PRESENTATION[p.status].glyph} ${STATUS_PRESENTATION[p.status].label}` : '',
    getSize: 12, getColor: [219, 234, 243, 255], getPixelOffset: [0, 24],
    fontFamily: 'Arial, sans-serif', background: true, getBackgroundColor: [9, 19, 29, 230], backgroundPadding: [6, 3],
  }));
  return sceneLayers;
}

/** Reuse on the host MapboxOverlay so hovering any identity badge opens its readable name. */
export function fluxPlacementTooltip(info: PickingInfo<FluxPlacement>): { text: string } | null {
  const p = info.object;
  return p ? { text: `${p.label}${p.status ? `\n${STATUS_PRESENTATION[p.status].glyph} ${STATUS_PRESENTATION[p.status].label}` : '\nGeometry catalogue'}` } : null;
}
