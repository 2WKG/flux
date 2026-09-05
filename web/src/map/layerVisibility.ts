export type LayerToggle = Readonly<{
  id: string;
  label: string;
  visible: boolean;
}>;

/**
 * Toggle only a declared layer. This deliberately carries no scores, geometry,
 * status, or fallback values: interpretation stays in the server response.
 */
export function toggleLayerVisibility(
  layers: readonly LayerToggle[],
  layerId: string,
): readonly LayerToggle[] {
  if (!layers.some((layer) => layer.id === layerId)) {
    return layers;
  }
  return layers.map((layer) =>
    layer.id === layerId ? { ...layer, visible: !layer.visible } : layer,
  );
}
