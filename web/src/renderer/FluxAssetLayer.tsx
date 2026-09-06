/** Verified GLB/symbol loader. It positions only caller-supplied artifacts. */
import { useEffect, useMemo, useRef } from "react";
import type { Layer, LayersList, PickingInfo } from "@deck.gl/core";
import { IconLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { ScenegraphLayer } from "@deck.gl/mesh-layers";

export type FluxAssetSourceMode = "physical_inventory" | "synthetic_texas_act";
export type StatusLabel =
  | "source_supported"
  | "source_screened"
  | "hypothetical"
  | "synthetic"
  | "unavailable"
  | "request_failed";
export interface FluxAssetPlacementInput {
  readonly id: string;
  readonly archetypeId: string;
  readonly position: readonly [number, number, number?];
  readonly headingDegrees?: number;
  readonly label: string;
  readonly artifactId: string;
  readonly status: StatusLabel;
  readonly topology?: "synthetic (ACTIVSg2000)";
}
interface Placement {
  readonly id: string;
  readonly archetypeId: string;
  readonly position: [number, number, number];
  readonly headingDegrees: number;
  readonly label: string;
  readonly artifactId: string;
  readonly status: StatusLabel;
}
interface Resource {
  readonly path: string;
  readonly sha256: string;
  readonly bytes: number;
}
interface File extends Resource {
  readonly triangles: number;
}
interface Manifest {
  readonly schema_version: 1;
  readonly contract_id: "flux:3d-asset-archetypes:v1";
  readonly assets: readonly {
    readonly archetype_id: string;
    readonly lods: Readonly<Record<"lod0" | "lod1" | "lod2", File>>;
  }[];
  readonly symbols: { readonly atlas: Resource; readonly mapping: Resource };
}
interface Icon {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly anchorX: number;
  readonly anchorY: number;
  readonly mask: boolean;
}
export interface FluxAssetLayerProps {
  readonly mode: FluxAssetSourceMode;
  readonly placements: readonly FluxAssetPlacementInput[];
  readonly zoom: number;
  readonly onLayersChange: (layers: LayersList) => void;
  readonly onStateChange?: (
    state: "ready" | "unavailable" | "request_failed",
    detail: string,
  ) => void;
  readonly onSelect?: (placement: Placement) => void;
  readonly manifestUrl?: string;
}

const STATUS: Readonly<Record<StatusLabel, string>> = {
  source_supported: "Source-supported",
  source_screened: "Source-screened",
  hypothetical: "Hypothetical",
  synthetic: "Synthetic",
  unavailable: "Unavailable",
  request_failed: "Request failed",
};
const physical: readonly StatusLabel[] = [
  "source_supported",
  "source_screened",
];

/** No IDs, names, or coordinates are inferred: source type and geometry arrive in the input. */
export function fluxPlacementsFor(
  mode: FluxAssetSourceMode,
  inputs: readonly FluxAssetPlacementInput[],
): readonly Placement[] {
  return inputs.map((input) => {
    if (mode === "physical_inventory" && !physical.includes(input.status))
      throw new Error(
        "Physical inventory placement " +
          input.id +
          " has non-placeable status " +
          input.status +
          ".",
      );
    if (
      mode === "synthetic_texas_act" &&
      (input.status !== "synthetic" ||
        input.topology !== "synthetic (ACTIVSg2000)")
    )
      throw new Error(
        "Synthetic Texas placement " +
          input.id +
          " must name synthetic (ACTIVSg2000).",
      );
    return {
      id: input.id,
      archetypeId: input.archetypeId,
      position: [input.position[0], input.position[1], input.position[2] ?? 0],
      headingDegrees: input.headingDegrees ?? 0,
      label: input.label,
      artifactId: input.artifactId,
      status: input.status,
    };
  });
}
function isManifest(value: unknown): value is Manifest {
  const r = value as Record<string, unknown> | null;
  return (
    !!r &&
    r.schema_version === 1 &&
    r.contract_id === "flux:3d-asset-archetypes:v1" &&
    Array.isArray(r.assets) &&
    r.assets.length === 18 &&
    typeof r.symbols === "object"
  );
}
async function bytes(base: string, file: Resource): Promise<ArrayBuffer> {
  const r = await fetch(base + "/" + file.path);
  if (!r.ok)
    throw new Error("3D asset request failed (" + r.status + "): " + file.path);
  const b = await r.arrayBuffer();
  const hash = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", b)),
    (x) => x.toString(16).padStart(2, "0"),
  ).join("");
  if (b.byteLength !== file.bytes || hash !== file.sha256)
    throw new Error("3D asset checksum mismatch: " + file.path);
  return b;
}
function currentLod(zoom: number): "symbol" | "lod0" | "lod1" | "lod2" {
  return zoom < 12
    ? "symbol"
    : zoom < 15
      ? "lod2"
      : zoom < 17
        ? "lod1"
        : "lod0";
}
function matrix(degrees: number): number[] {
  const a = (degrees * Math.PI) / 180,
    c = Math.cos(a),
    s = Math.sin(a);
  return [c, -s, 0, 0, 0, 0, 1, 0, -s, -c, 0, 0, 0, 0, 0, 1];
}

