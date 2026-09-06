"""Behavioral tests for the fixture-safe app scaffold and health route."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import ValidationError

from copilot.api import API_VERSION
from copilot.app import create_app
from copilot.config import Settings

# Run in a subprocess so the failure is the one an operator sees: `copilot/app.py`
# builds the app at module import, so a bad DUCKDB_PATH fails before any request.
_IMPORT_PROBE = """
import traceback

from copilot.config import ConfigError

try:
    import copilot.app  # noqa: F401
except ConfigError as error:
    print("NAMED", type(error).__name__, error)
    print("TRACEBACK", traceback.format_exc().replace(chr(10), " | "))
else:
    print("NO ERROR")
"""


def _response_surface(response: Response) -> str:
    """Every byte a client sees: `response.text` covers the body only, so a
    credential shipped in a header would otherwise pass unnoticed."""
    headers = "\n".join(f"{key}: {value}" for key, value in response.headers.items())
    return f"{response.text}\n{headers}"


def _fixture_database(path: Path, *, with_corpus: bool = True) -> None:
    connection = duckdb.connect(str(path))
    connection.execute("CREATE TABLE fixture_marker (id INTEGER)")
    if with_corpus:
        connection.execute("CREATE TABLE corpus_chunks (embedding DOUBLE[])")
        connection.execute("INSERT INTO corpus_chunks VALUES ([0.5])")
    connection.close()


def test_settings_leave_the_model_unconfigured_when_copilot_model_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COPILOT_MODEL", raising=False)

    assert Settings(_env_file=None).copilot_model is None


@pytest.mark.parametrize(
    ("configured_path", "expected_error"),
    [
        ("", "non-empty local file path"),
        ("   ", "non-empty local file path"),
        (".", "name a file, not a directory"),
        (":memory:", "not a DuckDB connection target"),
        ("md:my_db", "not a DuckDB connection target"),
        ("md:", "not a DuckDB connection target"),
        ("md:?motherduck_token=private-db-token", "not a DuckDB connection target"),
        ("ducklake:x", "not a DuckDB connection target"),
        ("ducklake:metadata.ducklake", "not a DuckDB connection target"),
        ("motherduck://token=private-db-token", "not a DuckDB connection target"),
        ("http://host/private-db-token.duckdb", "not a DuckDB connection target"),
        ("s3://bucket/grid.duckdb", "not a DuckDB connection target"),
    ],
)
def test_settings_reject_invalid_database_locations_without_exposing_input(
    monkeypatch: pytest.MonkeyPatch,
    configured_path: str,
    expected_error: str,
) -> None:
    monkeypatch.setenv("DUCKDB_PATH", configured_path)

    with pytest.raises(ValidationError, match=expected_error) as error:
        Settings(_env_file=None)

    assert "private-db-token" not in str(error.value)


@pytest.mark.parametrize(
    "configured_path",
    [
        Path("motherduck://token=private-db-token"),
        Path("md:my_db"),
        Path(":memory:"),
        Path("ducklake:metadata.ducklake"),
    ],
)
def test_settings_reject_connection_targets_passed_as_paths(
    configured_path: Path,
) -> None:
    """Every in-repo call site passes a ``Path``, which normalises away ``://``."""
    with pytest.raises(
        ValidationError, match="not a DuckDB connection target"
    ) as error:
        Settings(_env_file=None, duckdb_path=configured_path)

    assert "private-db-token" not in str(error.value)


@pytest.mark.parametrize(
    "configured_path",
    ["grid.duckdb", "data/duck/grid.duckdb", "/tmp/flux/grid.duckdb"],
)
def test_settings_accept_ordinary_local_database_paths(configured_path: str) -> None:
    assert Settings(_env_file=None, duckdb_path=configured_path).duckdb_path == Path(
        configured_path
    )


def test_settings_accept_a_real_absolute_database_path(tmp_path: Path) -> None:
    """An absolute local artifact path is accepted and stays absolute."""
    configured_path = tmp_path / "data" / "grid.duckdb"

    settings = Settings(_env_file=None, duckdb_path=str(configured_path))

    assert settings.duckdb_path == configured_path
    assert settings.duckdb_path.is_absolute()
    assert settings.duckdb_path.name == "grid.duckdb"


@pytest.mark.parametrize("configured_path", ["C:/flux/data/grid.duckdb", "Z:/x.duckdb"])
def test_settings_only_accepts_a_drive_letter_path_when_local_to_this_platform(
    configured_path: str,
) -> None:
    """Drive paths are local on Windows but target-shaped on POSIX."""
    if Path(configured_path).is_absolute():
        assert Settings(
            _env_file=None, duckdb_path=configured_path
        ).duckdb_path == Path(configured_path)
    else:
        with pytest.raises(ValidationError, match="not a DuckDB connection target"):
            Settings(_env_file=None, duckdb_path=configured_path)


def test_settings_normalise_surrounding_whitespace_in_the_database_path() -> None:
    settings = Settings(_env_file=None, duckdb_path="  data/duck/grid.duckdb  ")

    assert settings.duckdb_path == Path("data/duck/grid.duckdb")


