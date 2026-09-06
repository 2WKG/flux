/**
 * Graph structure and hop arithmetic for the GNN teaching section.
 *
 * Everything in this module is *graph structure*, not model output. There is no
 * trained graph neural network in Flux (see `GNN_STATUS` below), so this file
 * deliberately contains no learned weights, no inference, no accuracy figure and
 * no timing figure. What it computes is the part of the story that is exactly
 * true regardless of whether a model ever exists: which buses are within K hops
 * of a disturbance, and how many contingency candidates a screening pass has to
 * rank.
 *
 * The network below is a small schematic. It is not ACTIVSg2000, not Minnesota,
 * and not any real system; it exists so a reader can count the hops by eye.
 */

export interface GraphNode {
  readonly id: string;
  readonly name: string;
  /** Schematic layout only. Distances on screen carry no electrical meaning. */
  readonly x: number;
  readonly y: number;
}

export interface GraphEdge {
  readonly id: string;
  readonly from: string;
  readonly to: string;
  /** Series reactance, per unit. A real edge feature, illustrative values. */
  readonly reactance: number;
  /** Thermal rating, MW. The other real edge feature. */
  readonly ratingMw: number;
}

/** One round of message passing: the frontier that layer newly reaches. */
export interface HopRound {
  /** 0 is the seed itself, before any message has been sent. */
  readonly hop: number;
  /** Nodes first reached at this hop. */
  readonly newlyReached: readonly string[];
  /** Every node reached at or before this hop — the receptive field. */
  readonly reached: readonly string[];
  /** Edges that carried a message into a newly reached node at this hop. */
  readonly carryingEdgeIds: readonly string[];
}

export const SCHEMATIC_NODES: readonly GraphNode[] = [
  { id: "b1", name: "West generation", x: 62, y: 160 },
  { id: "b2", name: "Northwest tap", x: 172, y: 66 },
  { id: "b3", name: "Southwest tap", x: 172, y: 254 },
  { id: "b4", name: "Hub A", x: 300, y: 160 },
  { id: "b5", name: "North corridor", x: 424, y: 66 },
  { id: "b6", name: "South corridor", x: 424, y: 254 },
  { id: "b7", name: "Hub B", x: 546, y: 160 },
  { id: "b8", name: "East load", x: 646, y: 72 },
  { id: "b9", name: "Far south load", x: 646, y: 248 },
] as const;

export const SCHEMATIC_EDGES: readonly GraphEdge[] = [
  { id: "b1-b2", from: "b1", to: "b2", reactance: 0.22, ratingMw: 90 },
  { id: "b1-b3", from: "b1", to: "b3", reactance: 0.26, ratingMw: 90 },
  { id: "b2-b4", from: "b2", to: "b4", reactance: 0.18, ratingMw: 110 },
  { id: "b3-b4", from: "b3", to: "b4", reactance: 0.24, ratingMw: 80 },
  { id: "b4-b5", from: "b4", to: "b5", reactance: 0.2, ratingMw: 100 },
  { id: "b4-b6", from: "b4", to: "b6", reactance: 0.28, ratingMw: 70 },
  { id: "b5-b6", from: "b5", to: "b6", reactance: 0.32, ratingMw: 45 },
  { id: "b5-b7", from: "b5", to: "b7", reactance: 0.19, ratingMw: 100 },
  { id: "b6-b7", from: "b6", to: "b7", reactance: 0.27, ratingMw: 70 },
  { id: "b7-b8", from: "b7", to: "b8", reactance: 0.21, ratingMw: 85 },
  { id: "b7-b9", from: "b7", to: "b9", reactance: 0.3, ratingMw: 60 },
  { id: "b8-b9", from: "b8", to: "b9", reactance: 0.35, ratingMw: 40 },
] as const;

/**
 * The published status of the graph surrogate in Flux.
 *
 * `not_running` is the only value this section may render until a trained
 * checkpoint *and* a published error envelope both exist in the repository. The
 * evidence for the current value is recorded in `GNN_STATUS_EVIDENCE`; if that
 * ever stops being true, the section is wrong and must be corrected before the
 * label changes.
 */
export const GNN_STATUS = "not_running" as const;

export const GNN_STATUS_EVIDENCE: readonly string[] = [
  "No model definition, training entry point, or evaluation script for a graph network exists in the tree.",
  "No checkpoint artifact (.pt, .pth, .ckpt, .onnx, .safetensors) is tracked in the repository.",
  "No published error envelope exists, so there is no honest number to show.",
  "`torch` and `torch-geometric` are declared only as the optional `gnn` extra in `pyproject.toml`; a declared dependency is not a trained model.",
] as const;

