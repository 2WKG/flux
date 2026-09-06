/**
 * Public surface of the JEPA explainer section.
 *
 * A page mounts `JepaSection`. Nothing else in the repository needs anything
 * from this directory, and this directory imports nothing outside it.
 */
export { JepaSection } from "./JepaSection";
export { RECORDED_EVALUATION, ARTIFACT_PROVENANCE } from "./recordedEvaluation";
export { runSchematicTraining, SCHEMATIC_DISCLAIMER } from "./embeddingSchematic";
