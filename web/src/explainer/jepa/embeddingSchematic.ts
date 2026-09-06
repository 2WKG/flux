/**
 * A deterministic 2-D schematic of the JEPA training objective.
 *
 * THIS IS AN ILLUSTRATION, NOT MODEL OUTPUT. The coordinates below are invented
 * teaching constants. The recorded 2WKG-474 run embeds into 12 dimensions with
 * weights that are not loaded in the browser, so nothing here is a projection of
 * a real embedding and no figure produced by this file is an accuracy claim.
 *
 * What the schematic *does* reproduce faithfully is the shape of the objective:
 *
 *   - a context encoder places a window of history at a point in latent space,
 *   - a predictor moves that point to where it thinks the future window lands,
 *   - a separate target encoder — updated only by an exponential moving average,
 *     never by gradients (stop-gradient) — places the actual future window,
 *   - the loss is the distance between those two *embeddings*. Raw customer
 *     counts are never reconstructed, so the noise the counts carry is not
 *     something the objective is forced to fit.
 *
 * The predictor here is a 2x2 affine map trained by plain gradient descent, so
 * the animation is a real optimisation, just of a toy problem with no data in it.
 */
export interface Vec2 {
  readonly x: number;
  readonly y: number;
}

export interface SchematicWindow {
  readonly id: string;
  /** An illustrative regime name. Not a county and not a recorded window. */
  readonly label: string;
  readonly context: Vec2;
  readonly future: Vec2;
}

export interface SchematicPrediction {
  readonly windowId: string;
  readonly label: string;
  readonly context: Vec2;
  readonly predicted: Vec2;
  /** Where the EMA target encoder currently places the true future window. */
  readonly emaTarget: Vec2;
  readonly trueFuture: Vec2;
  /** Distance the loss actually penalises: predicted vs. EMA target embedding. */
  readonly embeddingError: number;
}

export interface SchematicFrame {
  readonly epoch: number;
  readonly predictions: readonly SchematicPrediction[];
  /** Mean squared predicted-vs-target embedding error across the four windows. */
  readonly embeddingLoss: number;
  readonly caption: string;
}

export const SCHEMATIC_DISCLAIMER =
  "Schematic illustration of the training objective. Invented 2-D coordinates, not the recorded model's 12-dimensional embedding and not model output.";

/** Four illustrative context windows, spread so a linear predictor has something to learn. */
export const SCHEMATIC_WINDOWS: readonly SchematicWindow[] = [
  { id: "calm", label: "Calm overnight hours", context: { x: -0.7, y: -0.45 }, future: { x: 0, y: 0 } },
  { id: "ramp", label: "Storm ramp", context: { x: -0.15, y: 0.6 }, future: { x: 0, y: 0 } },
  { id: "restore", label: "Restoration tail", context: { x: 0.45, y: -0.6 }, future: { x: 0, y: 0 } },
  { id: "flat", label: "Flat baseline", context: { x: 0.8, y: 0.25 }, future: { x: 0, y: 0 } },
].map((entry) => ({ ...entry, future: trueFutureOf(entry.context) }));

/**
 * The invented "true" relationship the predictor has to discover: a rotation and
 * a small shift. Nothing about it is estimated from EAGLE-I data.
 */
function trueFutureOf(context: Vec2): Vec2 {
  return {
    x: 0.75 * context.x - 0.35 * context.y + 0.12,
    y: 0.3 * context.x + 0.8 * context.y - 0.1,
  };
}

export const SCHEMATIC_HYPERPARAMETERS = {
  epochs: 40,
  learningRate: 0.35,
  /** Deliberately faster than the recorded run's 0.97 so the drift is visible. */
  emaMomentum: 0.8,
} as const;

function round(value: number): number {
  return Number(value.toFixed(6));
}

function distance(left: Vec2, right: Vec2): number {
  return Math.hypot(left.x - right.x, left.y - right.y);
}

/**
 * Run the toy JEPA optimisation and return one frame per epoch, frame 0 being
 * the untrained state. Pure and deterministic: the same call always yields the
 * same frames, so the animation is a replay rather than a live random process.
 */
