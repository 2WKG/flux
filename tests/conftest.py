"""Wire-coverage pytest plugin.

Records every ``(method, path)`` the Starlette router actually serves during the
session and, at session end, compares that against the routes registered by
``copilot.app.create_app()``. A registered route that no test ever hit fails the
session. This catches the "body-tested, wire-untested" class: a router whose
tests are green but whose ``include_router`` call was dropped.

Behavior:

- ``copilot.app.create_app`` importable -> enforce at ``pytest_sessionfinish``.
- Not importable (master today) -> nothing to enforce; the plugin stays inert.
- Narrowed runs (positional paths, ``-k``, ``-m``, ``--collect-only``) are not
  enforced, so a developer running one file is never punished. CI runs the whole
  suite, which is enforced.
- ``FLUX_WIRE_COVERAGE=0`` disables enforcement explicitly (and says so).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

import pytest

EXCLUDED_PATHS = frozenset(
    {"/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}
)
EXCLUDED_METHODS = frozenset({"HEAD", "OPTIONS"})

# A route is identified by (method, endpoint identity), not by path: FastAPI
# applies include_router prefixes outside the Route object, and endpoint
# identity is stable across separate create_app() calls.
RouteKey = tuple[str, str]

_served: set[RouteKey] = set()
_recorder_installed = False


def endpoint_id(endpoint: object) -> str:
    return f"{getattr(endpoint, '__module__', '?')}.{getattr(endpoint, '__qualname__', repr(endpoint))}"


def served_routes() -> frozenset[RouteKey]:
    """Routes served so far in this session (for tests of the plugin itself)."""
    return frozenset(_served)


def _route_classes() -> list[type]:
    """Every Route class that defines its own ``handle`` (FastAPI overrides it)."""
    classes: list[type] = []
    try:
        from starlette.routing import Route
    except ImportError:  # starlette absent: nothing to record
        return classes
    classes.append(Route)
    try:
        from fastapi.routing import APIRoute
    except ImportError:
        return classes
    classes.append(APIRoute)
    return [cls for cls in classes if "handle" in cls.__dict__]


def _install_recorder() -> None:
    global _recorder_installed
    if _recorder_installed:
        return
    classes = _route_classes()
    if not classes:
        return

    def wrap(original_handle):  # type: ignore[no-untyped-def]
        async def recording_handle(self, scope, receive, send):  # type: ignore[no-untyped-def]
            method = scope.get("method")
            if method and method not in EXCLUDED_METHODS:
                _served.add((method, endpoint_id(self.endpoint)))
            return await original_handle(self, scope, receive, send)

        return recording_handle

    for cls in classes:
        cls.handle = wrap(cls.__dict__["handle"])  # type: ignore[method-assign]
    _recorder_installed = True


def _route_contexts(app):  # type: ignore[no-untyped-def]
    """Yield (path, methods, endpoint) for every HTTP route, prefixes applied."""
    from starlette.routing import Route

    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # older FastAPI flattens included routers into app.routes
        contexts = app.routes
    else:
        contexts = iter_route_contexts(app.routes)
    for context in contexts:
        original = getattr(context, "original_route", context)
        if isinstance(original, Route):
            yield context.path, context.methods or (), original.endpoint


def registered_routes(app) -> dict[RouteKey, str]:  # type: ignore[no-untyped-def]
    """Every enforceable (method, endpoint) -> path, minus docs and auto-routes."""
    found: dict[RouteKey, str] = {}
    for path, methods, endpoint in _route_contexts(app):
        if path in EXCLUDED_PATHS:
            continue
        for method in methods:
            if method not in EXCLUDED_METHODS:
                found[(method, endpoint_id(endpoint))] = path
    return found


def unhit_routes(
    registered: Mapping[RouteKey, str], served: Iterable[RouteKey]
) -> list[tuple[str, str]]:
    """(method, path) for registered routes never served, sorted for a stable report."""
    hit = set(served)
    return sorted(
        (method, path)
        for (method, key), path in registered.items()
        if (method, key) not in hit
    )


def _load_create_app():  # type: ignore[no-untyped-def]
    try:
        from copilot.app import create_app
    except ImportError:
        return None
    return create_app


def _run_is_narrowed(config: pytest.Config) -> bool:
    if config.getoption("collectonly", default=False):
        return True
    if config.getoption("keyword", default="") or config.getoption(
        "markexpr", default=""
    ):
        return True
    root = str(config.rootpath)
    for arg in config.args:
        path = os.path.abspath(arg.split("::", 1)[0])
        if path != root:
            return True
    return False


def pytest_configure(config: pytest.Config) -> None:
    _install_recorder()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")

    def say(line: str) -> None:
        if reporter is not None:
            reporter.write_line(line)

    if os.environ.get("FLUX_WIRE_COVERAGE", "1") == "0":
        say("wire-coverage: disabled by FLUX_WIRE_COVERAGE=0")
        return
    create_app = _load_create_app()
    if create_app is None:
        return
    if _run_is_narrowed(session.config):
        say(
            "wire-coverage: not enforced for a narrowed run (whole-suite runs enforce it)"
        )
        return
    if not _recorder_installed:
        say("wire-coverage: FAIL - route recorder was never installed")
        session.exitstatus = 1
        return

    registered = registered_routes(create_app())
    missing = unhit_routes(registered, _served)
    if not missing:
        say(
            f"wire-coverage: PASS - all {len(registered)} registered routes were served by tests"
        )
        return
    say(
        f"wire-coverage: FAIL - {len(missing)} registered route(s) never served by any test:"
    )
    for method, path in missing:
        say(f"  {method} {path}")
    say(
        "  Add a test that drives each route through TestClient (not just its handler body)."
    )
    session.exitstatus = 1
