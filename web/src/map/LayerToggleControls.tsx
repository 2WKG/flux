import type { LayerToggle } from "./layerVisibility";
import "./layerToggleControls.css";

type LayerToggleControlsProps = Readonly<{
  layers: readonly LayerToggle[];
  onToggle: (layerId: string) => void;
}>;

/** Controlled visibility controls for already-declared analytical layers. */
export function LayerToggleControls({
  layers,
  onToggle,
}: LayerToggleControlsProps) {
  return (
    <fieldset className="layer-toggle-controls">
      <legend>Analytical layers</legend>
      {layers.map((layer) => (
        <label key={layer.id}>
          <input
            checked={layer.visible}
            onChange={() => onToggle(layer.id)}
            type="checkbox"
          />
          <span>{layer.label}</span>
        </label>
      ))}
    </fieldset>
  );
}
