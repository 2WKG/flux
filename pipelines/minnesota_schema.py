"""Idempotent, namespaced storage for Minnesota artifact metadata."""

import duckdb

SCHEMA_VERSION = "2.0.0-mn"
TABLES = (
    "mn_schema_meta", "mn_artifact_manifests", "mn_artifact_provenance",
    "mn_artifact_field_provenance", "mn_geography_artifacts", "mn_fixture_artifacts",
    "mn_scenario_artifacts", "mn_model_results", "mn_score_results",
    "mn_citation_chunks", "mn_citation_hits",
)

DDL = (
    "CREATE TABLE mn_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE mn_artifact_manifests (artifact_id TEXT PRIMARY KEY, artifact_kind TEXT NOT NULL,
    contract_version TEXT NOT NULL, geography_id TEXT NOT NULL, availability TEXT NOT NULL CHECK(availability IN ('available','unavailable')),
    model_mode TEXT NOT NULL CHECK(model_mode IN ('topology','aggregate','not_applicable')), identity_json JSON NOT NULL,
    created_at TIMESTAMP NOT NULL, assumptions_json JSON NOT NULL, limitations_json JSON NOT NULL, input_artifact_ids_json JSON NOT NULL)""",
    """CREATE TABLE mn_artifact_provenance (artifact_id TEXT NOT NULL REFERENCES mn_artifact_manifests(artifact_id),
    provenance_ordinal INTEGER NOT NULL CHECK(provenance_ordinal >= 0), source_name TEXT NOT NULL, source_ref TEXT NOT NULL,
    source_version TEXT NOT NULL, retrieved_at TIMESTAMP NOT NULL, license_or_terms TEXT NOT NULL, source_record_id TEXT,
    content_sha256 TEXT NOT NULL CHECK(regexp_full_match(content_sha256, '[0-9a-f]{64}')), is_derived BOOLEAN NOT NULL,
    PRIMARY KEY(artifact_id, provenance_ordinal))""",
    """CREATE TABLE mn_artifact_field_provenance (artifact_id TEXT NOT NULL, field_name TEXT NOT NULL,
    provenance_ordinal INTEGER NOT NULL, derivation_method TEXT, PRIMARY KEY(artifact_id,field_name,provenance_ordinal),
    FOREIGN KEY(artifact_id,provenance_ordinal) REFERENCES mn_artifact_provenance(artifact_id,provenance_ordinal))""",
    """CREATE TABLE mn_geography_artifacts (artifact_id TEXT PRIMARY KEY REFERENCES mn_artifact_manifests(artifact_id), geometry_wkb BLOB,
    lon DOUBLE, lat DOUBLE, coordinate_status TEXT NOT NULL CHECK(coordinate_status IN ('source','derived','unavailable')),
    coordinate_precision TEXT, CHECK((lon IS NULL) = (lat IS NULL)), CHECK(lon IS NULL OR (lon BETWEEN -180 AND 180 AND lat BETWEEN -90 AND 90)))""",
    "CREATE TABLE mn_fixture_artifacts (artifact_id TEXT PRIMARY KEY REFERENCES mn_artifact_manifests(artifact_id), source_manifest_id TEXT NOT NULL REFERENCES mn_artifact_manifests(artifact_id), fixture_label TEXT NOT NULL, fallback_label TEXT)",
    """CREATE TABLE mn_scenario_artifacts (artifact_id TEXT PRIMARY KEY REFERENCES mn_artifact_manifests(artifact_id), scenario_id TEXT NOT NULL UNIQUE,
    scenario_label TEXT NOT NULL, ts_begin TIMESTAMP NOT NULL, ts_end TIMESTAMP NOT NULL CHECK(ts_end >= ts_begin), location_coverage TEXT NOT NULL,
    weather_values_json JSON NOT NULL, outcome_artifact_id TEXT REFERENCES mn_artifact_manifests(artifact_id), matching_method TEXT)""",
    """CREATE TABLE mn_model_results (artifact_id TEXT PRIMARY KEY REFERENCES mn_artifact_manifests(artifact_id), model_name TEXT NOT NULL,
    model_version TEXT NOT NULL, model_run_id TEXT NOT NULL, input_manifest_sha256 TEXT NOT NULL CHECK(regexp_full_match(input_manifest_sha256, '[0-9a-f]{64}')),
    validation_status TEXT NOT NULL CHECK(validation_status='validated'), metric_name TEXT NOT NULL, metric_value DOUBLE NOT NULL,
    metric_unit TEXT NOT NULL, formula TEXT, base_mva DOUBLE, solver_version TEXT, converter_version TEXT, CHECK(isfinite(metric_value)))""",
    """CREATE TABLE mn_score_results (artifact_id TEXT PRIMARY KEY REFERENCES mn_artifact_manifests(artifact_id), metric TEXT NOT NULL,
    score_value DOUBLE NOT NULL CHECK(isfinite(score_value)), score_unit TEXT NOT NULL, score_components_json JSON NOT NULL,
    regulatory_label TEXT NOT NULL CHECK(regulatory_label IN ('hypothetical','source_screened','source_supported')))""",
    """CREATE TABLE mn_citation_chunks (chunk_id TEXT PRIMARY KEY, corpus_artifact_id TEXT NOT NULL REFERENCES mn_artifact_manifests(artifact_id),
    doc TEXT NOT NULL, title TEXT NOT NULL, page INTEGER NOT NULL CHECK(page > 0), chunk_ordinal INTEGER NOT NULL CHECK(chunk_ordinal >= 0), text TEXT NOT NULL,
    UNIQUE(corpus_artifact_id,doc,page,chunk_ordinal))""",
    """CREATE TABLE mn_citation_hits (artifact_id TEXT NOT NULL REFERENCES mn_artifact_manifests(artifact_id), hit_ordinal INTEGER NOT NULL CHECK(hit_ordinal >= 0),
    chunk_id TEXT NOT NULL REFERENCES mn_citation_chunks(chunk_id), doc TEXT NOT NULL, title TEXT NOT NULL, page INTEGER NOT NULL CHECK(page > 0),
    score DOUBLE NOT NULL CHECK(isfinite(score)), text TEXT NOT NULL, PRIMARY KEY(artifact_id,hit_ordinal))""",
)


def ensure_minnesota_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the MN namespace, refusing incompatible versions before any mutation."""
    existing = _version(con)
    mn_tables = {r[0] for r in con.execute("SHOW TABLES").fetchall() if r[0].startswith("mn_")}
    if mn_tables and existing is None:
        raise RuntimeError("Minnesota schema metadata is absent; migrate explicitly.")
    if existing is not None and existing != SCHEMA_VERSION:
        raise RuntimeError(f"Minnesota schema version is {existing!r}, expected {SCHEMA_VERSION!r}; migrate explicitly.")
    con.execute("BEGIN")
    try:
        for statement in DDL:
            con.execute(statement.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))
        if existing is None:
            con.execute("INSERT INTO mn_schema_meta VALUES ('contract_version', ?)", [SCHEMA_VERSION])
        _validate(con)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def _version(con: duckdb.DuckDBPyConnection) -> str | None:
    if "mn_schema_meta" not in {r[0] for r in con.execute("SHOW TABLES").fetchall()}:
        return None
    row = con.execute("SELECT value FROM mn_schema_meta WHERE key='contract_version'").fetchone()
    return None if row is None else row[0]


