"""Read-through and no-compute proofs for the persisted artifact routes (2WKG-171).

The behavioural payloads of ``GET /predictions`` and ``GET /cascade`` are pinned
in ``copilot/test_predictions.py``; this module deliberately asserts nothing that
file already asserts.  What it adds is the property that file cannot express: the
read routes *serve persisted rows* rather than calculating them.

Two independent assertions carry that:

* :func:`test_predictions_serves_exactly_what_persistence_returned` installs a
  recording double at the one seam the route really uses
  (``models.outage.persistence.query_predictions``, bound into the route module)
  and requires the response body to be exactly the rows that seam returned,
  sentinel values included.  A route that recomputed any served field would
  no longer match.
* :func:`test_read_routes_import_no_prediction_computation` asserts the route
  module imports no computation module at all — statically over its source, so a
  module-level *and* a function-local ``from models.outage.prediction_paths
  import …`` are both caught, and over its runtime globals, so a rebinding at
  import time is caught too.  ``monkeypatch.setattr`` on the compute module could
  not see either shape; this can.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from fastapi.encoders import jsonable_encoder

from copilot._artifact_fixtures import (
    SCENARIO,
    Prediction,
    client,
    prediction_database,
)
from copilot.routes import predictions as predictions_module

#: Modules that would be a *computed* rather than a persisted answer.
COMPUTE_MODULES = ("models.outage.prediction_paths", "models.outage.evaluate")


def _utc_z(value: object) -> object:
    """Render an ISO UTC offset the way the app's JSON encoder does."""
    if isinstance(value, str) and value.endswith("+00:00"):
        return f"{value[: -len('+00:00')]}Z"
    return value


def test_predictions_serves_exactly_what_persistence_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The response body is the persistence seam's rows, not a recomputation."""
    database = tmp_path / "predictions.duckdb"
    prediction_database(database, (Prediction("27000"),))

    real_query = predictions_module.query_predictions
    calls: list[dict[str, object]] = []
    served: list[list[dict[str, object]]] = []

    def _recording_query(con: object, **kwargs: object) -> list[dict[str, object]]:
        calls.append(kwargs)
        rows = real_query(con, **kwargs)  # type: ignore[arg-type]
        # A value no computation in this repo would produce, so a route that
        # calculated `p_out` instead of serving the persisted row diverges here.
        for row in rows:
            row["p_out"] = 0.123456789
        served.append(rows)
        return rows

    monkeypatch.setattr(predictions_module, "query_predictions", _recording_query)

    response = client(database).get("/predictions", params={"scenario_id": SCENARIO})

    assert response.status_code == 200
    # The route read through the seam exactly once, with the qualification
    # predicate pushed into SQL.
    assert len(calls) == 1
    assert calls[0]["scenario_id"] == SCENARIO
    assert calls[0]["qualified_only"] is True
    # And served precisely those rows (the app renders UTC as ``Z``; that is the
    # only transformation the route is allowed to make).
    assert response.json() == [
        {key: _utc_z(value) for key, value in row.items()}
        for row in jsonable_encoder(served[0])
    ]
    assert response.json()[0]["p_out"] == 0.123456789


def test_read_routes_import_no_prediction_computation() -> None:
    """No computation module is imported by the read-route module, anywhere."""
    source = Path(inspect.getfile(predictions_module)).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)

    offending_imports = {
        name
        for name in imported
        for compute in COMPUTE_MODULES
        if name == compute or name.startswith(f"{compute}.")
    }
    assert offending_imports == set(), (
        f"{predictions_module.__name__} imports computation: {offending_imports}"
    )

    # Runtime globals, for a name bound from a computation module by any route.
    offending_globals = {
        name
        for name, value in vars(predictions_module).items()
        if getattr(value, "__module__", "") in COMPUTE_MODULES
        or getattr(value, "__name__", "") in COMPUTE_MODULES
    }
    assert offending_globals == set(), (
        f"{predictions_module.__name__} binds computation: {offending_globals}"
    )
