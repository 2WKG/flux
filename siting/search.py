"""Bounded, synthetic-topology location screening for new grid interventions.

The search output is deliberately a *screening comparison*.  It evaluates the
declared synthetic network and never describes a result as a physical siting,
interconnection, permitting, or construction recommendation.  Upstream policy
owners supply feasibility, balance/corridor, redundancy, and cascade evidence;
this module owns their ordering, bounded counterfactual work, normalization,
and a reviewable result shape.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from typing import Literal

CandidateKind = Literal["producer", "consumer"]
SCREENING_LABEL = "synthetic-topology screening; not a physical siting or permitability claim"
MAX_FULL_WINDOW_COUNTERFACTUALS = 5


class SearchUnavailable(RuntimeError):
    """A required policy or counterfactual result was unavailable.

    Search must not replace a missing physics or policy result with a plausible
    score.  Callers can surface this as an unavailable analysis instead.
    """


@dataclass(frozen=True)
class SearchAdapters:
    """Injectable policy boundary used by tests and sibling integrations.

    Each callable may return either a mapping or an object with identically
    named attributes.  The permissive transport shape keeps this coordination
    layer independent of the sibling modules' result classes while the
    required *facts* remain strict: feasibility must be explicit, and consumer
    candidates require an explicit P4 corridor pass.
    """

    feasibility: Callable[..., object] | None = None
    balance: Callable[..., object] | None = None
    redundancy: Callable[..., object] | None = None
    cascade: Callable[..., object] | None = None
    candidates: Callable[..., Iterable[object]] | None = None
    edit_factory: Callable[..., object] | None = None
    edit_hasher: Callable[..., str] | None = None


def search_locations(
    net: object,
    *,
    kind: CandidateKind,
    unit_mw: float,
    scenario_id: str,
    n: int = 5,
    hour: int = 0,
    edits: Sequence[object] = (),
    adapters: SearchAdapters | Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    """Return up to ``n`` ranked, feasible synthetic screening candidates.

    Every candidate first receives a peak-hour counterfactual.  Only the five
    strongest preliminary candidates are replayed across the full window.  A
    consumer candidate is excluded before any ranking if its balance evidence
    does not explicitly say it passes the P4 corridor headroom rule.
    """

    _validate_request(kind, unit_mw, scenario_id, n, hour)
    policy = _adapters(adapters)
    # Feasibility is the first mandatory gate.  Resolve it before the shared
    # baseline so an unavailable placement policy cannot accidentally trigger
    # a costly or misleading cascade run.
    if (
        policy.feasibility is None
        and _find_callable(net, "placement_feasibility", "feasibility") is None
        and _import_callable("twin.feasibility", "evaluate_feasibility")
        is None
    ):
        raise SearchUnavailable("placement feasibility policy is unavailable")
    candidates = _candidate_rows(net, kind, policy)
    if not candidates:
        return []

    baseline_peak = _cascade(net, scenario_id, hour, tuple(edits), policy)
    baseline_redundancy: object | None = (
        _baseline_redundancy(
            net, candidates, kind, unit_mw, scenario_id, hour, tuple(edits), policy
        )
        if kind == "producer"
        else None
    )

    preliminary: list[dict[str, object]] = []
    for candidate in candidates:
        edit = _candidate_edit(candidate, kind, unit_mw, policy)
        candidate_edits = (*edits, edit)
        feasibility = _feasibility(
            net, candidate, edit, kind, unit_mw, scenario_id, hour, candidate_edits, policy
        )
        if not _feasible(feasibility):
            continue

        balance: object | None = None
        if kind == "consumer":
            balance = _balance(
                net, candidate, unit_mw, scenario_id, hour, candidate_edits, policy
            )
            # Missing or ambiguous corridor evidence is a rejection, not a
            # guessed safe path.
            if not _passed(
                balance,
                "p4_passed",
                "corridor_p4_passed",
                "p4_ok",
                "corridor_ok",
            ):
                continue

        counterfactual = _cascade(net, scenario_id, hour, candidate_edits, policy)
        redundancy = _redundancy(
            net, candidate, kind, unit_mw, scenario_id, hour, candidate_edits, policy
        )
        components = _components(
            kind,
            baseline_peak,
            counterfactual,
            baseline_redundancy,
            redundancy,
            balance,
        )
        preliminary.append(
            {
                "candidate": candidate,
                "edit": edit,
                "edits": candidate_edits,
                "feasibility": feasibility,
                "balance": balance,
                "peak_counterfactual": counterfactual,
                "peak_components": components,
            }
        )

    if not preliminary:
        return []

    _assign_objectives(preliminary, kind, component_key="peak_components")
    preliminary.sort(key=_rank_key)
    finalists = preliminary[:MAX_FULL_WINDOW_COUNTERFACTUALS]

    # Full-window results replace peak-hour results for the bounded finalist
    # set.  The baseline is shared, so no candidate receives a different
    # reference scenario.
    baseline_full = _cascade(net, scenario_id, None, tuple(edits), policy)
    baseline_full_redundancy: object | None = (
        _baseline_redundancy(
            net, candidates, kind, unit_mw, scenario_id, None, tuple(edits), policy
        )
        if kind == "producer"
        else None
    )
    for row in finalists:
        candidate = _as_mapping(row["candidate"])
        candidate_edits = row["edits"]
        assert isinstance(candidate_edits, tuple)
        counterfactual = _cascade(net, scenario_id, None, candidate_edits, policy)
        balance = row["balance"]
        if kind == "consumer":
            balance = _balance(
                net, candidate, unit_mw, scenario_id, None, candidate_edits, policy
            )
            if not _passed(
                balance,
                "p4_passed",
                "corridor_p4_passed",
                "p4_ok",
                "corridor_ok",
            ):
                # A candidate can become invalid when the full window exposes
                # a P4 breach.  Do not retain its optimistic peak result.
                row["full_window_rejected"] = True
                continue
        redundancy = _redundancy(
            net, candidate, kind, unit_mw, scenario_id, None, candidate_edits, policy
        )
        row["balance"] = balance
        row["counterfactual"] = counterfactual
        row["components"] = _components(
            kind,
            baseline_full,
            counterfactual,
            baseline_full_redundancy,
            redundancy,
            balance,
        )

    finalists = [row for row in finalists if not row.get("full_window_rejected")]
    _assign_objectives(finalists, kind, component_key="components")
    finalists.sort(key=_rank_key)

    results: list[dict[str, object]] = []
    for rank, row in enumerate(finalists[:n], start=1):
        candidate = _as_mapping(row["candidate"])
        components = _as_mapping(row["components"])
        candidate_edits = row["edits"]
        assert isinstance(candidate_edits, tuple)
        results.append(
            {
                "rank": rank,
                "candidate_id": _candidate_id(candidate),
                "kind": kind,
                "bus_id": _required(candidate, "bus_id"),
                "objective": row["objective"],
                "objective_components": components,
                "edit_hash": _edit_hash(candidate_edits, policy),
                "counterfactual": row["counterfactual"],
                "feasibility": row["feasibility"],
                "safety_flags": _get(candidate, "safety_flags", "safety_flags_json", default=[]),
                "balance": row["balance"],
                "analysis_label": SCREENING_LABEL,
                "model_mode": "synthetic",
                "evaluation": {
                    "peak_hour": hour,
                    "full_window": _full_window_evaluated(row["counterfactual"]),
                    "scope": _get(
                        row["counterfactual"],
                        "evaluation_scope",
                        default="full_window",
                    ),
                    "bounded_full_window_candidates": MAX_FULL_WINDOW_COUNTERFACTUALS,
                },
            }
        )
    return results


def _validate_request(kind: str, unit_mw: float, scenario_id: str, n: int, hour: int) -> None:
    if kind not in {"producer", "consumer"}:
        raise ValueError("kind must be 'producer' or 'consumer'")
    if not _finite_positive(unit_mw):
        raise ValueError("unit_mw must be a finite positive MW value")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ValueError("scenario_id must be a non-empty string")
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_FULL_WINDOW_COUNTERFACTUALS:
        raise ValueError(f"n must be an integer from 1 to {MAX_FULL_WINDOW_COUNTERFACTUALS}")
    if isinstance(hour, bool) or not isinstance(hour, int) or hour < 0:
        raise ValueError("hour must be a non-negative integer")


def _adapters(value: SearchAdapters | Mapping[str, object] | None) -> SearchAdapters:
    if value is None:
        return SearchAdapters()
    if isinstance(value, SearchAdapters):
        return value
    if isinstance(value, Mapping):
        allowed = SearchAdapters.__dataclass_fields__
        unknown = set(value) - set(allowed)
        if unknown:
            raise ValueError(f"unknown search adapter(s): {sorted(unknown)!r}")
        return SearchAdapters(**value)  # type: ignore[arg-type]
    raise TypeError("adapters must be SearchAdapters, a mapping, or None")


def _candidate_rows(net: object, kind: CandidateKind, policy: SearchAdapters) -> list[dict[str, object]]:
    source: Iterable[object] | None = None
    if policy.candidates is not None:
        source = _invoke(policy.candidates, net=net, kind=kind)
    elif callable(getattr(net, "search_candidates", None)):
        source = _invoke(net.search_candidates, kind=kind)  # type: ignore[union-attr]
    elif kind == "producer":
        source = _get(net, "site_candidates", "producer_candidates", default=None)
    else:
        source = _get(net, "consumer_candidates", "load_buses", "loads", default=None)
    if source is None:
        raise SearchUnavailable(f"no {kind} candidate source is available")
    if isinstance(source, (str, bytes, Mapping)):
        source = [source]

    seen: set[str] = set()
    rows: list[dict[str, object]] = []
    for raw in source:
        candidate = _as_mapping(raw)
        candidate_id = _candidate_id(candidate)
        bus_id = _get(candidate, "bus_id", "id", default=None)
        if bus_id is None:
            raise SearchUnavailable(f"candidate {candidate_id!r} has no bus_id")
        if candidate_id in seen:
            raise ValueError(f"duplicate candidate id {candidate_id!r}")
        seen.add(candidate_id)
        candidate.setdefault("candidate_id", candidate_id)
        candidate.setdefault("bus_id", bus_id)
        candidate.setdefault("synthetic", True)
        rows.append(candidate)
    return rows


def _feasibility(net: object, candidate: Mapping[str, object], edit: object, kind: CandidateKind, unit_mw: float, scenario_id: str, hour: int | None, edits: tuple[object, ...], policy: SearchAdapters) -> object:
    fn = policy.feasibility or _find_callable(net, "placement_feasibility", "feasibility")
    if fn is not None:
        return _invoke(fn, net=net, candidate=candidate, edit=edit, kind=kind, unit_mw=unit_mw, scenario_id=scenario_id, hour=hour, edits=edits)
    fn = _import_callable("twin.feasibility", "evaluate_feasibility")
    if fn is None:
        raise SearchUnavailable("placement feasibility policy is unavailable")
    return _invoke(fn, net=net, edit=edit)


def _balance(net: object, candidate: Mapping[str, object], unit_mw: float, scenario_id: str, hour: int | None, edits: tuple[object, ...], policy: SearchAdapters) -> object:
    fn = policy.balance or _find_callable(net, "balance", "assess_balance")
    if fn is not None:
        return _invoke(fn, net=net, candidate=candidate, unit_mw=unit_mw, scenario_id=scenario_id, hour=hour, edits=edits)
    fn = _import_callable("twin.balance", "balance_report")
    if fn is None:
        raise SearchUnavailable("consumer balance/corridor policy is unavailable")
    report = _as_mapping(_invoke(fn, net=net, edits=edits))
    feasibility = _import_callable("twin.feasibility", "evaluate_feasibility")
    if feasibility is None:
        raise SearchUnavailable("consumer corridor policy is unavailable")
    p4 = _as_mapping(_invoke(feasibility, net=net, edit=edits[-1]))
    report["p4_passed"] = p4.get("status") == "valid"
    report["p4_evidence"] = p4
    return report


def _redundancy(net: object, candidate: Mapping[str, object] | None, kind: CandidateKind, unit_mw: float, scenario_id: str, hour: int | None, edits: tuple[object, ...], policy: SearchAdapters) -> object:
    fn = policy.redundancy or _find_callable(net, "redundancy", "redundancy_score")
    if fn is not None:
        return _invoke(fn, net=net, candidate=candidate, kind=kind, unit_mw=unit_mw, scenario_id=scenario_id, hour=hour, edits=edits)
    fn = _import_callable("siting.redundancy", "score_redundancy")
    if fn is None:
        raise SearchUnavailable("redundancy policy is unavailable")
    if candidate is None:
        raise SearchUnavailable("candidate-scoped redundancy requires a candidate")
    score_net = net
    if edits:
        apply = _import_callable("twin.edits", "apply_edits")
        if apply is None:
            raise SearchUnavailable("immutable edit application is unavailable")
        score_net = _invoke(apply, net=net, edits=edits)
    return _invoke(
        fn,
        net=score_net,
        bus_id=_required(candidate, "bus_id"),
        scenario_id=scenario_id,
        hour=0 if hour is None else hour,
    )


def _baseline_redundancy(
    net: object,
    candidates: Sequence[Mapping[str, object]],
    kind: CandidateKind,
    unit_mw: float,
    scenario_id: str,
    hour: int | None,
    edits: tuple[object, ...],
    policy: SearchAdapters,
) -> object:
    """Return a producer baseline without inventing a network-wide score.

    The 434 contract scores one bus at a time.  A producer search therefore
    uses the arithmetic mean of the same candidate-bus population before any
    candidate edit.  Each counterfactual is then evaluated at its own bus,
    making ``mean_redundancy_uplift`` a measurable difference on a declared
    population rather than a fabricated system-wide redundancy number.
    """

    if policy.redundancy is not None or _find_callable(net, "redundancy", "redundancy_score"):
        return _redundancy(
            net, None, kind, unit_mw, scenario_id, hour, edits, policy
        )
    values = [
        _redundancy_value(
            _redundancy(net, candidate, kind, unit_mw, scenario_id, hour, edits, policy)
        )
        for candidate in candidates
    ]
    if not values:
        raise SearchUnavailable("producer search has no candidate buses for redundancy baseline")
    return {"mean_redundancy": sum(values) / len(values)}


def _cascade(net: object, scenario_id: str, hour: int | None, edits: tuple[object, ...], policy: SearchAdapters) -> object:
    if policy.cascade is not None:
        return _invoke(policy.cascade, net=net, scenario_id=scenario_id, hour=hour, edits=edits)
    runner = _find_callable(net, "run_cascade") or _import_callable("twin.cascade", "run_cascade")
    if runner is None:
        raise SearchUnavailable("cascade counterfactual interface is unavailable")
    # ``twin.cascade.run_cascade`` owns immutable application of the ordered
    # edits.  Passing a pre-edited net would apply every edit twice.  Its
    # current primitive is a single synthetic snapshot; richer scenario/window
    # adapters receive ``scenario_id`` and ``hour`` through the injected path.
    result = _as_mapping(_invoke(runner, net=net, edits=edits))
    # The current foundation exposes one immutable synthetic snapshot.  Do not
    # present a repeated snapshot as a scenario-window replay; callers with a
    # window-aware cascade use the injected adapter boundary above.
    result.setdefault("evaluation_scope", "single_synthetic_snapshot")
    return result


def _candidate_edit(candidate: Mapping[str, object], kind: CandidateKind, unit_mw: float, policy: SearchAdapters) -> object:
    fields = {
        "kind": "add_gen" if kind == "producer" else "add_load",
        "element_id": f"search:{kind}:{_candidate_id(candidate)}",
        "bus_id": _required(candidate, "bus_id"),
        "p_mw": float(unit_mw),
        "pmax_mw": float(unit_mw) if kind == "producer" else None,
        "length_km": _get(candidate, "interconnect_distance_km", "length_km", default=None),
    }
    factory = policy.edit_factory or _import_callable("twin.contracts", "GridEdit")
    if factory is None:
        # The fallback is intentionally explicit and serializable, for tests
        # before the shared twin contract is installed.
        return {key: value for key, value in fields.items() if value is not None}
    return _invoke(factory, **fields)


def _components(kind: CandidateKind, baseline: object, counterfactual: object, baseline_redundancy: object, redundancy: object, balance: object | None) -> dict[str, float]:
    if kind == "producer":
        baseline_lol = _lost_load_mwh(baseline)
        candidate_lol = _lost_load_mwh(counterfactual)
        base_congestion = _congestion_proxy(baseline)
        candidate_congestion = _congestion_proxy(counterfactual)
        if base_congestion == 0.0:
            congestion_relief_pct = 0.0
        else:
            congestion_relief_pct = 100.0 * (base_congestion - candidate_congestion) / abs(base_congestion)
        return {
            "lost_load_reduction_mwh": baseline_lol - candidate_lol,
            "mean_redundancy_uplift": _redundancy_value(redundancy) - _redundancy_value(baseline_redundancy),
            "congestion_relief_pct": congestion_relief_pct,
        }
    if balance is None:
        raise SearchUnavailable("consumer balance evidence is unavailable")
    return {
        "redundancy_score": _redundancy_value(redundancy),
        "headroom_mw": _number(balance, "headroom_mw"),
    }


def _lost_load_mwh(result: object) -> float:
    """Read a declared MWh value or the foundation's one-hour MW snapshot."""

    value = _get(result, "lost_load_mwh", default=None)
    if value is not None:
        return _number(result, "lost_load_mwh")
    # ``run_cascade`` is one declared snapshot.  Its lost-load MW therefore
    # represents one modeled hour for peak-hour comparison, not a historical
    # or full-window energy observation.
    return _number(result, "lost_load_mw")