def _validate(con: duckdb.DuckDBPyConnection) -> None:
    actual = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    missing = set(TABLES) - actual
    if missing:
        raise RuntimeError(f"Minnesota schema missing tables: {sorted(missing)!r}; migrate explicitly.")
    expected = (("artifact_id", "VARCHAR", True, True), ("artifact_kind", "VARCHAR", True, False), ("contract_version", "VARCHAR", True, False), ("geography_id", "VARCHAR", True, False), ("availability", "VARCHAR", True, False), ("model_mode", "VARCHAR", True, False), ("identity_json", "JSON", True, False), ("created_at", "TIMESTAMP", True, False), ("assumptions_json", "JSON", True, False), ("limitations_json", "JSON", True, False), ("input_artifact_ids_json", "JSON", True, False))
    actual_columns = tuple((row[1], row[2], bool(row[3]), bool(row[5])) for row in con.execute("PRAGMA table_info('mn_artifact_manifests')").fetchall())
    constraints = " ".join(str(value) for row in con.execute("SELECT * FROM duckdb_constraints() WHERE table_name='mn_artifact_manifests'").fetchall() for value in row)
    if actual_columns != expected or "availability IN" not in constraints or "model_mode IN" not in constraints:
        raise RuntimeError("mn_artifact_manifests shape is incompatible; migrate explicitly.")
    bad = con.execute("""SELECT m.artifact_id FROM mn_artifact_manifests m
        WHERE m.availability='available' AND NOT EXISTS (SELECT 1 FROM mn_artifact_provenance p WHERE p.artifact_id=m.artifact_id)""").fetchone()
    if bad:
        raise RuntimeError(f"available artifact {bad[0]!r} has no provenance")
    checks = (
        ("SELECT d.artifact_id FROM (SELECT artifact_id FROM mn_geography_artifacts UNION ALL SELECT artifact_id FROM mn_fixture_artifacts UNION ALL SELECT artifact_id FROM mn_scenario_artifacts UNION ALL SELECT artifact_id FROM mn_model_results UNION ALL SELECT artifact_id FROM mn_score_results UNION ALL SELECT corpus_artifact_id AS artifact_id FROM mn_citation_chunks UNION ALL SELECT artifact_id FROM mn_citation_hits) d JOIN mn_artifact_manifests m USING(artifact_id) WHERE m.availability <> 'available' LIMIT 1", "domain row requires available manifest"),
        ("SELECT m.artifact_id FROM mn_artifact_manifests m WHERE m.availability='unavailable' AND EXISTS (SELECT 1 FROM mn_geography_artifacts d WHERE d.artifact_id=m.artifact_id) LIMIT 1", "unavailable artifact has domain row"),
        ("SELECT g.artifact_id FROM mn_geography_artifacts g WHERE g.coordinate_status='unavailable' AND (g.geometry_wkb IS NOT NULL OR g.lon IS NOT NULL) LIMIT 1", "unavailable geometry has values"),
        ("SELECT f.artifact_id FROM mn_artifact_field_provenance f JOIN mn_artifact_provenance p USING(artifact_id,provenance_ordinal) WHERE p.is_derived AND (f.derivation_method IS NULL OR f.derivation_method='') LIMIT 1", "derived provenance lacks method"),
        ("SELECT artifact_id FROM mn_scenario_artifacts WHERE scenario_label <> 'historical_weather_stress' AND (outcome_artifact_id IS NULL OR matching_method IS NULL OR matching_method='') LIMIT 1", "replay lacks outcome or method"),
        ("SELECT r.artifact_id FROM mn_model_results r JOIN mn_artifact_manifests m USING(artifact_id) WHERE (m.model_mode='aggregate' AND (r.formula IS NULL OR r.base_mva IS NOT NULL OR r.solver_version IS NOT NULL OR r.converter_version IS NOT NULL)) OR (m.model_mode='topology' AND (r.base_mva IS NULL OR r.solver_version IS NULL OR r.converter_version IS NULL)) LIMIT 1", "model mode fields incompatible"),
    )
    for query, message in checks:
        row = con.execute(query).fetchone()
        if row:
            raise RuntimeError(f"artifact {row[0]!r}: {message}")
