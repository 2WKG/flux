import { useId, type ChangeEvent, type CSSProperties } from "react";

/**
 * The immutable edit vocabulary from `twin.contracts.GridEdit`.
 *
 * The order of these values is part of a scenario identity: a parent must send
 * the array exactly as emitted here and use the returned edit hash as the
 * server's identity for that sequence.
 */
export type GridEdit =
  | Readonly<{ kind: "outage"; element_id: string }>
  | Readonly<{ kind: "remove"; element_id: string }>
  | Readonly<{ kind: "add_gen"; element_id: string; bus_id: number; p_mw: number; pmax_mw: number }>
  | Readonly<{ kind: "add_load"; element_id: string; bus_id: number; p_mw: number }>
  | Readonly<{
      kind: "add_line";
      element_id: string;
      from_bus_id: number;
      to_bus_id: number;
      r_pu: number;
      x_pu: number;
      rate_a_mw: number;
      base_kv: number;
      length_km: number;
    }>;

export type GridEditKind = GridEdit["kind"];

/** A verdict is copied from the edit service. The browser does not derive one. */
export interface ServerFeasibilityVerdict {
  readonly verdict: "valid" | "invalid" | "unknown";
  readonly reason: string;
  /** The zero-based operation index supplied by the server when available. */
  readonly op_index?: number;
  /** The server may distinguish a fast screen from a later solve. */
  readonly stage?: string;
}

export type ScenarioEditServerState =
  | Readonly<{ kind: "loading" }>
  | Readonly<{ kind: "unavailable"; reason?: string }>
  | Readonly<{ kind: "error"; reason: string }>
  | Readonly<{
      kind: "ready";
      edit_hash?: string;
      feasibility: readonly ServerFeasibilityVerdict[];
    }>;

export interface ScenarioEditPanelProps {
  readonly baseScenarioId: string;
  readonly onBaseScenarioIdChange?: (baseScenarioId: string) => void;
  readonly ops: readonly GridEdit[];
  /** Receives a fresh ordered array; this panel never mutates a caller's edit. */
  readonly onOpsChange?: (ops: readonly GridEdit[]) => void;
  /**
   * Fixture-only for now. A future parent may populate this from
   * POST /scenario/edit {base_scenario_id, ops[]}.
   */
  readonly serverState: ScenarioEditServerState;
  readonly heading?: string;
}

const kindCopy: Record<GridEditKind, string> = {
  outage: "Outage",
  remove: "Remove existing element",
  add_gen: "Add producer",
  add_load: "Add consumer",
  add_line: "Add transmission",
};

const verdictCopy: Record<ServerFeasibilityVerdict["verdict"], string> = {
  valid: "Server: valid",
  invalid: "Server: invalid",
  unknown: "Server: unknown",
};

/** Returns an editable illustrative operation without judging whether it is feasible. */
export function blankGridEdit(kind: GridEditKind): GridEdit {
  switch (kind) {
    case "outage":
    case "remove":
      return { kind, element_id: "" };
    case "add_gen":
      return { kind, element_id: "", bus_id: 0, p_mw: 0, pmax_mw: 0 };
    case "add_load":
      return { kind, element_id: "", bus_id: 0, p_mw: 0 };
    case "add_line":
      return {
        kind,
        element_id: "",
        from_bus_id: 0,
        to_bus_id: 0,
        r_pu: 0,
        x_pu: 0,
        rate_a_mw: 0,
        base_kv: 0,
        length_km: 1,
      };
  }
}

/** Add an operation without mutating or sorting the ordered edit sequence. */
export function insertGridEdit(
  ops: readonly GridEdit[],
  kind: GridEditKind,
  index: number = ops.length,
): readonly GridEdit[] {
  const position = Math.max(0, Math.min(index, ops.length));
  return [...ops.slice(0, position), blankGridEdit(kind), ...ops.slice(position)];
}

/** Replace one operation without mutating the caller's ordered sequence. */
export function replaceGridEdit(
  ops: readonly GridEdit[],
  index: number,
  edit: GridEdit,
): readonly GridEdit[] {
  if (index < 0 || index >= ops.length) return ops;
  return ops.map((item, itemIndex) => itemIndex === index ? edit : item);
}

/** Remove one operation without changing the remaining relative order. */
export function removeGridEdit(ops: readonly GridEdit[], index: number): readonly GridEdit[] {
  if (index < 0 || index >= ops.length) return ops;
  return [...ops.slice(0, index), ...ops.slice(index + 1)];
}

