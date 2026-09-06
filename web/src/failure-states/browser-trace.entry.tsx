import { useState } from "react";
import { mountFailureStateHarness } from "./browser-harness";
import { FailureState } from "./FailureState";
import type { FailureStateInput } from "./types";

const states: readonly FailureStateInput[] = [
  { kind: "network_failure", message: "Offline. No source result was created.", retainedContext: <p>Retained scene: Minnesota overview</p> },
  { kind: "malformed", message: "The source response was malformed; detail was withheld.", retainedContext: <p>Retained scene: Minnesota overview</p> },
  { kind: "version_mismatch", message: "The source uses an incompatible API version.", retainedContext: <p>Retained scene: Minnesota overview</p> },
  { kind: "cancelled", retainedContext: <p>Retained scene: Minnesota overview</p> },
  { kind: "partial", message: "Only the source-provided portion is available.", retainedContext: <p>Retained scene: Minnesota overview</p> },
];

function Trace() {
  const [index, setIndex] = useState(0);
  const [retries, setRetries] = useState(0);
  const [reset, setReset] = useState(false);
  const state = states[index];
  return <main data-retries={retries} data-reset={reset ? "called" : "not-called"}>
    <button type="button" onClick={() => setIndex((value) => (value + 1) % states.length)}>Next state</button>
    <FailureState state={state} onRetry={() => setRetries((value) => value + 1)} onReset={() => setReset(true)} />
  </main>;
}

mountFailureStateHarness(document.getElementById("root")!, <Trace />);