def _congestion_proxy(result: object) -> float:
    """Return a named synthetic overload proxy when no congestion series exists."""

    explicit = _get(result, "congestion_mwh", "congestion", default=None)
    if explicit is not None:
        return _number(result, "congestion_mwh", "congestion")
    loading = _get(result, "loading_by_element", default=None)
    if not isinstance(loading, Mapping):
        raise SearchUnavailable("modeled congestion or line-loading evidence is unavailable")
    overload = 0.0
    for element_id, percent in loading.items():
        if not isinstance(element_id, str):
            raise SearchUnavailable("line-loading evidence has an invalid element identity")
        if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not isfinite(float(percent)):
            raise SearchUnavailable("line-loading evidence has a non-finite percentage")
        overload += max(0.0, float(percent) - 100.0)
    return overload


def _full_window_evaluated(result: object) -> bool:
    return _get(result, "evaluation_scope", default="full_window") != "single_synthetic_snapshot"


def _assign_objectives(rows: list[dict[str, object]], kind: CandidateKind, *, component_key: str) -> None:
    if not rows:
        return
    names = (
        ("lost_load_reduction_mwh", "mean_redundancy_uplift", "congestion_relief_pct")
        if kind == "producer"
        else ("redundancy_score", "headroom_mw")
    )
    weights = (0.5, 0.3, 0.2) if kind == "producer" else (0.6, 0.4)
    values = {
        name: [_number(_as_mapping(row[component_key]), name) for row in rows]
        for name in names
    }
    for index, row in enumerate(rows):
        components = dict(_as_mapping(row[component_key]))
        normalized = {
            name: _minmax(values[name], values[name][index]) for name in names
        }
        components["normalized"] = normalized
        row[component_key] = components
        row["objective"] = sum(weight * normalized[name] for name, weight in zip(names, weights, strict=True))