/** Move an operation while preserving the order of every other operation. */
export function moveGridEdit(ops: readonly GridEdit[], index: number, destination: number): readonly GridEdit[] {
  if (index < 0 || index >= ops.length || destination < 0 || destination >= ops.length || index === destination) return ops;
  const next = [...ops];
  const [edit] = next.splice(index, 1);
  next.splice(destination, 0, edit);
  return next;
}

function numberValue(event: ChangeEvent<HTMLInputElement>): number {
  return Number(event.currentTarget.value);
}

function textInput(
  label: string,
  value: string,
  onChange: (value: string) => void,
  key: string,
) {
  return <label key={key} style={styles.field}><span>{label}</span><input value={value} onChange={(event) => onChange(event.currentTarget.value)} /></label>;
}

function numberInput(
  label: string,
  value: number,
  onChange: (value: number) => void,
  key: string,
) {
  return <label key={key} style={styles.field}><span>{label}</span><input type="number" value={Number.isNaN(value) ? "" : value} onChange={(event) => onChange(numberValue(event))} /></label>;
}

function EditFields({ edit, onChange }: { edit: GridEdit; onChange: (edit: GridEdit) => void }) {
  const update = (patch: Partial<GridEdit>) => onChange({ ...edit, ...patch } as GridEdit);
  const fields = [textInput("Element ID", edit.element_id, (element_id) => update({ element_id }), "element_id")];
  if (edit.kind === "outage" || edit.kind === "remove") return <div style={styles.fields}>{fields}</div>;

  if (edit.kind === "add_gen") {
    fields.push(
      numberInput("Bus ID", edit.bus_id, (bus_id) => update({ bus_id }), "bus_id"),
      numberInput("Scheduled MW", edit.p_mw, (p_mw) => update({ p_mw }), "p_mw"),
      numberInput("Maximum MW", edit.pmax_mw, (pmax_mw) => update({ pmax_mw }), "pmax_mw"),
    );
  }
  if (edit.kind === "add_load") {
    fields.push(
      numberInput("Bus ID", edit.bus_id, (bus_id) => update({ bus_id }), "bus_id"),
      numberInput("Demand MW", edit.p_mw, (p_mw) => update({ p_mw }), "p_mw"),
    );
  }
  if (edit.kind === "add_line") {
    fields.push(
      numberInput("From bus ID", edit.from_bus_id, (from_bus_id) => update({ from_bus_id }), "from_bus_id"),
      numberInput("To bus ID", edit.to_bus_id, (to_bus_id) => update({ to_bus_id }), "to_bus_id"),
      numberInput("Resistance (p.u.)", edit.r_pu, (r_pu) => update({ r_pu }), "r_pu"),
      numberInput("Reactance (p.u.)", edit.x_pu, (x_pu) => update({ x_pu }), "x_pu"),
      numberInput("Rating (MW)", edit.rate_a_mw, (rate_a_mw) => update({ rate_a_mw }), "rate_a_mw"),
      numberInput("Base voltage (kV)", edit.base_kv, (base_kv) => update({ base_kv }), "base_kv"),
      numberInput("Length (km)", edit.length_km, (length_km) => update({ length_km }), "length_km"),
    );
  }
  return <div style={styles.fields}>{fields}</div>;
}

function ServerResult({ state }: { state: ScenarioEditServerState }) {
  if (state.kind === "loading") return <section aria-label="Scenario edit server state" data-scenario-edit-state="loading" role="status" style={styles.server}><strong>Checking the server</strong><p>Waiting for a server feasibility response. The browser has not evaluated this edit.</p></section>;
  if (state.kind === "unavailable") return <section aria-label="Scenario edit server state" data-scenario-edit-state="unavailable" role="alert" style={styles.server}><strong>Scenario editing unavailable</strong><p>{state.reason ?? "No stable scenario edit endpoint is mounted, so no feasibility verdict is available."}</p></section>;
  if (state.kind === "error") return <section aria-label="Scenario edit server state" data-scenario-edit-state="error" role="alert" style={styles.server}><strong>Scenario edit request failed</strong><p>{state.reason}</p></section>;
  return <section aria-label="Scenario edit server result" data-scenario-edit-state="ready" style={styles.server}>
    <strong>Server feasibility result</strong>
    <p>Edit hash: <code>{state.edit_hash ?? "Unavailable"}</code></p>
    {state.feasibility.length === 0 ? <p>No feasibility rows were returned by the server.</p> : <ol style={styles.verdicts}>
      {state.feasibility.map((verdict, index) => <li key={`${verdict.op_index ?? index}-${verdict.reason}`} data-feasibility-verdict={verdict.verdict}>
        <strong>{verdictCopy[verdict.verdict]}</strong>{verdict.op_index !== undefined ? ` · operation ${verdict.op_index + 1}` : ""}{verdict.stage ? ` · ${verdict.stage}` : ""}
        <p>{verdict.reason}</p>
      </li>)}
    </ol>}
  </section>;
}