const NODE_IDS: readonly string[] = SCHEMATIC_NODES.map((node) => node.id);

function adjacency(): Map<string, { readonly nodeId: string; readonly edgeId: string }[]> {
  const map = new Map(NODE_IDS.map((id) => [id, [] as { nodeId: string; edgeId: string }[]]));
  for (const edge of SCHEMATIC_EDGES) {
    const from = map.get(edge.from);
    const to = map.get(edge.to);
    if (!from || !to) throw new Error(`Edge ${edge.id} references a node that is not in the schematic.`);
    from.push({ nodeId: edge.to, edgeId: edge.id });
    to.push({ nodeId: edge.from, edgeId: edge.id });
  }
  return map;
}

/** Degree of every node, keyed by node id. A node's degree is how many neighbours it aggregates from. */
export function nodeDegrees(): Readonly<Record<string, number>> {
  const degrees: Record<string, number> = Object.fromEntries(NODE_IDS.map((id) => [id, 0]));
  for (const edge of SCHEMATIC_EDGES) {
    degrees[edge.from] += 1;
    degrees[edge.to] += 1;
  }
  return degrees;
}

/**
 * Breadth-first message passing from one seed node.
 *
 * Round 0 holds the seed alone: a network with no layers has read nothing but
 * the node's own features. Each further round is one message-passing layer, and
 * `reached` after round K is exactly the K-hop receptive field.
 */
export function messagePassingRounds(seedId: string, maxHops: number): readonly HopRound[] {
  if (!NODE_IDS.includes(seedId)) throw new Error(`Unknown seed node ${seedId}.`);
  if (!Number.isInteger(maxHops) || maxHops < 0) throw new Error("maxHops must be a non-negative integer.");
  const neighbors = adjacency();
  const seen = new Set([seedId]);
  const rounds: HopRound[] = [{ hop: 0, newlyReached: [seedId], reached: [seedId], carryingEdgeIds: [] }];
  let frontier: readonly string[] = [seedId];
  for (let hop = 1; hop <= maxHops; hop += 1) {
    const newlyReached: string[] = [];
    const carryingEdgeIds: string[] = [];
    for (const nodeId of frontier) {
      for (const link of neighbors.get(nodeId) ?? []) {
        if (seen.has(link.nodeId)) continue;
        seen.add(link.nodeId);
        newlyReached.push(link.nodeId);
        carryingEdgeIds.push(link.edgeId);
      }
    }
    rounds.push({
      hop,
      newlyReached,
      reached: NODE_IDS.filter((id) => seen.has(id)),
      carryingEdgeIds,
    });
    frontier = newlyReached;
    if (!newlyReached.length) break;
  }
  return rounds;
}

/** Hop distance from the seed to every node; `null` where the seed cannot reach it at all. */
export function hopDistances(seedId: string): Readonly<Record<string, number | null>> {
  const rounds = messagePassingRounds(seedId, NODE_IDS.length);
  const distances: Record<string, number | null> = Object.fromEntries(NODE_IDS.map((id) => [id, null]));
  for (const round of rounds) for (const id of round.newlyReached) distances[id] = round.hop;
  return distances;
}

/**
 * What a K-layer network can and cannot see from one seed.
 *
 * The blind count is the teaching point: stacking layers is the only way a
 * message-passing model widens its view, and every extra layer costs compute and
 * tends to smear node features together.
 */
export function receptiveField(seedId: string, layers: number) {
  const rounds = messagePassingRounds(seedId, layers);
  const reached = rounds[rounds.length - 1].reached;
  return {
    layers,
    seenCount: reached.length,
    blindCount: NODE_IDS.length - reached.length,
    totalCount: NODE_IDS.length,
    seen: reached,
    blind: NODE_IDS.filter((id) => !reached.includes(id)),
  };
}

/**
 * How many outage candidates a screening pass has to rank on this schematic.
 *
 * These are combinatorial counts over the graph, not measurements: N-1 is one
 * candidate per edge, N-2 is every unordered pair of edges. They are what makes
 * the screen-then-decide split worth anything — the candidate set grows
 * quadratically while the operator's decision budget does not.
 */
export function contingencyCounts() {
  const edges = SCHEMATIC_EDGES.length;
  return { edges, n1: edges, n2: (edges * (edges - 1)) / 2 };
}