def _rank_key(row: Mapping[str, object]) -> tuple[float, str]:
    return (-float(row["objective"]), _candidate_id(_as_mapping(row["candidate"])))


def _minmax(values: Sequence[float], value: float) -> float:
    low, high = min(values), max(values)
    # A tie is an honest result.  Assigning a nonzero value would manufacture a
    # winner where the model contains no differentiation.
    return 0.0 if high == low else (value - low) / (high - low)


def _edit_hash(edits: tuple[object, ...], policy: SearchAdapters) -> str:
    # Tests and API adapters may choose a plain serializable edit factory.  Do
    # not import pandapower merely to hash those values; production GridEdit
    # values use the canonical sibling hasher below.
    hasher = policy.edit_hasher
    if hasher is None and policy.edit_factory is None:
        hasher = _import_callable("twin.edits", "edit_hash")
    if hasher is not None:
        value = _invoke(hasher, edits=edits)
        if isinstance(value, str) and value:
            return value
        raise SearchUnavailable("shared edit_hash returned no hash")
    # Only a bridge for tests before the shared contracts land.  It remains
    # ordered so a different intervention sequence has a different identity.
    payload = json.dumps([_jsonable(edit) for edit in edits], sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _invoke(fn: Callable[..., object], /, **kwargs: object) -> object:
    """Call a sibling adapter without coupling this module to result classes."""
    try:
        return fn(**kwargs)
    except TypeError as keyword_error:
        # Narrow fallback for small test doubles and positional-only sibling
        # callables.  Do not hide a second TypeError raised by their own work.
        try:
            return fn(*kwargs.values())
        except TypeError:
            raise keyword_error


def _find_callable(obj: object, *names: str) -> Callable[..., object] | None:
    for name in names:
        value = getattr(obj, name, None)
        if callable(value):
            return value
    return None


def _import_callable(module_name: str, *names: str) -> Callable[..., object] | None:
    try:
        module = __import__(module_name, fromlist=list(names))
    except ImportError:
        return None
    for name in names:
        value = getattr(module, name, None)
        if callable(value):
            return value
    return None


def _as_mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise TypeError(f"expected a mapping-like value, got {type(value).__name__}")


def _get(value: object, *names: str, default: object) -> object:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
        return default
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _required(value: object, *names: str) -> object:
    found = _get(value, *names, default=None)
    if found is None:
        raise SearchUnavailable(f"required field {names[0]!r} is unavailable")
    return found


def _candidate_id(candidate: Mapping[str, object]) -> str:
    value = _get(candidate, "candidate_id", "site_id", "id", "name", default=None)
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value):
        raise SearchUnavailable("candidate requires a stable candidate_id, site_id, id, or name")
    return str(value)


def _passed(value: object, *names: str) -> bool:
    marker = _get(value, *names, default=None)
    return marker is True


def _feasible(value: object) -> bool:
    return _passed(value, "feasible", "passed", "allowed") or _get(value, "status", default=None) == "valid"


def _number(value: object, *names: str) -> float:
    raw = _get(value, *names, default=None)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not isfinite(float(raw)):
        raise SearchUnavailable(f"required finite metric {names[0]!r} is unavailable")
    return float(raw)


def _redundancy_value(value: object) -> float:
    return _number(value, "mean_redundancy", "redundancy_score", "score")


def _finite_positive(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(float(value)) and float(value) > 0.0


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())  # type: ignore[union-attr]
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return repr(value)