/**
 * Controlled, fixture-ready edit composer. It deliberately has no fetch, URL,
 * geometry, or feasibility implementation; a mounted parent owns all of those
 * integrations and forwards only server facts through `serverState`.
 */
export function ScenarioEditPanel({
  baseScenarioId,
  onBaseScenarioIdChange,
  ops,
  onOpsChange,
  serverState,
  heading = "Illustrative scenario edits",
}: ScenarioEditPanelProps) {
  const headingId = useId();
  const changeOps = (next: readonly GridEdit[]) => onOpsChange?.(next);

  return <section aria-labelledby={headingId} data-scenario-edit-panel="illustrative" style={styles.panel}>
    <header>
      <p style={styles.kicker}>Illustrative edits only</p>
      <h2 id={headingId}>{heading}</h2>
      <p>User-created producers, consumers, and transmission are illustrative. Feasibility comes only from the server; this panel does not calculate it.</p>
    </header>

    <label style={styles.field}><span>Base scenario ID</span><input value={baseScenarioId} onChange={(event) => onBaseScenarioIdChange?.(event.currentTarget.value)} /></label>
    <section aria-label="Ordered scenario operations" style={styles.operations}>
      <h3>Ordered operations</h3>
      <p>Order is preserved when the parent submits the future <code>POST /scenario/edit</code> request.</p>
      {ops.length === 0 ? <p>No illustrative edits yet.</p> : <ol style={styles.operationList}>
        {ops.map((edit, index) => <li key={`${index}-${edit.kind}-${edit.element_id}`} data-grid-edit-kind={edit.kind} style={styles.operation}>
          <div style={styles.operationHeader}><strong>{index + 1}. {kindCopy[edit.kind]}</strong><span data-truth-label="illustrative" style={styles.illustrative}>Illustrative</span></div>
          <EditFields edit={edit} onChange={(next) => changeOps(replaceGridEdit(ops, index, next))} />
          <div style={styles.actions}>
            <button type="button" onClick={() => changeOps(moveGridEdit(ops, index, index - 1))} disabled={index === 0}>Move earlier</button>
            <button type="button" onClick={() => changeOps(moveGridEdit(ops, index, index + 1))} disabled={index === ops.length - 1}>Move later</button>
            <button type="button" onClick={() => changeOps(removeGridEdit(ops, index))}>Remove operation</button>
          </div>
        </li>)}
      </ol>}
      <div aria-label="Add an illustrative operation" style={styles.actions}>
        {(Object.keys(kindCopy) as GridEditKind[]).map((kind) => <button key={kind} type="button" onClick={() => changeOps(insertGridEdit(ops, kind))}>Add {kindCopy[kind]}</button>)}
      </div>
    </section>
    <ServerResult state={serverState} />
  </section>;
}

const styles: Record<string, CSSProperties> = {
  panel: { display: "grid", gap: "1rem", maxWidth: "56rem" },
  kicker: { margin: 0, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em" },
  field: { display: "grid", gap: "0.25rem", minWidth: "10rem" },
  operations: { display: "grid", gap: "0.75rem" },
  operationList: { display: "grid", gap: "0.75rem", margin: 0, paddingLeft: "1.5rem" },
  operation: { display: "grid", gap: "0.75rem", padding: "0.75rem", border: "1px solid currentColor" },
  operationHeader: { display: "flex", justifyContent: "space-between", gap: "0.75rem", alignItems: "center" },
  illustrative: { fontSize: "0.8rem", fontWeight: 700 },
  fields: { display: "flex", flexWrap: "wrap", gap: "0.75rem" },
  actions: { display: "flex", flexWrap: "wrap", gap: "0.5rem" },
  server: { display: "grid", gap: "0.25rem", padding: "0.75rem", border: "1px solid currentColor" },
  verdicts: { display: "grid", gap: "0.5rem", margin: 0, paddingLeft: "1.5rem" },
};
