import { useState, type ReactNode } from "react";

import { ControlRoom, type ControlRoomProps } from "./ControlRoom";
import { TexasModelStage, type TexasModelScene } from "./TexasModelStage";

export type PrimarySceneMode = "inventory" | "texas_model";

export interface PrimaryDemoProps {
  /** The only decision surface. Region changes flow through this prop's callback. */
  readonly controlRoom: ControlRoomProps;
  /** The source-backed spatial surface, normally GridInventoryPanel. */
  readonly spatialStage: ReactNode;
  /** Separate synthetic-ID scene. Never receives physical-inventory geometry. */
  readonly texasModelScene?: TexasModelScene;
  readonly sceneMode?: PrimarySceneMode;
  readonly onSceneModeChange?: (mode: PrimarySceneMode) => void;
  readonly inspectorSlot?: ReactNode;
  readonly chatSlot?: ReactNode;
  /** The retired five-bus fixture. It remains absent from the DOM until requested. */
  readonly legacyFixture?: ReactNode;
  readonly className?: string;
}

/**
 * A deliberately thin layout adapter. It owns no requests and never converts a
 * slot's absence into a substitute visualization or result.
 */
export function PrimaryDemo({
  controlRoom,
  spatialStage,
  texasModelScene,
  sceneMode: controlledSceneMode,
  onSceneModeChange,
  inspectorSlot,
  chatSlot,
  legacyFixture,
  className = "",
}: PrimaryDemoProps) {
  const [legacyVisible, setLegacyVisible] = useState(false);
  const [uncontrolledSceneMode, setUncontrolledSceneMode] = useState<PrimarySceneMode>("inventory");
  const sceneMode = controlledSceneMode ?? uncontrolledSceneMode;
  const setSceneMode = (mode: PrimarySceneMode) => {
    if (controlledSceneMode === undefined) setUncontrolledSceneMode(mode);
    onSceneModeChange?.(mode);
  };
  const modelEnabled = controlRoom.selectedRegionId === "texas" && Boolean(texasModelScene);
  return <section className={`primary-demo ${className}`} data-demo-runtime="primary">
    <section className="primary-demo__workspace" aria-label="Energy system workspace">
      <section className="primary-demo__spatial" aria-label="Primary spatial stage">
        <div className="primary-demo__scene-controls" role="group" aria-label="Scene mode">
          <button type="button" className={sceneMode === "inventory" ? "is-selected" : ""} aria-pressed={sceneMode === "inventory"} onClick={() => setSceneMode("inventory")}>Asset inventory</button>
          <button type="button" className={sceneMode === "texas_model" ? "is-selected" : ""} aria-pressed={sceneMode === "texas_model"} onClick={() => setSceneMode("texas_model")} disabled={!modelEnabled}>Texas grid model</button>
        </div>
        {sceneMode === "texas_model" && modelEnabled && texasModelScene ? <TexasModelStage scene={texasModelScene} /> : spatialStage}
      </section>
      <aside className="primary-demo__context" aria-label="Scenario controls and copilot">
        {chatSlot ? <div className="primary-demo__chat">{chatSlot}</div> : null}
        <details className="primary-demo__controls">
          <summary>Region, weather, and cascade details</summary>
          <ControlRoom {...controlRoom} />
        </details>
      </aside>
    </section>
    {inspectorSlot ? <section className="primary-demo__support" aria-label="Evidence inspector">
      <aside className="primary-demo__inspector" aria-label="Evidence inspector">{inspectorSlot}</aside>
    </section> : null}
    {legacyFixture ? <section className="primary-demo__legacy" aria-label="Legacy synthetic fixture">
      <button type="button" className="primary-demo__legacy-trigger" aria-expanded={legacyVisible} onClick={() => setLegacyVisible((visible) => !visible)}>
        {legacyVisible ? "Hide legacy synthetic fixture" : "Show legacy synthetic fixture"}
      </button>
      {legacyVisible ? <div className="primary-demo__legacy-content">{legacyFixture}</div> : null}
    </section> : null}
  </section>;
}
