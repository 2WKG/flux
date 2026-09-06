"""Versioned, source-qualified physical-grid inventory artifacts.

This module is deliberately below the API boundary.  State ingest lanes write one
validated artifact; read routes may serialize its tables, but must not promote a
synthetic fixture or an unknown coverage denominator into a physical-grid claim.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from typing import Any

import duckdb
from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely.geometry import shape

CONTRACT_VERSION = "1.0.0"
ARTIFACT_KIND = "physical_inventory"
INVENTORY_MODES = frozenset({"physical_observed", "fixture", "synthetic"})
MODEL_MODES = frozenset({"none", "source_backed", "synthetic", "aggregate"})
ASSET_CLASSES = frozenset({"line", "cable", "substation", "terminal", "transformer", "switchgear", "generation", "storage", "distribution_feeder", "distribution_equipment", "support", "pole", "tower", "load", "critical_facility", "intertie"})
GEOMETRY_TYPES = frozenset({"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"})
COVERAGE_STATUSES = frozenset({"complete", "partial", "unknown", "unavailable"})

DDL = (
    "CREATE TABLE physical_inventory_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE physical_inventory_manifests (artifact_id TEXT PRIMARY KEY, contract_version TEXT NOT NULL,
    geography_id TEXT NOT NULL, artifact_version TEXT NOT NULL, canonical_json TEXT NOT NULL, inventory_mode TEXT NOT NULL CHECK(inventory_mode IN ('physical_observed','fixture','synthetic')),
    electrical_model_mode TEXT NOT NULL CHECK(electrical_model_mode IN ('none','source_backed','synthetic','aggregate')),
    created_at TIMESTAMP NOT NULL, content_sha256 TEXT NOT NULL CHECK(regexp_full_match(content_sha256, '[0-9a-f]{64}')))""",
    """CREATE TABLE physical_inventory_sources (artifact_id TEXT NOT NULL REFERENCES physical_inventory_manifests(artifact_id), source_id TEXT NOT NULL,
    authority TEXT NOT NULL, source_ref TEXT NOT NULL, source_version TEXT NOT NULL, retrieved_at TIMESTAMP NOT NULL,
    license_or_terms TEXT NOT NULL, content_sha256 TEXT NOT NULL CHECK(regexp_full_match(content_sha256, '[0-9a-f]{64}')), PRIMARY KEY(artifact_id,source_id))""",
    """CREATE TABLE physical_assets (artifact_id TEXT NOT NULL REFERENCES physical_inventory_manifests(artifact_id), asset_id TEXT NOT NULL,
    asset_class TEXT NOT NULL, asset_kind TEXT NOT NULL, source_id TEXT NOT NULL, source_record_id TEXT NOT NULL,
    geometry_geojson JSON, geometry_crs TEXT, geometry_precision_m DOUBLE, geometry_accuracy_basis TEXT, geometry_derivation_method TEXT,
    geometry_status TEXT NOT NULL CHECK(geometry_status IN ('source','derived','unavailable')), PRIMARY KEY(artifact_id,asset_id),
    FOREIGN KEY(artifact_id,source_id) REFERENCES physical_inventory_sources(artifact_id,source_id))""",
    """CREATE TABLE physical_asset_terminals (artifact_id TEXT NOT NULL, terminal_id TEXT NOT NULL, asset_id TEXT NOT NULL,
    source_id TEXT NOT NULL, source_record_id TEXT NOT NULL, PRIMARY KEY(artifact_id,terminal_id),
    FOREIGN KEY(artifact_id,asset_id) REFERENCES physical_assets(artifact_id,asset_id), FOREIGN KEY(artifact_id,source_id) REFERENCES physical_inventory_sources(artifact_id,source_id))""",
    """CREATE TABLE physical_connectivity_edges (artifact_id TEXT NOT NULL, edge_id TEXT NOT NULL, from_terminal_id TEXT NOT NULL,
    to_terminal_id TEXT NOT NULL, source_id TEXT NOT NULL, source_record_id TEXT NOT NULL, PRIMARY KEY(artifact_id,edge_id),
    FOREIGN KEY(artifact_id,from_terminal_id) REFERENCES physical_asset_terminals(artifact_id,terminal_id),
    FOREIGN KEY(artifact_id,to_terminal_id) REFERENCES physical_asset_terminals(artifact_id,terminal_id), FOREIGN KEY(artifact_id,source_id) REFERENCES physical_inventory_sources(artifact_id,source_id))""",
    """CREATE TABLE physical_coverage (artifact_id TEXT NOT NULL REFERENCES physical_inventory_manifests(artifact_id), asset_class TEXT NOT NULL,
    scope_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('complete','partial','unknown','unavailable')), observed_count BIGINT NOT NULL CHECK(observed_count >= 0),
    denominator_count BIGINT CHECK(denominator_count >= 0), unknown_count BIGINT CHECK(unknown_count >= 0), unavailable_count BIGINT CHECK(unavailable_count >= 0), denominator_basis TEXT NOT NULL, source_scope TEXT NOT NULL, reason TEXT NOT NULL,
    PRIMARY KEY(artifact_id,asset_class,scope_id))""",
)