def test_settings_validate_the_database_path_without_opening_a_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Validation is syntactic: a connection here would be a network side effect."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("validation must not open a DuckDB connection")

    monkeypatch.setattr(duckdb, "connect", refuse)

    assert Settings(
        _env_file=None, duckdb_path=tmp_path / "grid.duckdb"
    ).duckdb_path == (tmp_path / "grid.duckdb")

    with pytest.raises(ValidationError, match="not a DuckDB connection target"):
        Settings(_env_file=None, duckdb_path="md:my_db")


def test_bad_configuration_at_import_raises_a_named_error_without_the_value() -> None:
    """`copilot/app.py` builds the app at import; operators must not get a traceback."""
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DUCKDB_PATH": "md:private-db-token",
            "PYTHONPATH": os.getcwd(),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "NAMED ConfigError" in result.stdout
    assert "duckdb_path" in result.stdout
    assert "not a DuckDB connection target" in result.stdout
    assert "private-db-token" not in result.stdout
    assert "private-db-token" not in result.stderr
    assert "pydantic" not in result.stdout


def test_settings_accepts_a_missing_local_database_for_unavailable_health_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "not-built-yet.duckdb"

    settings = Settings(duckdb_path=database)

    assert settings.duckdb_path == database
    assert not database.exists()


def test_health_opens_a_fixture_database_without_claiming_model_availability(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)
    app = create_app(Settings(duckdb_path=database))

    response = TestClient(app).get("/health", headers={"X-Request-ID": "health-1"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "ok": True,
        "duckdb_path": str(database),
        "tables": ["corpus_chunks", "fixture_marker"],
        "corpus_chunks": 1,
        "dense": True,
        "model": {
            "status": "not_configured",
            "message": "No model provider credential is configured.",
        },
    }
    assert response.headers["X-Request-ID"] == "health-1"
    assert response.headers["X-Flux-Api-Version"] == API_VERSION
    assert "X-Flux-Artifact" not in response.headers


def test_health_reports_a_sparse_fixture_without_claiming_dense_retrieval(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database, with_corpus=False)
    app = create_app(Settings(duckdb_path=database))

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "duckdb_path": str(database),
        "tables": ["fixture_marker"],
        "corpus_chunks": 0,
        "dense": False,
        "model": {
            "status": "not_configured",
            "message": "No model provider credential is configured.",
        },
    }


def test_health_returns_the_shared_unavailable_envelope_for_a_missing_fixture(
    tmp_path: Path,
) -> None:
    database = tmp_path / "missing.duckdb"
    secret = "unavailable-but-configured"
    app = create_app(Settings(duckdb_path=database, anthropic_api_key=secret))

    # App construction must not eagerly open DuckDB and create an empty file.
    # Redundant with the assertions below (they already catch an eager open); kept
    # only to localise such a failure to the construction phase, not as coverage.
    assert not database.exists()

    response = TestClient(app).get("/health", headers={"X-Request-ID": "health-2"})

    assert response.status_code == 503
    assert secret not in _response_surface(response)
    assert response.json()["status"] == "unavailable"
    assert response.json()["data"] is None
    assert response.json()["error"] == {
        "code": "unavailable",
        "message": "The configured database artifact is unavailable.",
        "retryable": True,
        "retry_after_s": 30,
        "details": {"artifact": "database", "model": "not_configured"},
    }
    assert not database.exists()
    assert response.headers["X-Request-ID"] == "health-2"
    assert response.headers["X-Flux-Api-Version"] == API_VERSION
    assert "X-Flux-Artifact" not in response.headers


def test_cors_exposes_response_metadata_headers(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)
    app = create_app(Settings(duckdb_path=database))

    response = TestClient(app).get(
        "/health", headers={"Origin": "http://localhost:5173"}
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Expose-Headers"] == (
        "X-Request-ID, X-Flux-Api-Version, X-Flux-Artifact, X-Flux-Attempt-Id"
    )


def test_internal_error_keeps_cors_and_response_metadata(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)
    app = create_app(Settings(duckdb_path=database))

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("unexpected test failure")

    response = TestClient(app, raise_server_exceptions=False).get(
        "/boom", headers={"Origin": "http://localhost:5173"}
    )

    assert response.status_code == 500
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert response.headers["Access-Control-Expose-Headers"] == (
        "X-Request-ID, X-Flux-Api-Version, X-Flux-Artifact, X-Flux-Attempt-Id"
    )
    assert response.headers["X-Flux-Api-Version"] == API_VERSION
    assert "X-Flux-Artifact" not in response.headers


def test_health_does_not_treat_a_configured_credential_as_model_availability(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)
    secret = "configured-but-unchecked"
    app = create_app(
        Settings(
            duckdb_path=database,
            copilot_model="claude-sonnet-5",
            anthropic_api_key=secret,
        )
    )

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert secret not in _response_surface(response)
    assert response.json()["ok"] is True
    assert response.json()["model"] == {
        "status": "not_verified",
        "message": "Model availability is not verified by this local health check.",
    }
