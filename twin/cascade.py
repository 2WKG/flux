"""Deterministic DC cascade simulation for the synthetic ACTIVSg2000 network."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb
import networkx as nx
import pandapower as pp

from twin.build import cached_base_network
from twin.contracts import (
    SYNTHETIC_TOPOLOGY_LABEL,
    CascadeEvent,
    CascadeResult,
    PlacementResult,
    SimulationCancelledError,
    SimulationInputError,
    SimulationSolveError,
    SimulationUnavailableError,
)


def run_cascade(
    element_ids: list[str],
    scenario_id: str,
    hour: int,
    *,
    net: Any | None = None,
    case_path: str | Path | None = None,
    db_path: str | Path | None = None,
    write: bool = False,
    seed: int = 0,
    overload_limit_pct: float = 100.0,
    max_stages: int = 12,
    unit_mw: float | None = None,
    site_bus: int | None = None,
    counterfactual_site_id: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Apply outages, solve with ``rundcpp``, and trip overloads to stability.

    ``element_ids`` accepts contract line IDs (``"42"`` or ``"line:42"``),
    plus explicit ``impedance:``, ``generator:``/``gen:``, and ``load:`` ids.
    The supplied network is deep-copied before every edit, so scenario reruns
    never mutate a shared baseline.  ``write=True`` persists the same row shape
    read by the existing copilot cascade route; a missing database is explicit.
    """
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise SimulationInputError("scenario_id must be a non-empty string")
    if isinstance(hour, bool) or not isinstance(hour, int) or hour < 0:
        raise SimulationInputError("hour must be a non-negative integer")
    if overload_limit_pct <= 0 or max_stages <= 0:
        raise SimulationInputError("overload_limit_pct and max_stages must be positive")
    _check_cancel(cancel_check)
    if net is None:
        net = cached_base_network(
            case_path, db_path=db_path if db_path is not None else None
        )
    scenario_net = copy.deepcopy(net)
    _ensure_element_ids(scenario_net)
    if unit_mw is not None or site_bus is not None:
        if unit_mw is None or site_bus is None:
            raise SimulationInputError("unit_mw and site_bus must be supplied together")
        add_unit(scenario_net, bus_id=site_bus, unit_mw=unit_mw)

    canonical_forced = _canonical_forced_elements(scenario_net, element_ids)
    events, lost_load_mw, dark_buses = _apply_forced_outages(
        scenario_net, canonical_forced
    )
    metadata = (
        _metadata_from_database(db_path, scenario_net)
        if db_path is not None
        else ({}, {})
    )
    county_by_bus, critical_by_bus = metadata
    loading_by_element: dict[str, float] = {}
    for stage in range(1, max_stages + 1):
        _check_cancel(cancel_check)
        island_lost, island_buses, island_events = _island_load_loss(
            scenario_net, stage
        )
        lost_load_mw += island_lost
        dark_buses.update(island_buses)
        events.extend(island_events)
        _solve(scenario_net)
        overloads = _overloaded_elements(scenario_net, overload_limit_pct)
        loading_by_element.update(
            {element_id: loading for element_id, _, _, loading in overloads}
        )
        if not overloads:
            break
        for element_id, table, index, loading in overloads:
            scenario_net[table].at[index, "in_service"] = False
            events.append(
                CascadeEvent(
                    element_id=element_id,
                    kind="line" if table == "line" else "impedance",
                    stage=stage,
                    cause="overload",
                    loading_percent=round(float(loading), 6),
                )
            )
    else:
        raise SimulationSolveError(
            f"cascade did not stabilize after {max_stages} stages; increase max_stages explicitly"
        )

    county_impacts = _county_impacts(scenario_net, county_by_bus)
    counties_dark = tuple(
        impact["county_fips"]
        for impact in county_impacts
        if impact["fraction_dark"] >= 1.0
    )
    critical_lost = tuple(
        sorted(
            critical_id
            for bus in dark_buses
            for critical_id in critical_by_bus.get(bus, ())
        )
    )
    forced_key = tuple(event.element_id for event in events if event.cause == "forced")
    if write and (
        overload_limit_pct != 100.0
        or max_stages != 12
        or unit_mw is not None
        or site_bus is not None
    ):
        raise SimulationInputError(
            "persistence of non-default solver settings or unit counterfactuals requires an explicit counterfactual workflow"
        )
    identity = scenario_identity(
        forced_key,
        scenario_id,
        hour,
        seed=seed,
        unit_mw=unit_mw,
        site_bus=site_bus,
        net=scenario_net,
        overload_limit_pct=overload_limit_pct,
        max_stages=max_stages,
    )
    result = CascadeResult(
        run_id=make_run_id(
            scenario_id,
            seed,
            forced_key,
            counterfactual_site_id,
            unit_mw,
            scenario_hash=str(identity["scenario_hash"]),
        ),
        scenario_id=scenario_id,
        hour=hour,
        tripped_element_ids=tuple(events),
        lost_load_mw=round(float(lost_load_mw), 6),
        counties_dark=counties_dark,
        critical_loads_lost=critical_lost,
        topology=str(scenario_net.get("flux_topology", SYNTHETIC_TOPOLOGY_LABEL)),
        loading_by_element=loading_by_element,
        county_impacts=tuple(county_impacts),
        scenario_identity={"version": "v1", **identity},
    )
    if write:
        _check_cancel(cancel_check)
        if db_path is None:
            raise SimulationUnavailableError(
                "write=True requires a cascade_runs database path"
            )
        persist_result(result, db_path, counterfactual_site_id=counterfactual_site_id)
    return result.json()