class Cache {
  private loaded = new Map<string, Promise<string>>();
  private iconPromise: Promise<{
    atlas: string;
    mapping: Record<string, Icon>;
  }> | null = null;
  private file(file: Resource): Promise<string> {
    const key = file.path + ":" + file.sha256;
    if (!this.loaded.has(key))
      this.loaded.set(
        key,
        // Preflight the immutable bytes before handing their same-origin URL to
        // deck.gl. Blob URLs are blocked by Flux's deliberate `connect-src
        // 'self'` policy, while a direct static URL remains CSP-safe.
        bytes("/assets/flux-grid", file).then(
          () => "/assets/flux-grid/" + file.path,
        ),
      );
    return this.loaded.get(key)!;
  }
  icons(manifest: Manifest) {
    if (!this.iconPromise)
      this.iconPromise = Promise.all([
        bytes("/assets/flux-grid", manifest.symbols.atlas),
        bytes("/assets/flux-grid", manifest.symbols.mapping),
      ]).then(([, mapping]) => {
        return {
          atlas: "/assets/flux-grid/" + manifest.symbols.atlas.path,
          mapping: JSON.parse(new TextDecoder().decode(mapping)) as Record<
            string,
            Icon
          >,
        };
      });
    return this.iconPromise;
  }
  model(file: File) {
    return this.file(file);
  }
  dispose() {
    this.loaded.clear();
    this.iconPromise = null;
  }
}

async function makeLayers(
  cache: Cache,
  manifest: Manifest,
  placements: readonly Placement[],
  zoom: number,
  onSelect?: (p: Placement) => void,
): Promise<LayersList> {
  const click = (info: PickingInfo<Placement>) => {
    if (info.object) onSelect?.(info.object);
  };
  const icons = await cache.icons(manifest);
  const badges: Layer[] = [
    new ScatterplotLayer<Placement>({
      id: "flux-asset-backplates",
      data: placements,
      getPosition: (p) => p.position,
      getRadius: 21,
      radiusUnits: "pixels",
      getFillColor: [5, 17, 26, 242],
      getLineColor: [106, 165, 184, 185],
      stroked: true,
      getLineWidth: 1,
      lineWidthUnits: "pixels",
      pickable: true,
      onClick: click,
    }),
    new IconLayer<Placement>({
      id: "flux-asset-symbols",
      data: placements,
      iconAtlas: icons.atlas,
      iconMapping: icons.mapping,
      getIcon: (p) => p.archetypeId,
      getPosition: (p) => p.position,
      getSize: 32,
      sizeUnits: "pixels",
      sizeMinPixels: 24,
      getColor: [222, 246, 251, 255],
      pickable: true,
      onClick: click,
    }),
  ];
  const labels = new TextLayer<Placement>({
    id: "flux-asset-labels",
    data: placements,
    getPosition: (p) => p.position,
    getText: (p) => p.label + "\n" + STATUS[p.status],
    getSize: 12,
    getColor: [219, 234, 243, 255],
    getPixelOffset: [28, 0],
    getTextAnchor: "start",
    background: true,
    getBackgroundColor: [9, 19, 29, 230],
    backgroundPadding: [6, 3],
    pickable: true,
    onClick: click,
  });
  const lod = currentLod(zoom);
  if (lod === "symbol") return [...badges, labels];
  const assets = new Map(
    manifest.assets.map((asset) => [asset.archetype_id, asset]),
  );
  const groups = new Map<string, Placement[]>();
  for (const p of placements) {
    if (!assets.has(p.archetypeId))
      throw new Error(
        "3D asset manifest has no " + p.archetypeId + " archetype.",
      );
    groups.set(p.archetypeId, [...(groups.get(p.archetypeId) ?? []), p]);
  }
  const scenes = await Promise.all(
    [...groups.entries()].map(
      async ([id, entries]) =>
        new ScenegraphLayer<Placement>({
          id: "flux-asset-" + id + "-" + lod,
          data: entries,
          scenegraph: await cache.model(assets.get(id)!.lods[lod]),
          getPosition: (p) => p.position,
          getTransformMatrix: (p) => matrix(p.headingDegrees),
          getColor: [255, 255, 255, 255],
          pickable: true,
          onClick: click,
          _lighting: "pbr",
        }),
    ),
  );
  return lod === "lod2" ? [...scenes, ...badges, labels] : [...scenes, labels];
}

export function FluxAssetLayer({
  mode,
  placements: input,
  zoom,
  onLayersChange,
  onStateChange,
  onSelect,
  manifestUrl = "/assets/flux-grid/manifest.json",
}: FluxAssetLayerProps) {
  const cache = useRef<Cache | null>(null);
  if (!cache.current) cache.current = new Cache();
  const placements = useMemo(
    () => fluxPlacementsFor(mode, input),
    [mode, input],
  );
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const r = await fetch(manifestUrl, { cache: "no-store" });
        const payload: unknown = r.ok ? await r.json() : null;
        if (!isManifest(payload))
          throw new Error(
            r.ok
              ? "3D asset manifest is missing the Flux v1 contract."
              : "3D asset manifest request failed (" + r.status + ").",
          );
        const layers = await makeLayers(
          cache.current!,
          payload,
          placements,
          zoom,
          onSelect,
        );
        if (active) {
          onLayersChange(layers);
          onStateChange?.(
            "ready",
            placements.length +
              " verified 3D placement" +
              (placements.length === 1 ? "" : "s") +
              " loaded.",
          );
        }
      } catch (error) {
        if (active) {
          onLayersChange([]);
          onStateChange?.(
            "request_failed",
            error instanceof Error ? error.message : String(error),
          );
        }
      }
    })();
    return () => {
      active = false;
      onLayersChange([]);
    };
  }, [
    manifestUrl,
    mode,
    onLayersChange,
    onSelect,
    onStateChange,
    placements,
    zoom,
  ]);
  useEffect(() => () => cache.current?.dispose(), []);
  return null;
}