class PhysicalInventoryError(ValueError):
    pass

def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def artifact_sha256(artifact: dict[str, Any]) -> str:
    """Digest the complete artifact excluding its self-referential digest field."""
    copied = dict(artifact)
    copied.pop("content_sha256", None)
    return hashlib.sha256(_canonical(copied).encode()).hexdigest()

def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str): raise PhysicalInventoryError(f"{field} must be an ISO-8601 timestamp")
    try: parsed = datetime.fromisoformat(value)
    except ValueError as exc: raise PhysicalInventoryError(f"{field} is not ISO-8601") from exc
    if parsed.tzinfo is None: raise PhysicalInventoryError(f"{field} must include an offset")
    return parsed.astimezone(UTC).replace(tzinfo=None)

def _sha(value: Any, field: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None: raise PhysicalInventoryError(f"{field} must be a lowercase SHA-256")

def _geometry(value: Any, status: str, crs: Any, prefix: str) -> None:
    if status == "unavailable":
        if value is not None: raise PhysicalInventoryError(f"{prefix}.geometry must be null when unavailable")
        return
    if not isinstance(value, dict) or value.get("type") not in GEOMETRY_TYPES: raise PhysicalInventoryError(f"{prefix}.geometry must be a non-empty GeoJSON physical geometry")
    try: geom = shape(value)
    except Exception as exc: raise PhysicalInventoryError(f"{prefix}.geometry is invalid GeoJSON") from exc
    if geom.is_empty or not geom.is_valid: raise PhysicalInventoryError(f"{prefix}.geometry must be valid and non-empty")
    west, south, east, north = geom.bounds
    if not all(math.isfinite(value) for value in (west, south, east, north)) or crs == "EPSG:4326" and not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
        raise PhysicalInventoryError(f"{prefix}.geometry has invalid EPSG:4326 coordinates")

def _registered_crs(value: Any, prefix: str) -> None:
    """Accept only a real, explicit EPSG or ESRI authority code."""
    if not isinstance(value, str) or re.fullmatch(r"(?:EPSG|ESRI):\d+", value) is None:
        raise PhysicalInventoryError(f"{prefix}.geometry_crs must be an explicit registered EPSG or ESRI CRS")
    authority, code = value.split(":", 1)
    try:
        resolved = CRS.from_authority(authority, code).to_authority()
    except CRSError as exc:
        raise PhysicalInventoryError(f"{prefix}.geometry_crs is not a registered CRS") from exc
    if resolved != (authority, code):
        raise PhysicalInventoryError(f"{prefix}.geometry_crs must retain its declared authority")

def validate_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Validate a complete immutable physical inventory artifact and return it."""
    required = {"artifact_id","contract_version","geography_id","artifact_version","inventory_mode","electrical_model_mode","created_at","content_sha256","sources","assets","terminals","connectivity_edges","coverage"}
    if set(artifact) != required: raise PhysicalInventoryError(f"artifact fields must be exactly {sorted(required)!r}")
    if artifact["contract_version"] != CONTRACT_VERSION: raise PhysicalInventoryError("unsupported physical inventory contract_version")
    geo, version = artifact["geography_id"], artifact["artifact_version"]
    if not isinstance(geo, str) or not geo or not isinstance(version, str) or re.fullmatch(r"\d+\.\d+\.\d+", version) is None: raise PhysicalInventoryError("geography_id and semantic artifact_version are required")
    if artifact["artifact_id"] != f"{geo}:physical-inventory:{version}": raise PhysicalInventoryError("artifact_id must be '<geography_id>:physical-inventory:<version>'")
    if artifact["inventory_mode"] not in INVENTORY_MODES or artifact["electrical_model_mode"] not in MODEL_MODES: raise PhysicalInventoryError("invalid inventory or electrical model mode")
    _timestamp(artifact["created_at"], "created_at"); _sha(artifact["content_sha256"], "content_sha256")
    if artifact["content_sha256"] != artifact_sha256(artifact): raise PhysicalInventoryError("content_sha256 does not match canonical artifact")
    sources = artifact["sources"]
    if not isinstance(sources, list) or not sources: raise PhysicalInventoryError("sources must be a non-empty array")
    source_ids=set()
    for i, row in enumerate(sources):
        if set(row) != {"source_id","authority","source_ref","source_version","retrieved_at","license_or_terms","content_sha256"}: raise PhysicalInventoryError(f"sources[{i}] has incompatible fields")
        if not all(isinstance(row[k],str) and row[k] for k in ("source_id","authority","source_ref","source_version","license_or_terms")) or row["source_id"] in source_ids: raise PhysicalInventoryError(f"sources[{i}] has invalid identity")
        source_ids.add(row["source_id"]); _timestamp(row["retrieved_at"],f"sources[{i}].retrieved_at"); _sha(row["content_sha256"],f"sources[{i}].content_sha256")
    assets=artifact["assets"]
    if not isinstance(assets,list): raise PhysicalInventoryError("assets must be an array")
    asset_ids=set()
    for i,row in enumerate(assets):
        need={"asset_id","asset_class","asset_kind","source_id","source_record_id","geometry","geometry_crs","geometry_precision_m","geometry_accuracy_basis","geometry_derivation_method","geometry_status"}
        if set(row)!=need: raise PhysicalInventoryError(f"assets[{i}] has incompatible fields")
        if not all(isinstance(row[k],str) and row[k] for k in ("asset_id","asset_kind","source_id","source_record_id","geometry_status")) or row["asset_id"] in asset_ids or row["asset_class"] not in ASSET_CLASSES or row["source_id"] not in source_ids: raise PhysicalInventoryError(f"assets[{i}] has invalid identity/class/source")
        asset_ids.add(row["asset_id"])
        if row["geometry_status"] not in {"source","derived","unavailable"}: raise PhysicalInventoryError(f"assets[{i}] invalid geometry_status")
        if row["geometry_status"] == "unavailable" and any(row[key] is not None for key in ("geometry_crs","geometry_precision_m","geometry_accuracy_basis","geometry_derivation_method")): raise PhysicalInventoryError(f"assets[{i}] unavailable geometry must not have CRS, precision, accuracy, or derivation values")
        if row["geometry_status"] != "unavailable" and (row["geometry_precision_m"] is not None and (not isinstance(row["geometry_precision_m"],(int,float)) or isinstance(row["geometry_precision_m"],bool) or row["geometry_precision_m"] < 0) or not isinstance(row["geometry_accuracy_basis"],str) or not row["geometry_accuracy_basis"]): raise PhysicalInventoryError(f"assets[{i}] needs an accuracy basis; numeric precision may be null only when unknown")
        if row["geometry_status"] != "unavailable": _registered_crs(row["geometry_crs"], f"assets[{i}]")
        if row["geometry_status"] == "derived" and (not isinstance(row["geometry_derivation_method"],str) or not row["geometry_derivation_method"]): raise PhysicalInventoryError(f"assets[{i}] derived geometry needs a derivation method")
        if row["geometry_status"] == "source" and row["geometry_derivation_method"] is not None: raise PhysicalInventoryError(f"assets[{i}] source geometry must not claim a derivation method")
        _geometry(row["geometry"],row["geometry_status"],row["geometry_crs"],f"assets[{i}]")
    if not isinstance(artifact["terminals"], list) or not isinstance(artifact["connectivity_edges"], list) or not isinstance(artifact["coverage"], list): raise PhysicalInventoryError("terminals, connectivity_edges, and coverage must be arrays")
    terminal_ids=set()
    for i,row in enumerate(artifact["terminals"]):
        if set(row)!={"terminal_id","asset_id","source_id","source_record_id"} or not all(isinstance(row[k],str) and row[k] for k in row) or row["terminal_id"] in terminal_ids or row["asset_id"] not in asset_ids or row["source_id"] not in source_ids: raise PhysicalInventoryError(f"terminals[{i}] must be a source-backed terminal for an asset")
        terminal_ids.add(row["terminal_id"])
    edge_ids=set()
    for i,row in enumerate(artifact["connectivity_edges"]):
        if set(row)!={"edge_id","from_terminal_id","to_terminal_id","source_id","source_record_id"} or not all(isinstance(row[k],str) and row[k] for k in row) or row["edge_id"] in edge_ids or row["from_terminal_id"] not in terminal_ids or row["to_terminal_id"] not in terminal_ids or row["from_terminal_id"]==row["to_terminal_id"] or row["source_id"] not in source_ids: raise PhysicalInventoryError(f"connectivity_edges[{i}] must join two sourced distinct terminals")
        edge_ids.add(row["edge_id"])
    coverage_keys=set()
    for i,row in enumerate(artifact["coverage"]):
        need={"asset_class","scope_id","status","observed_count","denominator_count","unknown_count","unavailable_count","denominator_basis","source_scope","reason"}
        if set(row)!=need or row["asset_class"] not in ASSET_CLASSES or not isinstance(row["scope_id"],str) or not row["scope_id"] or row["status"] not in COVERAGE_STATUSES or not isinstance(row["observed_count"],int) or isinstance(row["observed_count"],bool) or row["observed_count"]<0 or any(row[key] is not None and (not isinstance(row[key],int) or isinstance(row[key],bool) or row[key]<0) for key in ("unknown_count","unavailable_count")) or not all(isinstance(row[k],str) and row[k] for k in ("denominator_basis","source_scope","reason")): raise PhysicalInventoryError(f"coverage[{i}] has invalid class/status/counts")
        denom=row["denominator_count"]
        if denom is not None and (not isinstance(denom,int) or isinstance(denom,bool) or denom<0): raise PhysicalInventoryError(f"coverage[{i}].denominator_count must be non-negative or null")
        if row["status"]=="complete" and (denom is None or row["unknown_count"] != 0 or row["unavailable_count"] != 0 or row["observed_count"] != denom): raise PhysicalInventoryError(f"coverage[{i}] cannot claim complete without exact reconciled counts")
        key=(row["asset_class"],row["scope_id"])
        if key in coverage_keys: raise PhysicalInventoryError(f"coverage[{i}] duplicates class/scope")
        coverage_keys.add(key)
    if not coverage_keys: raise PhysicalInventoryError("coverage must declare at least one class/scope")
    missing_classes={row["asset_class"] for row in assets} - {key[0] for key in coverage_keys}
    if missing_classes: raise PhysicalInventoryError(f"coverage is required for observed asset classes: {sorted(missing_classes)!r}")
    return artifact

def ensure_physical_inventory_schema(con: duckdb.DuckDBPyConnection) -> None:
    existing={r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "physical_inventory_schema_meta" in existing:
        value=con.execute("SELECT value FROM physical_inventory_schema_meta WHERE key='contract_version'").fetchone()
        if value is None or value[0]!=CONTRACT_VERSION: raise RuntimeError("physical inventory schema requires an explicit migration")
    elif any(name.startswith("physical_") for name in existing): raise RuntimeError("physical inventory schema metadata is absent; migrate explicitly")
    con.execute("BEGIN")
    try:
        for statement in DDL: con.execute(statement.replace("CREATE TABLE ","CREATE TABLE IF NOT EXISTS ",1))
        if "physical_inventory_schema_meta" not in existing: con.execute("INSERT INTO physical_inventory_schema_meta VALUES ('contract_version', ?)",[CONTRACT_VERSION])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK"); raise

def write_artifact(con: duckdb.DuckDBPyConnection, artifact: dict[str, Any]) -> str:
    """Persist a validated artifact once; a repeat must be byte-for-byte identical."""
    validate_artifact(artifact); ensure_physical_inventory_schema(con)
    aid=artifact["artifact_id"]
    existing=con.execute("SELECT content_sha256 FROM physical_inventory_manifests WHERE artifact_id=?",[aid]).fetchone()
    if existing:
        if existing[0]!=artifact["content_sha256"]: raise PhysicalInventoryError(f"artifact {aid!r} conflicts with persisted content")
        return aid
    con.execute("BEGIN")
    try:
        con.execute("INSERT INTO physical_inventory_manifests VALUES (?,?,?,?,?,?,?,?,?)",[aid,artifact["contract_version"],artifact["geography_id"],artifact["artifact_version"],_canonical(artifact),artifact["inventory_mode"],artifact["electrical_model_mode"],_timestamp(artifact["created_at"],"created_at"),artifact["content_sha256"]])
        for row in artifact["sources"]: con.execute("INSERT INTO physical_inventory_sources VALUES (?,?,?,?,?,?,?,?)",[aid,row["source_id"],row["authority"],row["source_ref"],row["source_version"],_timestamp(row["retrieved_at"],"retrieved_at"),row["license_or_terms"],row["content_sha256"]])
        for row in artifact["assets"]: con.execute("INSERT INTO physical_assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",[aid,row["asset_id"],row["asset_class"],row["asset_kind"],row["source_id"],row["source_record_id"],_canonical(row["geometry"]) if row["geometry"] is not None else None,row["geometry_crs"],row["geometry_precision_m"],row["geometry_accuracy_basis"],row["geometry_derivation_method"],row["geometry_status"]])
        for row in artifact["terminals"]: con.execute("INSERT INTO physical_asset_terminals VALUES (?,?,?,?,?)",[aid,row["terminal_id"],row["asset_id"],row["source_id"],row["source_record_id"]])
        for row in artifact["connectivity_edges"]: con.execute("INSERT INTO physical_connectivity_edges VALUES (?,?,?,?,?,?)",[aid,row["edge_id"],row["from_terminal_id"],row["to_terminal_id"],row["source_id"],row["source_record_id"]])
        for row in artifact["coverage"]: con.execute("INSERT INTO physical_coverage VALUES (?,?,?,?,?,?,?,?,?,?,?)",[aid,row["asset_class"],row["scope_id"],row["status"],row["observed_count"],row["denominator_count"],row["unknown_count"],row["unavailable_count"],row["denominator_basis"],row["source_scope"],row["reason"]])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK"); raise
    return aid