def scenario_identity(
    element_ids: Sequence[str],
    scenario_id: str,
    hour: int,
    *,
    seed: int = 0,
    unit_mw: float | None = None,
    site_bus: int | None = None,
    net: Any | None = None,
    overload_limit_pct: float = 100.0,
    max_stages: int = 12,
    case_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return one canonical immutable identity for a synthetic scenario edit."""
    if not scenario_id or hour < 0:
        raise SimulationInputError("scenario_id and non-negative hour are required")
    resolved_case = Path(case_path) if case_path is not None else None
    if resolved_case is None and net is not None and net.get("flux_case_path"):
        resolved_case = Path(str(net["flux_case_path"]))
    case_sha256 = None
    if resolved_case is not None and resolved_case.is_file():
        with resolved_case.open("rb") as case_file:
            case_sha256 = hashlib.file_digest(case_file, "sha256").hexdigest()
    canonical = {
        "scenario_id": str(scenario_id),
        "hour": int(hour),
        "seed": int(seed),
        "element_ids": (
            _canonical_forced_elements(net, element_ids)
            if net is not None
            else sorted(
                {
                    f"line:{str(element_id).strip()}"
                    if ":" not in str(element_id)
                    else str(element_id).strip()
                    for element_id in element_ids
                }
            )
        ),
        "unit_mw": None if unit_mw is None else float(unit_mw),
        "site_bus": site_bus,
        "overload_limit_pct": float(overload_limit_pct),
        "max_stages": int(max_stages),
        "case_sha256": case_sha256,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return {
        **canonical,
        "scenario_hash": hashlib.sha256(encoded.encode()).hexdigest()[:16],
    }


def immutable_scenario_net(
    net: Any,
    element_ids: Sequence[str],
    *,
    unit_mw: float | None = None,
    site_bus: int | None = None,
) -> Any:
    """Build an independently editable synthetic scenario network.

    The caller owns the returned copy.  The original baseline is never edited.
    This function is intentionally topology-only and cannot attach a physical
    facility to the synthetic graph.
    """
    scenario_net = copy.deepcopy(net)
    _ensure_element_ids(scenario_net)
    _apply_forced_outages(scenario_net, element_ids)
    if unit_mw is not None or site_bus is not None:
        if unit_mw is None or site_bus is None:
            raise SimulationInputError("unit_mw and site_bus must be supplied together")
        add_unit(scenario_net, bus_id=site_bus, unit_mw=unit_mw)
    return scenario_net


def feasibility_report(net: Any) -> dict[str, Any]:
    """Report DC connectivity/solve feasibility without claiming OPF or stability."""
    candidate = copy.deepcopy(net)
    _ensure_element_ids(candidate)
    graph = _in_service_graph(candidate)
    source_buses = _source_buses(candidate)
    islands: list[dict[str, Any]] = []
    for component in nx.connected_components(graph):
        component_load = float(
            candidate.load[
                candidate.load.in_service & candidate.load.bus.isin(component)
            ].p_mw.sum()
        )
        component_gen = float(
            candidate.gen[
                candidate.gen.in_service & candidate.gen.bus.isin(component)
            ].max_p_mw.sum()
        )
        has_slack = bool(source_buses.intersection(component))
        islands.append(
            {
                "bus_count": len(component),
                "load_mw": round(component_load, 6),
                "available_gen_mw": round(component_gen, 6),
                "has_source": has_slack,
                "unsupplied_load_mw": round(
                    component_load if not has_slack else 0.0, 6
                ),
            }
        )
    try:
        _solve(candidate)
        solve_status = "solved"
    except SimulationSolveError as exc:
        solve_status = "solver_failed"
        solve_error = str(exc)
    else:
        solve_error = None
    unsupplied = round(sum(item["unsupplied_load_mw"] for item in islands), 6)
    return {
        "status": solve_status,
        "dc_solve_converged": solve_status == "solved",
        "unsupplied_load_mw": unsupplied,
        "islands": islands,
        "limitations": [
            "DC power-flow feasibility only; no AC voltage, transient-stability, protection, or OPF claim.",
            "All topology is synthetic (ACTIVSg2000).",
        ],
        **({"solve_error": solve_error} if solve_error is not None else {}),
    }


def balance_report(net: Any) -> dict[str, Any]:
    """Measure solved DC generation, slack, and load rather than inventing balance."""
    candidate = copy.deepcopy(net)
    _ensure_element_ids(candidate)
    _solve(candidate)
    generation = (
        float(candidate.res_gen.p_mw.sum()) if not candidate.res_gen.empty else 0.0
    )
    generation += (
        float(candidate.res_sgen.p_mw.sum()) if not candidate.res_sgen.empty else 0.0
    )
    slack = (
        float(candidate.res_ext_grid.p_mw.sum())
        if not candidate.res_ext_grid.empty
        else 0.0
    )
    load = float(candidate.res_load.p_mw.sum()) if not candidate.res_load.empty else 0.0
    return {
        "generation_mw": round(generation, 6),
        "slack_mw": round(slack, 6),
        "served_load_mw": round(load, 6),
        "dc_balance_residual_mw": round(generation + slack - load, 6),
        "topology": SYNTHETIC_TOPOLOGY_LABEL,
        "dispatch_assumption": "existing in-service generator dispatch; add_unit displaces it pro-rata before DC slack balancing",
        "limitations": [
            "DC balance is not economic dispatch or a unit-commitment/OPF result.",
            f"All topology is {SYNTHETIC_TOPOLOGY_LABEL}.",
        ],
    }


def redundancy_report(
    net: Any, candidate_bus_ids: Iterable[int]
) -> list[dict[str, Any]]:
    """Measure synthetic source reachability and incident solved flow for buses."""
    candidate = copy.deepcopy(net)
    _ensure_element_ids(candidate)
    _solve(candidate)
    graph = _in_service_graph(candidate)
    sources = _source_buses(candidate)
    report: list[dict[str, Any]] = []
    for raw_bus in candidate_bus_ids:
        bus_id = int(raw_bus)
        if bus_id not in graph:
            raise SimulationInputError(
                f"candidate bus {bus_id} is absent from the synthetic network"
            )
        source_hops = min(
            (
                nx.shortest_path_length(graph, bus_id, source)
                for source in sources
                if nx.has_path(graph, bus_id, source)
            ),
            default=None,
        )
        incident_flow = _incident_flow_mw(candidate, bus_id)
        report.append(
            {
                "bus_id": bus_id,
                "in_service_incident_elements": _incident_element_count(
                    candidate, bus_id
                ),
                "source_hops": source_hops,
                "incident_abs_flow_mw": round(incident_flow, 6),
                "topology": SYNTHETIC_TOPOLOGY_LABEL,
                "limitations": "connectivity and DC flow exposure in synthetic topology; not a physical interconnection claim",
            }
        )
    return sorted(
        report,
        key=lambda row: (
            row["source_hops"] is None,
            row["source_hops"] or 0,
            -row["in_service_incident_elements"],
            row["bus_id"],
        ),
    )


def placement_counterfactual(
    element_ids: list[str],
    scenario_id: str,
    hour: int,
    *,
    net: Any,
    site_bus: int,
    unit_mw: float,
    seed: int = 0,
) -> dict[str, Any]:
    """Compare measured baseline and synthetic-unit cascade reruns at one bus."""
    baseline = run_cascade(
        element_ids, scenario_id, hour, net=net, seed=seed, write=False
    )
    with_unit = run_cascade(
        element_ids,
        scenario_id,
        hour,
        net=net,
        seed=seed,
        unit_mw=unit_mw,
        site_bus=site_bus,
        write=False,
    )
    return {
        "site_bus": site_bus,
        "unit_mw": float(unit_mw),
        "baseline": baseline,
        "with_synthetic_unit": with_unit,
        "measured_delta": {
            "lost_load_reduction_mw": round(
                float(baseline["lost_load_mw"]) - float(with_unit["lost_load_mw"]), 6
            ),
            "tripped_event_reduction": len(baseline["tripped_element_ids"])
            - len(with_unit["tripped_element_ids"]),
        },
        "limitations": [
            "Counterfactual is a synthetic generator injection on ACTIVSg2000, not a physical siting or interconnection result.",
            "DC power flow only; no AC voltage, transient stability, unit commitment, or regulatory suitability score.",
        ],
    }


def make_run_id(
    scenario_id: str,
    seed: int,
    forced_out: Sequence[str],
    counterfactual_site_id: int | None = None,
    unit_mw: float | None = None,
    scenario_hash: str | None = None,
) -> str:
    """Build the shared deterministic baseline/counterfactual run identity."""
    digest = (
        scenario_hash[:8]
        if scenario_hash is not None
        else hashlib.sha256("\x1f".join(sorted(forced_out)).encode()).hexdigest()[:8]
    )
    if counterfactual_site_id is not None:
        if unit_mw is None:
            raise SimulationInputError("counterfactual run_id requires unit_mw")
        return f"{scenario_id}-s{seed}-cf-{counterfactual_site_id}-{_number_token(unit_mw)}"
    return f"{scenario_id}-s{seed}-{digest}"


def add_unit(net: Any, *, bus_id: int, unit_mw: float) -> int:
    """Add synthetic firm generation and pro-rata displace existing dispatch."""
    if bus_id not in net.bus.index:
        raise SimulationInputError(
            f"site bus {bus_id} is absent from the synthetic network"
        )
    if unit_mw <= 0:
        raise SimulationInputError("unit_mw must be positive")
    active = net.gen.index[net.gen.in_service]
    existing = float(net.gen.loc[active, "p_mw"].sum())
    if existing <= 0:
        raise SimulationInputError(
            "cannot displace generation: no in-service generators"
        )
    displacement = min(float(unit_mw), existing)
    net.gen.loc[active, "p_mw"] *= (existing - displacement) / existing
    index = pp.create_gen(
        net,
        bus=bus_id,
        p_mw=float(unit_mw),
        vm_pu=1.0,
        max_p_mw=float(unit_mw),
        min_p_mw=0.3 * float(unit_mw),
        name=f"synthetic-unit:{bus_id}",
    )
    net.gen.at[index, "flux_element_id"] = f"generator:site:{bus_id}"
    return int(index)


def rank_candidate_placements(
    net: Any,
    candidate_bus_ids: Iterable[int],
    *,
    max_hops: int = 3,
) -> list[dict[str, Any]]:
    """Rank synthetic buses by local redundancy and reachable synthetic load.

    This is a topology heuristic for site screening.  It intentionally returns
    no connection claim for a real facility or public inventory asset.
    """
    if max_hops < 1:
        raise SimulationInputError("max_hops must be at least one")
    graph = _in_service_graph(net)
    load_by_bus = net.load[net.load.in_service].groupby("bus").p_mw.sum().to_dict()
    results: list[PlacementResult] = []
    for raw_bus_id in candidate_bus_ids:
        bus_id = int(raw_bus_id)
        if bus_id not in graph:
            raise SimulationInputError(
                f"candidate bus {bus_id} is absent from the synthetic network"
            )
        reached = nx.single_source_shortest_path_length(graph, bus_id, cutoff=max_hops)
        reachable_load = sum(float(load_by_bus.get(bus, 0.0)) for bus in reached)
        results.append(
            PlacementResult(
                bus_id=bus_id,
                redundancy=int(graph.degree(bus_id)),
                reachable_load_mw=round(reachable_load, 6),
            )
        )
    return [
        result.json()
        for result in sorted(
            results,
            key=lambda row: (-row.redundancy, -row.reachable_load_mw, row.bus_id),
        )
    ]


def texas_stress_preset(
    scenario_id: str,
    hour: int,
    *,
    net: Any | None = None,
    case_path: str | Path | None = None,
    db_path: str | Path | None = None,
    force_count: int = 8,
) -> dict[str, Any]:
    """Build an auditable N-k synthetic Texas stress preset from solved flows.

    The forced set comprises the user-selected number of highest loaded actual
    in-service lines under the model's normal ratings, plus the largest
    currently radial synthetic load tie when one exists.  It is a deliberately
    severe synthetic contingency, not a weather observation or physical-grid
    outage claim.  Every later stage comes from ``rundcpp`` and the normal
    overload limit; this helper never invents visual threshold events.
    """
    if force_count < 1:
        raise SimulationInputError("force_count must be at least one")
    base_net = (
        cached_base_network(case_path, db_path=db_path)
        if net is None
        else copy.deepcopy(net)
    )
    _ensure_element_ids(base_net)
    _solve(base_net)
    top_lines = sorted(
        (
            (float(loading), str(base_net.line.at[index, "flux_element_id"]))
            for index, loading in base_net.res_line.loading_percent.items()
            if bool(base_net.line.at[index, "in_service"])
        ),
        key=lambda row: (-row[0], row[1]),
    )[:force_count]
    if not top_lines:
        raise SimulationUnavailableError(
            "synthetic network has no in-service lines to form a stress preset"
        )
    radial = _largest_radial_load_tie(base_net)
    forced = [element_id for _, element_id in top_lines]
    if radial is not None and radial[0] not in forced:
        forced.append(radial[0])
    cascade = run_cascade(
        forced, scenario_id, hour, net=base_net, db_path=db_path, write=False
    )
    return {
        "preset_id": f"synthetic_texas_n{len(forced)}_stress",
        "topology": SYNTHETIC_TOPOLOGY_LABEL,
        "source_kind": "simulated",
        "scenario_id": scenario_id,
        "hour": hour,
        "forced_element_ids": forced,
        "selection": {
            "method": "highest baseline DC line loading under normal ratings plus largest radial synthetic load tie",
            "baseline_line_loading_percent": [
                {"element_id": element_id, "loading_percent": round(loading, 6)}
                for loading, element_id in top_lines
            ],
            "radial_load_tie": (
                {"element_id": radial[0], "isolated_synthetic_load_mw": radial[1]}
                if radial is not None
                else None
            ),
        },
        "timeline": cascade["tripped_element_ids"],
        "cascade": cascade,
    }


def control_room_payload(
    result: Mapping[str, Any], db_path: str | Path
) -> dict[str, Any]:
    """Package provenance and an honest playback qualification for a run.

    This keeps the UI bridge read-only.  A run qualifies only after its exact
    synthetic ``cascade_runs`` row has been persisted and the current MATPOWER,
    current AUX, scenario, and weather-run receipts are all present in the DB.
    """
    for key in ("run_id", "scenario_id", "hour", "topology"):
        if key not in result:
            raise SimulationInputError(f"result is missing {key}")
    path = Path(db_path)
    if not path.is_file():
        raise SimulationUnavailableError(
            f"control-room database is unavailable: {path}"
        )
    con = duckdb.connect(str(path), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        missing_tables = {
            "ingest_log",
            "scenarios",
            "weather_source_runs",
            "cascade_runs",
        } - tables
        if missing_tables:
            return _unqualified_payload(
                result, f"missing tables: {', '.join(sorted(missing_tables))}"
            )
        artifacts = {
            source_file: sha256
            for source_file, sha256 in con.execute(
                "SELECT source_file, sha256 FROM ingest_log "
                "WHERE source = 'activsg2000' AND source_release = 'current' "
                "AND source_file IN ('case_ACTIVSg2000.m', 'ACTIVSg2000.aux')"
            ).fetchall()
        }
        scenario = con.execute(
            "SELECT source_name, source_ref, source_version FROM scenarios WHERE scenario_id = ?",
            [result["scenario_id"]],
        ).fetchone()
        weather = con.execute(
            "SELECT source, source_release, receipt_path, grid_signature FROM weather_source_runs "
            "WHERE scenario_id = ? ORDER BY valid_ts LIMIT 1",
            [result["scenario_id"]],
        ).fetchone()
        persisted = con.execute(
            "SELECT source_name, source_ref, source_version, fixture_batch_id FROM cascade_runs "
            "WHERE run_id = ? AND hour = ?",
            [result["run_id"], result["hour"]],
        ).fetchone()
    finally:
        con.close()
    reasons: list[str] = []
    if set(artifacts) != {"case_ACTIVSg2000.m", "ACTIVSg2000.aux"}:
        reasons.append("current MATPOWER/AUX receipts are incomplete")
    if scenario is None:
        reasons.append("scenario is unavailable")
    if weather is None:
        reasons.append("weather source-run receipt is unavailable")
    if persisted is None:
        reasons.append("cascade result is not persisted")
    identity = result.get("scenario_identity")
    expected_identity = (
        f"scenario_identity=v1:{identity.get('scenario_hash')}"
        if isinstance(identity, Mapping) and identity.get("scenario_hash")
        else None
    )
    if (
        persisted is not None
        and expected_identity is not None
        and expected_identity not in str(persisted[1])
    ):
        reasons.append("persisted row lacks matching scenario identity proof")
    return {
        "run_id": result["run_id"],
        "scenario_id": result["scenario_id"],
        "hour": result["hour"],
        "topology": {
            "label": result["topology"],
            "source_kind": "simulated",
            "case": {
                "source_file": "case_ACTIVSg2000.m",
                "sha256": artifacts.get("case_ACTIVSg2000.m"),
            },
            "coordinates": {
                "source_file": "ACTIVSg2000.aux",
                "sha256": artifacts.get("ACTIVSg2000.aux"),
                "coord_source": "tamu_aux",
            },
        },
        "scenario_provenance": (
            {
                "source_name": scenario[0],
                "source_ref": scenario[1],
                "source_version": scenario[2],
            }
            if scenario is not None
            else None
        ),
        "weather_source_run": (
            {
                "source": weather[0],
                "source_release": weather[1],
                "receipt_path": weather[2],
                "grid_signature": weather[3],
            }
            if weather is not None
            else None
        ),
        "persisted_provenance": (
            {
                "source_name": persisted[0],
                "source_ref": persisted[1],
                "source_version": persisted[2],
                "fixture_batch_id": persisted[3],
                "scenario_identity": identity,
            }
            if persisted is not None
            else None
        ),
        "qualification": {"playback_qualified": not reasons, "reasons": reasons},
    }


def persist_result(
    result: CascadeResult,
    db_path: str | Path,
    *,
    counterfactual_site_id: int | None = None,
) -> None:
    """Persist an exact ``cascade_runs`` row, failing closed on schema drift."""
    path = Path(db_path)
    if not path.is_file():
        raise SimulationUnavailableError(f"cascade database is unavailable: {path}")
    con = duckdb.connect(str(path))
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if "cascade_runs" not in tables:
            raise SimulationUnavailableError(
                "cascade database has no cascade_runs table"
            )
        columns = {
            row[1]
            for row in con.execute("PRAGMA table_info('cascade_runs')").fetchall()
        }
        required = {
            "run_id",
            "scenario_id",
            "hour",
            "tripped_element_ids_json",
            "lost_load_mw",
            "counties_dark_json",
            "critical_loads_lost_json",
        }
        missing = sorted(required - columns)
        if missing:
            raise SimulationUnavailableError(
                "cascade_runs schema is missing required columns: " + ", ".join(missing)
            )
        values: dict[str, Any] = {
            "run_id": result.run_id,
            "scenario_id": result.scenario_id,
            "hour": result.hour,
            "tripped_element_ids_json": json.dumps(
                [event.json() for event in result.tripped_element_ids]
            ),
            "lost_load_mw": result.lost_load_mw,
            "counties_dark_json": json.dumps(list(result.counties_dark)),
            "critical_loads_lost_json": json.dumps(list(result.critical_loads_lost)),
            "counterfactual_site_id": counterfactual_site_id,
            "source_name": "twin.cascade",
            "source_ref": (
                "ACTIVSg2000 synthetic topology; "
                f"scenario_identity=v1:{result.scenario_identity.get('scenario_hash', 'unavailable')}"
            ),
            "source_version": "current",
            "source_retrieved_at": None,
            "fixture_batch_id": "synthetic-cascade",
        }
        selected = [column for column in values if column in columns]
        con.execute(
            "DELETE FROM cascade_runs WHERE run_id = ? AND hour = ?",
            [result.run_id, result.hour],
        )
        con.execute(
            f"INSERT INTO cascade_runs ({', '.join(selected)}) VALUES ({', '.join('?' for _ in selected)})",
            [values[column] for column in selected],
        )
    finally:
        con.close()


def _apply_forced_outages(
    net: Any, element_ids: Sequence[str]
) -> tuple[list[CascadeEvent], float, set[int]]:
    events: list[CascadeEvent] = []
    lost_load_mw = 0.0
    dark_buses: set[int] = set()
    seen: set[tuple[str, int]] = set()
    for raw_id in element_ids:
        table, index, element_id = _resolve_element(net, raw_id)
        marker = (table, index)
        if marker in seen:
            continue
        seen.add(marker)
        if not bool(net[table].at[index, "in_service"]):
            continue
        net[table].at[index, "in_service"] = False
        kind = {
            "line": "line",
            "impedance": "impedance",
            "gen": "generator",
            "sgen": "static_generator",
            "load": "load",
        }[table]
        events.append(
            CascadeEvent(element_id=element_id, kind=kind, stage=0, cause="forced")
        )
        if table == "load":
            lost_load_mw += float(net.load.at[index, "p_mw"])
            dark_buses.add(int(net.load.at[index, "bus"]))
    return events, lost_load_mw, dark_buses


def _canonical_forced_elements(net: Any, element_ids: Sequence[str]) -> list[str]:
    """Resolve aliases/deduplicate before edits so timeline and identity agree."""
    resolved: dict[tuple[str, int], str] = {}
    for raw_id in element_ids:
        table, index, element_id = _resolve_element(net, raw_id)
        resolved[(table, index)] = element_id
    return [
        element_id
        for _, element_id in sorted(resolved.items(), key=lambda item: item[1])
    ]


def _resolve_element(net: Any, raw_id: str) -> tuple[str, int, str]:
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise SimulationInputError("element_ids must contain non-empty strings")
    token = raw_id.strip()
    prefix, separator, value = token.partition(":")
    if not separator:
        prefix, value = "line", token
    normalized_prefix = prefix.lower()
    if normalized_prefix == "slack":
        matches = net.ext_grid.index[net.ext_grid.flux_element_id.astype(str) == token]
        if len(matches) == 1:
            raise SimulationInputError(
                "grid-forming slack outages are unsupported without an explicit replacement model"
            )
        raise SimulationInputError(f"unknown slack element id {raw_id!r}")
    if normalized_prefix == "generator":
        matches: list[tuple[str, int]] = []
        for provider_table in ("gen", "sgen"):
            frame = net[provider_table]
            if "flux_element_id" in frame:
                matches.extend(
                    (provider_table, int(index))
                    for index in frame.index[frame.flux_element_id.astype(str) == token]
                )
        if len(matches) == 1:
            table, index = matches[0]
            return table, index, str(net[table].at[index, "flux_element_id"])
        raise SimulationInputError(f"unknown generator source id {raw_id!r}")
    aliases = {
        "line": "line",
        "impedance": "impedance",
        "gen": "gen",
        "sgen": "sgen",
        "load": "load",
    }
    table = aliases.get(normalized_prefix)
    if table is None:
        raise SimulationInputError(f"unknown synthetic element kind in {raw_id!r}")
    expected = f"{prefix.lower()}:{value}"
    frame = net[table]
    if "flux_element_id" in frame:
        matches = frame.index[frame.flux_element_id.astype(str).isin({token, expected})]
        if len(matches) == 1:
            index = int(matches[0])
            return table, index, str(frame.at[index, "flux_element_id"])
    try:
        index = int(value) - 1
    except ValueError as exc:
        raise SimulationInputError(f"unknown {prefix} element id {raw_id!r}") from exc
    if index not in frame.index:
        raise SimulationInputError(f"unknown {prefix} element id {raw_id!r}")
    canonical = (
        str(frame.at[index, "flux_element_id"])
        if "flux_element_id" in frame
        else f"{prefix}:{index + 1}"
    )
    return table, index, canonical


def _ensure_element_ids(net: Any) -> None:
    for table, prefix in (
        ("line", "line"),
        ("impedance", "impedance"),
        ("gen", "generator"),
        ("sgen", "generator"),
        ("ext_grid", "slack"),
        ("load", "load"),
    ):
        if "flux_element_id" not in net[table]:
            net[table]["flux_element_id"] = [
                f"{prefix}:{int(index) + 1}" for index in net[table].index
            ]


def _solve(net: Any) -> None:
    try:
        pp.rundcpp(net)
    except Exception as exc:
        raise SimulationSolveError(f"pandapower.rundcpp failed: {exc}") from exc
    if not bool(net.converged):
        raise SimulationSolveError("pandapower.rundcpp did not converge")


def _overloaded_elements(net: Any, limit: float) -> list[tuple[str, str, int, float]]:
    overloaded: list[tuple[str, str, int, float]] = []
    if not net.res_line.empty:
        for index, value in net.res_line.loading_percent.items():
            if bool(net.line.at[index, "in_service"]) and float(value) > limit:
                overloaded.append(
                    (
                        str(net.line.at[index, "flux_element_id"]),
                        "line",
                        int(index),
                        float(value),
                    )
                )
    if not net.res_impedance.empty:
        for index, row in net.res_impedance.iterrows():
            if not bool(net.impedance.at[index, "in_service"]):
                continue
            rating = float(net.impedance.at[index, "sn_mva"])
            if rating <= 0:
                continue
            loading = (
                max(abs(float(row.p_from_mw)), abs(float(row.p_to_mw))) / rating * 100.0
            )
            if loading > limit:
                overloaded.append(
                    (
                        str(net.impedance.at[index, "flux_element_id"]),
                        "impedance",
                        int(index),
                        loading,
                    )
                )
    return sorted(overloaded, key=lambda value: value[0])


def _in_service_graph(net: Any) -> nx.Graph:
    graph = nx.Graph()
    graph.add_nodes_from(int(bus) for bus in net.bus.index[net.bus.in_service])
    for table in ("line", "impedance", "trafo"):
        if table not in net or net[table].empty:
            continue
        frame = net[table]
        for _, row in frame[frame.in_service].iterrows():
            first = "hv_bus" if table == "trafo" else "from_bus"
            second = "lv_bus" if table == "trafo" else "to_bus"
            graph.add_edge(int(row[first]), int(row[second]))
    return graph


def _source_buses(net: Any) -> set[int]:
    """Return only grid-forming sources for conservative island accounting.

    A normal ``gen`` is not a black-start/grid-forming resource.  Treating it
    as one would turn an isolated load island into a fabricated served-load
    claim.  Until a future model supplies explicit islanding controls and
    capacity/dispatch evidence, only an in-service pandapower ext-grid counts.
    """
    return {int(value) for value in net.ext_grid.loc[net.ext_grid.in_service, "bus"]}


def _incident_element_count(net: Any, bus_id: int) -> int:
    return sum(
        int(
            (
                (net[table].in_service)
                & ((net[table].from_bus == bus_id) | (net[table].to_bus == bus_id))
            ).sum()
        )
        for table in ("line", "impedance")
    )


def _incident_flow_mw(net: Any, bus_id: int) -> float:
    total = 0.0
    for table, result_table in (("line", "res_line"), ("impedance", "res_impedance")):
        frame, results = net[table], net[result_table]
        for index, row in frame[frame.in_service].iterrows():
            if int(row.from_bus) == bus_id:
                total += abs(float(results.at[index, "p_from_mw"]))
            elif int(row.to_bus) == bus_id:
                total += abs(float(results.at[index, "p_to_mw"]))
    return total


def _check_cancel(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise SimulationCancelledError("cascade cancelled before persistence")


def _largest_radial_load_tie(net: Any) -> tuple[str, float] | None:
    """Find the largest load behind one actual in-service synthetic branch."""
    sources = {int(value) for value in net.ext_grid.loc[net.ext_grid.in_service, "bus"]}
    sources.update(int(value) for value in net.gen.loc[net.gen.in_service, "bus"])
    load_by_bus = net.load[net.load.in_service].groupby("bus").p_mw.sum().to_dict()
    incident: dict[int, list[str]] = {}
    for table in ("line", "impedance"):
        for index, row in net[table][net[table].in_service].iterrows():
            element_id = str(net[table].at[index, "flux_element_id"])
            incident.setdefault(int(row.from_bus), []).append(element_id)
            incident.setdefault(int(row.to_bus), []).append(element_id)
    candidates = [
        (float(load_mw), bus_id, elements[0])
        for bus_id, load_mw in load_by_bus.items()
        if int(bus_id) not in sources
        and len(elements := incident.get(int(bus_id), [])) == 1
    ]
    if not candidates:
        return None
    load_mw, _, element_id = max(candidates, key=lambda item: (item[0], item[2]))
    return element_id, round(load_mw, 6)


def _island_load_loss(
    net: Any, stage: int
) -> tuple[float, set[int], list[CascadeEvent]]:
    graph = _in_service_graph(net)
    source_buses = _source_buses(net)
    lost_load_mw = 0.0
    dark_buses: set[int] = set()
    events: list[CascadeEvent] = []
    for component in nx.connected_components(graph):
        if source_buses.intersection(component):
            continue
        rows = net.load.index[net.load.in_service & net.load.bus.isin(component)]
        for index in rows:
            net.load.at[index, "in_service"] = False
            lost_load_mw += float(net.load.at[index, "p_mw"])
            bus = int(net.load.at[index, "bus"])
            dark_buses.add(bus)
            events.append(
                CascadeEvent(
                    element_id=str(net.load.at[index, "flux_element_id"]),
                    kind="load",
                    stage=stage,
                    cause="island",
                )
            )
    return lost_load_mw, dark_buses, events


def _metadata_from_database(
    db_path: str | Path, net: Any
) -> tuple[dict[int, str], dict[int, tuple[str, ...]]]:
    path = Path(db_path)
    if not path.is_file():
        raise SimulationUnavailableError(f"metadata database is unavailable: {path}")
    con = duckdb.connect(str(path), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        counties: dict[int, str] = {}
        critical: dict[int, tuple[str, ...]] = {}
        if "buses" in tables:
            columns = {
                row[1] for row in con.execute("PRAGMA table_info('buses')").fetchall()
            }
            if {"bus_id", "county_fips"}.issubset(columns):
                counties = {
                    int(bus_id): str(county_fips)
                    for bus_id, county_fips in con.execute(
                        "SELECT bus_id, county_fips FROM buses WHERE county_fips IS NOT NULL"
                    ).fetchall()
                }
        if "critical_loads" in tables:
            columns = {
                row[1]
                for row in con.execute("PRAGMA table_info('critical_loads')").fetchall()
            }
            if {"cl_id", "bus_id"}.issubset(columns):
                grouped: dict[int, list[str]] = {}
                for critical_id, bus_id in con.execute(
                    "SELECT cl_id, bus_id FROM critical_loads WHERE bus_id IS NOT NULL"
                ).fetchall():
                    grouped.setdefault(int(bus_id), []).append(str(critical_id))
                critical = {
                    bus: tuple(sorted(values)) for bus, values in grouped.items()
                }
        if "flux_source_bus_id" in net.bus:
            source_to_pandapower = {
                int(source_bus): int(pandapower_bus)
                for pandapower_bus, source_bus in net.bus.flux_source_bus_id.items()
            }
            counties = {
                source_to_pandapower[source_bus]: county
                for source_bus, county in counties.items()
                if source_bus in source_to_pandapower
            }
            critical = {
                source_to_pandapower[source_bus]: values
                for source_bus, values in critical.items()
                if source_bus in source_to_pandapower
            }
        return counties, critical
    finally:
        con.close()


def _county_impacts(net: Any, county_by_bus: Mapping[int, str]) -> list[dict[str, Any]]:
    """Quantify synthetic modeled-load loss; never manufacture customer counts."""
    totals: dict[str, float] = {}
    lost: dict[str, float] = {}
    for _, row in net.load.iterrows():
        county = county_by_bus.get(int(row.bus))
        if county is None:
            continue
        mw = float(row.p_mw)
        totals[county] = totals.get(county, 0.0) + mw
        if not bool(row.in_service):
            lost[county] = lost.get(county, 0.0) + mw
    return [
        {
            "county_fips": county,
            "lost_mw": round(lost_mw, 6),
            "customers_out": None,
            "fraction_dark": round(lost_mw / totals[county], 6)
            if totals[county]
            else 0.0,
            "basis": "synthetic modeled load; customer count unavailable",
        }
        for county, lost_mw in sorted(lost.items())
    ]


def _unqualified_payload(result: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "run_id": result["run_id"],
        "scenario_id": result["scenario_id"],
        "hour": result["hour"],
        "topology": {"label": result["topology"], "source_kind": "simulated"},
        "scenario_provenance": None,
        "weather_source_run": None,
        "persisted_provenance": None,
        "qualification": {"playback_qualified": False, "reasons": [reason]},
    }


def _number_token(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number).replace(".", "p")