export function runSchematicTraining(
  epochs: number = SCHEMATIC_HYPERPARAMETERS.epochs,
): readonly SchematicFrame[] {
  if (!Number.isInteger(epochs) || epochs < 1) {
    throw new Error(`Schematic epoch count must be a positive integer, received ${epochs}.`);
  }
  // A predictor that starts badly wrong, so the first frame shows a real gap.
  let weights = [
    [0.2, 0],
    [0, 0.2],
  ];
  let bias: Vec2 = { x: 0, y: 0 };
  // The target encoder starts as a copy of the context encoder, as in a real
  // JEPA, then EMAs toward the future embedding. It is never given a gradient.
  const emaTargets = SCHEMATIC_WINDOWS.map((entry) => entry.context);
  const momentum = SCHEMATIC_HYPERPARAMETERS.emaMomentum;
  const frames: SchematicFrame[] = [];

  for (let epoch = 0; epoch <= epochs; epoch += 1) {
    for (let index = 0; index < SCHEMATIC_WINDOWS.length; index += 1) {
      const target = SCHEMATIC_WINDOWS[index].future;
      const current = emaTargets[index];
      emaTargets[index] = {
        x: momentum * current.x + (1 - momentum) * target.x,
        y: momentum * current.y + (1 - momentum) * target.y,
      };
    }

    const predictions = SCHEMATIC_WINDOWS.map((entry, index) => {
      const predicted = {
        x: weights[0][0] * entry.context.x + weights[0][1] * entry.context.y + bias.x,
        y: weights[1][0] * entry.context.x + weights[1][1] * entry.context.y + bias.y,
      };
      const emaTarget = emaTargets[index];
      return {
        windowId: entry.id,
        label: entry.label,
        context: entry.context,
        predicted: { x: round(predicted.x), y: round(predicted.y) },
        emaTarget: { x: round(emaTarget.x), y: round(emaTarget.y) },
        trueFuture: { x: round(entry.future.x), y: round(entry.future.y) },
        embeddingError: round(distance(predicted, emaTarget)),
      };
    });

    frames.push({
      epoch,
      predictions,
      embeddingLoss: round(
        predictions.reduce((sum, entry) => sum + entry.embeddingError ** 2, 0) / predictions.length,
      ),
      caption: captionFor(epoch, epochs),
    });

    if (epoch === epochs) break;

    // Gradient of the mean squared embedding error, with the target treated as a
    // constant. That stop-gradient is the part that makes this a JEPA step and
    // not a two-tower regression onto a moving label.
    const scale = (2 * SCHEMATIC_HYPERPARAMETERS.learningRate) / predictions.length;
    const gradient = [
      [0, 0],
      [0, 0],
    ];
    let biasGradient = { x: 0, y: 0 };
    for (const entry of predictions) {
      const errorX = entry.predicted.x - entry.emaTarget.x;
      const errorY = entry.predicted.y - entry.emaTarget.y;
      gradient[0][0] += errorX * entry.context.x;
      gradient[0][1] += errorX * entry.context.y;
      gradient[1][0] += errorY * entry.context.x;
      gradient[1][1] += errorY * entry.context.y;
      biasGradient = { x: biasGradient.x + errorX, y: biasGradient.y + errorY };
    }
    weights = weights.map((row, i) => row.map((value, j) => value - scale * gradient[i][j]));
    bias = { x: bias.x - scale * biasGradient.x, y: bias.y - scale * biasGradient.y };
  }

  return frames;
}

function captionFor(epoch: number, epochs: number): string {
  if (epoch === 0) {
    return "Untrained. The predictor sends every context embedding to roughly the same place, so it sits far from the target encoder's points.";
  }
  if (epoch < epochs * 0.25) {
    return "Early steps. The predictor is learning a direction in latent space while the target encoder is still drifting toward the future embeddings.";
  }
  if (epoch < epochs * 0.7) {
    return "The gap the loss measures is a distance between embeddings. No raw customer count is reconstructed at any point.";
  }
  return "Converged. Predicted and target embeddings coincide; a separate decoder is what turns an embedding back into a count trajectory.";
}
