"""Tests for the wire-coverage plugin in ``tests/conftest.py``."""

from __future__ import annotations

import pytest

from tests import conftest as wire

create_app = wire._load_create_app()
needs_app = pytest.mark.skipif(
    create_app is None, reason="no copilot.app on this branch"
)


def test_unhit_routes_reports_only_registered_routes_nobody_served() -> None:
    registered = {("GET", "m.a"): "/a", ("GET", "m.b"): "/b", ("POST", "m.c"): "/c"}
    served = {("GET", "m.a"), ("GET", "m.elsewhere")}

    assert wire.unhit_routes(registered, served) == [("GET", "/b"), ("POST", "/c")]


def test_registered_routes_excludes_docs_and_auto_methods() -> None:
    fastapi = pytest.importorskip("fastapi")
    app = fastapi.FastAPI()

    @app.get("/probe")
    def probe() -> dict[str, bool]:
        return {"ok": True}

    routes = wire.registered_routes(app)

    assert routes == {("GET", wire.endpoint_id(probe)): "/probe"}


def test_recorder_sees_a_route_served_through_an_included_router() -> None:
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    router = fastapi.APIRouter(prefix="/wire")
    app = fastapi.FastAPI()

    @router.get("/coverage-probe")
    def probe() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router, prefix="/v1")
    assert wire.registered_routes(app) == {
        ("GET", wire.endpoint_id(probe)): "/v1/wire/coverage-probe"
    }

    key = ("GET", wire.endpoint_id(probe))
    assert key not in wire.served_routes()
    assert TestClient(app).get("/v1/wire/coverage-probe").status_code == 200
    assert key in wire.served_routes()


@needs_app
def test_copilot_app_registers_routes_the_gate_will_enforce() -> None:
    assert create_app is not None
    registered = wire.registered_routes(create_app())

    assert registered, "create_app() registered no enforceable routes"
    assert all(path.startswith("/") for path in registered.values())
