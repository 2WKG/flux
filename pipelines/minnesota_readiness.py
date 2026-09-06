"""Decide and publish Minnesota's intake model mode from checked-in evidence.

This module does not ingest anything and does not build a pipeline.  It reads
the Minnesota evidence that is already committed, re-measures it with real
DuckDB queries, evaluates the topology decision gate from
``docs/specs/10-minnesota-demo.md``, and writes one receipt that states the
selected model mode with its limits.

Three rules hold everywhere in this file:

* A number is published only when a query in ``AGGREGATE_QUERIES`` or
  ``STORE_QUERIES`` produced it.  The receipt carries the SQL next to the value
  so a reader can rerun it.
* A missing input is a structured ``unavailable`` entry with a named next step,
  never a default, an estimate, or a silent omission.
* Aggregate mode is a claim ceiling.  ``PROHIBITED_CLAIMS`` is emitted in the
  receipt itself, so a consumer that reads only the JSON still sees it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

FORMAT = "flux-minnesota-readiness-receipt-v1"
STATE_SCOPE = "MN"
AGGREGATE_MANIFEST_FORMAT = "flux-minnesota-aggregate-v1"

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUTS_DIR = ROOT / "pipelines/fixtures/inputs"
DEFAULT_SOURCES_DIR = ROOT / "data/sources"
AGGREGATE_MANIFEST_FILE = "minnesota_aggregate_manifest_v1.json"
CAPACITY_FILE = "mn_county_plant_capacity_2024.csv"
CONTEXT_FILE = "miso_ba_context_2024_h1.csv"
SOURCE_AUTHORITY_LEDGER_FILE = "minnesota-source-authority-ledger-v1.json"

#: Frozen records the gate verdict is checked against.  Each is read at run
#: time; if the statement is gone, this receipt stops rather than publish a
#: verdict the repository no longer supports.
GATE_0_APPROVAL_DOC = "docs/design/minnesota-gate-0-approval.md"
GATE_0_AGGREGATE_STATEMENT = "Aggregate mode is the default and only mode."
SOLVER_FEASIBILITY_DOC = "docs/research/minnesota/solver-network-feasibility.md"
SOLVER_FEASIBILITY_DECISION = "use the aggregate fallback now"
MINNESOTA_DEMO_SPEC = "docs/specs/10-minnesota-demo.md"

#: The ledger class that would contradict an unmet topology gate.  A class that
#: is ``available_limited`` does not: limited retail or line coverage is not a
#: solver-complete electrical network.
CONNECTIVITY_LEDGER_CLASS = "real_electrical_connectivity"
LEDGER_SOLVER_COMPLETE_STATUSES = ("available", "complete")

#: The two independent Minnesota retail service-area counts, reconciled in the
#: receipt rather than silently averaged, corrected, or dropped.
LEDGER_SERVICE_AREA_SOURCE = "mngeo_eusa_featureserver_2026"
MANIFEST_SERVICE_AREA_SOURCE = "mngeo_service_areas_2026"
RETAIL_SERVICE_AREA_CLASS = "retail_service_area"

#: Minnesota county FIPS codes all begin with the state code 27.
MN_FIPS_PREFIX = "27"

#: The county-grain public-context source receipts published by PR #266.  Each
#: file records provider, source URL, retrieval time, license/terms, vintage,
#: per-file digest, and the loader that validated it.
COUNTY_GRAIN_SOURCE_RECEIPTS = (
    "minnesota-tiger-2024.json",
    "minnesota-nri-v1.20.json",
    "minnesota-pudl-eia860-v2026.2.0.json",
    "minnesota-eaglei-2021-2024.json",
    "minnesota-noaa-storm-events-2021-2024.json",
    "minnesota-ntad-military-bases-fy2024.json",
)

#: The decision gate from ``docs/specs/10-minnesota-demo.md``.  Topology mode is
#: selectable only when every item is satisfied by one source with units,
#: version, terms, and per-field provenance.
TOPOLOGY_GATE_ITEMS: tuple[dict[str, Any], ...] = (
    {
        "id": "bus_identity_and_region_mapping",
        "requirement": (
            "Bus identity plus a documented mapping of each bus to Minnesota "
            "geography or region."
        ),
        "status": "unmet",
        "evidence_documents": (SOLVER_FEASIBILITY_DOC,),
        "evidence": (
            "docs/research/minnesota/solver-network-feasibility.md: no public "
            "candidate supplies an inspectable bus set. EIA and HIFLD state "
            "that substation locations are not published, so line routes "
            "cannot establish buses."
        ),
        "next_step": (
            "Obtain an authorized MISO Model Manager / MTEP reliability-model "
            "delivery under CEII NDA, then record bus counts and identifiers "
            "in a source decision record."
        ),
    },
    {
        "id": "branch_identity_and_impedance",
        "requirement": "Branch identity, endpoints, and r/x with units and base.",
        "status": "unmet",
        "evidence_documents": (SOLVER_FEASIBILITY_DOC,),
        "evidence": (
            "docs/research/minnesota/solver-network-feasibility.md: HIFLD "
            "supplies geographic line features only and publishes no r, x, or "
            "electrical base. FERC Form 715 power-flow cases are CEII."
        ),
        "next_step": (
            "Verify r/x, their per-unit base, and endpoint bus references in a "
            "delivered case before any import."
        ),
    },
    {
        "id": "base_mva_ratings_and_allocation",
        "requirement": (
            "System base MVA, branch thermal ratings with units, and "
            "bus-level load/generation allocation."
        ),
        "status": "unmet",
        "evidence_documents": (SOLVER_FEASIBILITY_DOC,),
        "evidence": (
            "docs/research/minnesota/solver-network-feasibility.md: the only "
            "public rating data is the DOE/NREL modelled 2007-2013 static "
            "rating set in amperes, which its publisher says is not a "
            "substitute for operator limits. EIA-930 is balancing-authority "
            "hourly demand, not a nodal allocation."
        ),
        "next_step": (
            "Require normal and emergency ratings with units, plus a "
            "generator/load-to-bus reconciliation, in the delivered case."
        ),
    },
    {
        "id": "terms_permitting_use",
        "requirement": "Terms that permit storing and using the case in this demo.",
        "status": "unmet",
        "evidence_documents": (SOLVER_FEASIBILITY_DOC,),
        "evidence": (
            "MISO restricts FTP reliability-model access to logged-in users "
            "under a CEII NDA/UNDA; FERC classifies Form 715 Parts 2-6 as "
            "CEII. Neither permits redistribution here today."
        ),
        "next_step": "Obtain written legal approval before requesting a delivery.",
    },
    {
        "id": "documented_solver_field_mapping",
        "requirement": "A documented mapping from source fields into the chosen solver.",
        "status": "unmet",
        "evidence_documents": (SOLVER_FEASIBILITY_DOC, MINNESOTA_DEMO_SPEC),
        "evidence": (
            "No Minnesota case is present in this repository, so no field "
            "mapping exists to document. The GridSFM release named in "
            "docs/specs/10-minnesota-demo.md is unreviewed source evidence, "
            "not an accepted artifact, and is not checked in."
        ),
        "next_step": (
            "Review GridSFM 2026_05_07 field-by-field (impedance, base MVA, "
            "ratings, load/generation, units, license) or import a licensed "
            "MISO delivery; record the mapping in a source decision record."
        ),
    },
)

#: Never substitutable for a Minnesota network.
TEXAS_TOPOLOGY_EXCLUSION = (
    "ACTIVSg2000 and every synthetic_* / buses / lines / gens / loads relation "
    "in this repository is a synthetic Texas-shaped test system. It is not "
    "ERCOT and it is not Minnesota. It must never be relabelled, reused, or "
    "spatially re-projected as Minnesota topology."
)

#: Emitted verbatim in the receipt whenever the selected mode is aggregate.
PROHIBITED_CLAIMS = (
    "bus or branch power flow (MW, MVA, Mvar, or per-unit)",
    "line thermal rating, rate_a, ampacity, or line loading percent",
    "DC power flow or any solved network result",
    "N-1 or any contingency-screening conclusion",
    "breaker or line trip",
    "cascade or outage propagation",
    "outage replay or observed-outage attribution",
    "interconnection study, deliverability, or transfer capability",
    "congestion, marginal loss, or locational price",
)

#: The single named aggregate-mode metric this receipt publishes.
STRESS_METRIC = {
    "metric_id": "mn_agg_miso_demand_stress_index_v1",
    "name": "MISO balancing-authority demand stress index",
    "formula": "S(t) = D_MISO(t) / max_tau D_MISO(tau) over the manifest window",
    "units": (
        "dimensionless ratio in (0, 1]; the inputs D_MISO(t) and the window "
        "peak are megawatts (MW)"
    ),
    "reporting_unit": (
        "MISO balancing authority, hourly, UTC end of hour. This is the "
        "smallest unit the source supports."
    ),
    "allocation_assumptions": (
        "None applied. The aggregate manifest records allocation_status = "
        "'unavailable' because no reviewed, complete, non-overlapping "
        "BA-to-service-area crosswalk exists, so no MISO value is allocated "
        "to a Minnesota county, utility, zone, or bus. County plant capacity "
        "is reported separately at county grain and is never used as an "
        "allocation weight for demand."
    ),
    "source_label": "source_backed",
    "source_basis": (
        "EIA-930 Balance file, Balancing Authority == 'MISO', 2024 H1. No "
        "synthetic, modelled, imputed, or interpolated value contributes."
    ),
    "limitations": (
        "MISO spans fifteen states and Manitoba. S(t) is a MISO-wide stress "
        "shape, not Minnesota demand, not a Minnesota load, and not a "
        "transmission-flow, outage, cascade, N-1, or interconnection model. "
        "The window peak is the maximum inside the committed window only; a "
        "different window yields a different denominator."
    ),
}

#: Real queries over the committed aggregate evidence.  ``{capacity}`` and
#: ``{context}`` are substituted with the committed CSV paths.
AGGREGATE_QUERIES: dict[str, str] = {
    "mn_county_capacity_coverage": """
        SELECT count(*) AS counties_with_assigned_plants,
               sum(plant_count) AS assigned_plants,
               round(sum(summer_capacity_mw), 3) AS assigned_summer_capacity_mw,
               count(*) FILTER (WHERE county_fips NOT LIKE '27%') AS non_mn_rows,
               count(*) FILTER (WHERE summer_capacity_mw IS NULL) AS null_capacity_rows
        FROM read_csv_auto('{capacity}', header = true,
                           types = {{'county_fips': 'VARCHAR'}})
    """,
    "miso_context_window": """
        SELECT count(*) AS hours,
               min("UTC Time at End of Hour") AS window_start_utc,
               max("UTC Time at End of Hour") AS window_end_utc,
               count(*) FILTER (WHERE "Demand (MW)" IS NULL) AS null_demand_hours
        FROM read_csv_auto('{context}', header = true)
    """,
    "mn_agg_miso_demand_stress_index_v1": """
        WITH hourly AS (
            SELECT "UTC Time at End of Hour" AS ts, "Demand (MW)" AS demand_mw
            FROM read_csv_auto('{context}', header = true)
            WHERE "Demand (MW)" IS NOT NULL
        ), peak AS (SELECT max(demand_mw) AS peak_mw FROM hourly)
        SELECT (SELECT peak_mw FROM peak) AS window_peak_demand_mw,
               (SELECT ts FROM hourly ORDER BY demand_mw DESC, ts LIMIT 1)
                   AS window_peak_hour_utc,
               round(min(demand_mw) / (SELECT peak_mw FROM peak), 6) AS min_index,
               round(avg(demand_mw) / (SELECT peak_mw FROM peak), 6) AS mean_index,
               round(quantile_cont(demand_mw, 0.95)
                     / (SELECT peak_mw FROM peak), 6) AS p95_index,
               count(*) AS scored_hours
        FROM hourly
    """,
}

#: Real queries over a county-grain store when the operator supplies one.
STORE_QUERIES: dict[str, str] = {
    "counties": "SELECT count(*) FROM counties WHERE county_fips LIKE '27%'",
    "nri_hazards": "SELECT count(*) FROM nri_hazards WHERE county_fips LIKE '27%'",
    "eia_plants": "SELECT count(*) FROM eia_plants WHERE state = 'MN'",
    "storm_events": "SELECT count(*) FROM storm_events WHERE county_fips LIKE '27%'",
    "eaglei_outage_observations": (
        "SELECT count(*) FROM eaglei_outage_observations WHERE county_fips LIKE '27%'"
    ),
    "county_customers": (
        "SELECT count(*) FROM county_customers WHERE county_fips LIKE '27%'"
    ),
    "eaglei_coverage": "SELECT count(*) FROM eaglei_coverage WHERE state = 'MN'",
}

STORE_ABSENT_NEXT_STEPS = (
    (
        "data/duck/*.duckdb is git-ignored, so a fresh clone has no store. "
        "Fetch the raw inputs with "
        "`uv run python datasets/download.py --group demo-mn`."
    ),
    (
        "Run the two `pipelines.build_state_context --state MN` commands "
        "recorded in docs/data/minnesota-p0-curated-source-receipts.md, in "
        "that order, passing --eaglei-source-tz UTC explicitly."
    ),
    (
        "Re-run this receipt with --database <built store> to replace the "
        "unavailable status with measured counts."
    ),
)


class ReadinessError(Exception):
    """A condition that must stop the receipt rather than be defaulted away."""


def _canonical_text_sha256(path: Path) -> str:
    """Hash a tracked text file by its LF content, as the manifest pins it."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _as_row(connection: duckdb.DuckDBPyConnection, sql: str) -> dict[str, Any]:
    cursor = connection.execute(sql)
    columns = [description[0] for description in cursor.description]
    row = cursor.fetchone()
    return {
        column: _utc_isoformat(value) if isinstance(value, datetime) else value
        for column, value in zip(columns, row, strict=True)
    }


def _utc_isoformat(value: datetime) -> str:
    """Render an aware timestamp in UTC; the sources declare a UTC time basis.

    DuckDB returns a ``TIMESTAMP WITH TIME ZONE`` in the reader's local zone, so
    an unconverted ``isoformat`` would publish a local offset for a column whose
    documented basis is UTC end of hour.
    """
    return (value.astimezone(UTC) if value.tzinfo is not None else value).isoformat()


def verify_committed_evidence(
    manifest: dict[str, Any], inputs_dir: Path
) -> list[dict[str, Any]]:
    """Recompute each ``file_sha256`` the aggregate manifest pins.

    A mismatch or a missing file is reported per file; the caller decides.  No
    file is repaired and no digest is rewritten.
    """
    checks: list[dict[str, Any]] = []
    for source in manifest["sources"]:
        for name, expected in sorted(source.get("file_sha256", {}).items()):
            path = inputs_dir / name
            if not path.is_file():
                checks.append(
                    {
                        "file": name,
                        "source_id": source["id"],
                        "status": "unavailable",
                        "expected_sha256": expected,
                        "detail": f"{path} is not present in this checkout",
                    }
                )
                continue
            observed = _canonical_text_sha256(path)
            checks.append(
                {
                    "file": name,
                    "source_id": source["id"],
                    "status": "verified" if observed == expected else "mismatch",
                    "expected_sha256": expected,
                    "observed_sha256": observed,
                }
            )
    return checks


def _repo_relative(path: Path) -> str:
    """Publish a repository-relative path so the receipt is machine-independent."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def measure_aggregate_evidence(inputs_dir: Path) -> dict[str, Any]:
    """Run every aggregate query and return each result beside its SQL.

    The executed SQL carries the absolute input path; the published SQL carries
    the repository-relative one, so the receipt reruns from a checkout root on
    any machine instead of pinning the author's home directory.
    """
    executed = {
        "capacity": (inputs_dir / CAPACITY_FILE).as_posix(),
        "context": (inputs_dir / CONTEXT_FILE).as_posix(),
    }
    published = {
        "capacity": _repo_relative(inputs_dir / CAPACITY_FILE),
        "context": _repo_relative(inputs_dir / CONTEXT_FILE),
    }
    measurements: dict[str, Any] = {}
    with duckdb.connect(":memory:") as connection:
        for name, template in AGGREGATE_QUERIES.items():
            sql = " ".join(template.format(**executed).split())
            measurements[name] = {
                "query": " ".join(template.format(**published).split()),
                "result": _as_row(connection, sql),
            }
    return measurements


def _check_frozen_statement(
    root: Path, relative: str, statement: str
) -> dict[str, Any]:
    """Confirm a frozen record still carries the statement the gate leans on.

    The document is read, not quoted from memory.  A missing file or a revised
    statement raises instead of letting the verdict go stale, which is the whole
    point: the item statuses below are declared, so the declaration has to be
    tied to something that can change underneath it.
    """
    path = root / relative
    if not path.is_file():
        raise ReadinessError(
            f"topology-gate evidence document {relative} is not present in this "
            "checkout; the gate verdict cannot cite a document that is missing"
        )
    text = " ".join(path.read_text(encoding="utf-8").split())
    if statement and " ".join(statement.split()) not in text:
        raise ReadinessError(
            f"{relative} no longer states {statement!r}; the topology-gate "
            "verdict in this receipt is no longer supported by the record it "
            "cites and must be re-evaluated"
        )
    return {
        "document": relative,
        "status": "present",
        "required_statement": statement or None,
        "statement_found": bool(statement),
    }


def evaluate_topology_gate(root: Path = ROOT) -> dict[str, Any]:
    """Return the gate verdict; aggregate mode when any required item is unmet.

    The five item statuses are **declared** by this module from the research in
    ``SOLVER_FEASIBILITY_DOC``; they are not parsed out of it, and this function
    says so in ``verdict_basis``.  What it does derive is the ground under the
    declaration: every cited evidence document must exist, the frozen Gate 0
    approval must still name aggregate as the only mode, and the feasibility
    research must still decide for the aggregate fallback.
    """
    checked: list[dict[str, Any]] = [
        _check_frozen_statement(root, GATE_0_APPROVAL_DOC, GATE_0_AGGREGATE_STATEMENT),
        _check_frozen_statement(
            root, SOLVER_FEASIBILITY_DOC, SOLVER_FEASIBILITY_DECISION
        ),
    ]
    seen = {entry["document"] for entry in checked}
    items: list[dict[str, Any]] = []
    for item in TOPOLOGY_GATE_ITEMS:
        for document in item["evidence_documents"]:
            if document not in seen:
                checked.append(_check_frozen_statement(root, document, ""))
                seen.add(document)
        items.append({**item, "evidence_documents": list(item["evidence_documents"])})
    unmet = [item["id"] for item in items if item["status"] != "met"]
    return {
        "gate_source": f"{MINNESOTA_DEMO_SPEC}, network decision gate",
        "items": items,
        "unmet_items": unmet,
        "topology_mode_available": not unmet,
        "texas_topology_exclusion": TEXAS_TOPOLOGY_EXCLUSION,
        "verdict_basis": {
            "derivation": "declared, not derived",
            "statement": (
                "Each item status above is declared by "
                "pipelines/minnesota_readiness.py from the cited research; no "
                "code parses a status out of a prose document. Three things "
                "are derived and enforced on every run: each cited evidence "
                "document exists, the frozen Gate 0 approval still states "
                f"{GATE_0_AGGREGATE_STATEMENT!r}, and the feasibility research "
                f"still decides {SOLVER_FEASIBILITY_DECISION!r}. If any of "
                "those changes the receipt stops with a ReadinessError instead "
                "of republishing a verdict the record no longer supports."
            ),
            "checked_documents": checked,
        },
    }


def probe_county_grain_store(database: Path | None) -> dict[str, Any]:
    """Measure the county-grain store, or report why it is unavailable."""
    if database is None:
        return {
            "status": "unavailable",
            "reason": "no --database was supplied to this run",
            "published_evidence": (
                "docs/data/minnesota-p0-curated-source-receipts.md carries the "
                "counts measured when PR #266 loaded this store; they are that "
                "run's evidence, not a measurement by this receipt."
            ),
            "next_steps": list(STORE_ABSENT_NEXT_STEPS),
        }
    if not database.is_file():
        return {
            "status": "unavailable",
            "reason": f"{database} does not exist",
            "next_steps": list(STORE_ABSENT_NEXT_STEPS),
        }
    try:
        connection = duckdb.connect(database.as_posix(), read_only=True)
    except duckdb.Error as error:
        return {
            "status": "unreadable",
            "reason": str(error),
            "next_steps": [
                "Close any process holding the store open, then re-run.",
                (
                    "If the schema is a legacy contract, diagnose it with "
                    "`uv run python -m pipelines.preflight --state MN "
                    "--database <path>` and build into a fresh location "
                    "instead."
                ),
            ],
        }
    measurements: dict[str, Any] = {}
    with connection:
        for relation, sql in STORE_QUERIES.items():
            try:
                measurements[relation] = {
                    "query": sql,
                    "minnesota_rows": connection.execute(sql).fetchone()[0],
                }
            except duckdb.Error as error:
                measurements[relation] = {
                    "query": sql,
                    "status": "unavailable",
                    "reason": str(error),
                }
    measured = sorted(
        name for name, result in measurements.items() if "minnesota_rows" in result
    )
    unmeasured = sorted(
        name for name, result in measurements.items() if "minnesota_rows" not in result
    )
    #: A store that answered nothing was not measured, and a store that answered
    #: only part of the contract is not a full measurement.  Reporting either as
    #: ``measured`` would drop the store out of ``readiness.unavailable`` and let
    #: an empty or schema-incompatible database read as a satisfied input.
    if not measured:
        status = "unavailable"
    elif unmeasured:
        status = "partial"
    else:
        status = "measured"
    probe: dict[str, Any] = {
        "status": status,
        "database": database.as_posix(),
        "state_filter": f"county_fips prefix {MN_FIPS_PREFIX} or state = 'MN'",
        "measured_relations": measured,
        "unmeasured_relations": unmeasured,
        "relations": measurements,
    }
    if status != "measured":
        probe["reason"] = (
            f"{len(unmeasured)} of {len(measurements)} required Minnesota "
            f"relations could not be measured in {database}: "
            f"{', '.join(unmeasured)}"
        )
        probe["next_steps"] = [
            (
                "Do not read this store as a satisfied county-grain input: the "
                "relations above were not measured and their counts are "
                "unknown, not zero."
            ),
            *STORE_ABSENT_NEXT_STEPS[1:],
            (
                "Diagnose a legacy or partial schema with `uv run python -m "
                "pipelines.preflight --state MN --database <path>` and build "
                "into a fresh location instead."
            ),
        ]
    return probe


def _source_decision_record(sources_dir: Path) -> dict[str, Any]:
    """Summarise each committed county-grain source receipt without editing it."""
    records: list[dict[str, Any]] = []
    for name in COUNTY_GRAIN_SOURCE_RECEIPTS:
        path = sources_dir / name
        if not path.is_file():
            records.append(
                {
                    "receipt": name,
                    "status": "unavailable",
                    "detail": f"{path} is not present in this checkout",
                    "next_step": "Restore the receipt or remove it from this list.",
                }
            )
            continue
        receipt = json.loads(path.read_text(encoding="utf-8"))
        validation = receipt.get("validation", {})
        records.append(
            {
                "receipt": name,
                "status": "recorded",
                "provider": receipt.get("provider"),
                "source_url": receipt.get("source_url"),
                "retrieved_at": receipt.get("retrieved_at"),
                "version_or_vintage": receipt.get("vintage"),
                "license_or_terms": receipt.get("license_access"),
                "state_scope": validation.get("scope"),
                "loader": validation.get("loader"),
                "validation_result": validation.get("result"),
                "files": sorted(receipt.get("files", {})),
                "uncertainty": receipt.get("uncertainty"),
            }
        )
    return {
        "county_grain_public_context": records,
        "per_field_provenance": (
            "Curated county-grain relations carry the shared provenance "
            "columns defined in pipelines/db.py (PROVENANCE_COLUMNS) and one "
            "ingest_log row per state as '<release>;scope=mn'. The aggregate "
            "evidence carries per-field units, filters, and CRS in "
            f"{AGGREGATE_MANIFEST_FILE}."
        ),
    }


def _source_authority_ledger(
    sources_dir: Path, manifest: dict[str, Any], gate: dict[str, Any]
) -> dict[str, Any]:
    """Cross-check the #224 source-authority ledger against this verdict.

    Two records answer "what is unavailable for Minnesota": this receipt and
    ``minnesota-source-authority-ledger-v1.json``.  They are read together here
    so they cannot drift silently, and the one place their numbers disagree is
    reconciled in the receipt with a named authority instead of being averaged,
    corrected, or dropped.
    """
    path = sources_dir / SOURCE_AUTHORITY_LEDGER_FILE
    if not path.is_file():
        raise ReadinessError(
            f"source-authority ledger not found at {path}; this receipt will "
            "not publish a Minnesota availability verdict without it"
        )
    ledger = json.loads(path.read_text(encoding="utf-8"))
    if ledger.get("state") != STATE_SCOPE:
        raise ReadinessError(
            f"{path} declares state {ledger.get('state')!r}, expected {STATE_SCOPE!r}"
        )
    classes = {
        record["class_id"]: record
        for record in ledger.get("physical_class_coverage", [])
    }
    connectivity = classes.get(CONNECTIVITY_LEDGER_CLASS)
    if connectivity is None:
        raise ReadinessError(
            f"{path} records no {CONNECTIVITY_LEDGER_CLASS!r} class, so it "
            "cannot corroborate or contradict the topology gate"
        )
    if (
        connectivity["status"] in LEDGER_SOLVER_COMPLETE_STATUSES
        and not gate["topology_mode_available"]
    ):
        raise ReadinessError(
            f"{SOURCE_AUTHORITY_LEDGER_FILE} records "
            f"{CONNECTIVITY_LEDGER_CLASS} as {connectivity['status']!r} while "
            f"the topology gate has {len(gate['unmet_items'])} unmet items; "
            "the two Minnesota availability records disagree and must be "
            "reconciled before either is published"
        )

    ledger_source = next(
        (
            record
            for record in ledger.get("source_records", [])
            if record.get("source_id") == LEDGER_SERVICE_AREA_SOURCE
        ),
        None,
    )
    manifest_source = next(
        (
            source
            for source in manifest["sources"]
            if source.get("id") == MANIFEST_SERVICE_AREA_SOURCE
        ),
        None,
    )
    if ledger_source is None or manifest_source is None:
        raise ReadinessError(
            "the retail service-area count cannot be reconciled: "
            f"{LEDGER_SERVICE_AREA_SOURCE!r} in the ledger is "
            f"{'absent' if ledger_source is None else 'present'} and "
            f"{MANIFEST_SERVICE_AREA_SOURCE!r} in the aggregate manifest is "
            f"{'absent' if manifest_source is None else 'present'}"
        )
    ledger_query = ledger_source.get("verified_query", {})
    reconciliation = {
        "subject": "Minnesota retail electric service-area feature count",
        "ledger_source_id": LEDGER_SERVICE_AREA_SOURCE,
        "ledger_count": ledger_query.get("returned_feature_count"),
        "ledger_basis": (
            f"live ArcGIS FeatureServer count query at "
            f"{ledger_query.get('verification', {}).get('retrieved_at')}, "
            f"response pinned in "
            f"{ledger_query.get('verification', {}).get('response_file')}"
        ),
        "manifest_source_id": MANIFEST_SERVICE_AREA_SOURCE,
        "manifest_count": manifest_source.get("rows"),
        "manifest_basis": (
            "rows in the static util_eusa.gpkg publicdownload snapshot recorded "
            f"at manifest retrieved_at {manifest.get('retrieved_at')}"
        ),
        "authoritative_for_source_authority_and_class_coverage": (
            f"data/sources/{SOURCE_AUTHORITY_LEDGER_FILE}. The ledger names "
            "itself authoritative for Minnesota source authority, acquisition "
            "state, and physical-class coverage in its own "
            "related_provenance_artifacts, and its count is a verified live "
            "query with a checked-in response receipt."
        ),
        "authoritative_for_this_receipt": (
            f"{_repo_relative(DEFAULT_INPUTS_DIR / AGGREGATE_MANIFEST_FILE)}. "
            "The manifest pins the artifact this receipt actually measured, so "
            "its count is the one that describes the committed evidence."
        ),
        "why_they_differ": (
            "The two numbers count different artifacts at different times: a "
            "live FeatureServer feature count versus the row count of a static "
            "GeoPackage download. Neither is a count of utilities, grid "
            "assets, feeders, substations, or customers, neither is corrected "
            "into the other, and the difference is recorded rather than "
            "reconciled away."
        ),
    }
    if (
        reconciliation["ledger_count"] is None
        or reconciliation["manifest_count"] is None
    ):
        raise ReadinessError(
            "the retail service-area counts are not both recorded: "
            f"ledger={reconciliation['ledger_count']!r} "
            f"manifest={reconciliation['manifest_count']!r}"
        )
    return {
        "ledger": f"data/sources/{SOURCE_AUTHORITY_LEDGER_FILE}",
        "ledger_id": ledger.get("ledger_id"),
        "retrieved_at": ledger.get("retrieved_at"),
        "truth_boundary": ledger.get("truth_boundary"),
        "physical_class_coverage": [
            {
                "class_id": record["class_id"],
                "status": record["status"],
                "known_count": record.get("known_count"),
                "denominator": record.get("denominator"),
                "reason": record.get("reason"),
            }
            for record in ledger.get("physical_class_coverage", [])
        ],
        "corroborates_topology_gate": (
            connectivity["status"] not in LEDGER_SOLVER_COMPLETE_STATUSES
        ),
        "corroboration_detail": (
            f"{CONNECTIVITY_LEDGER_CLASS} is {connectivity['status']!r} in the "
            "ledger, which is consistent with an unmet topology gate. A "
            "ledger status of "
            f"{' or '.join(repr(s) for s in LEDGER_SOLVER_COMPLETE_STATUSES)} "
            "would contradict it and stops this receipt."
        ),
        "retail_service_area_class": classes.get(RETAIL_SERVICE_AREA_CLASS, {}).get(
            "status"
        ),
        "retail_service_area_count_reconciliation": reconciliation,
    }


def build_receipt(
    *,
    inputs_dir: Path = DEFAULT_INPUTS_DIR,
    sources_dir: Path = DEFAULT_SOURCES_DIR,
    database: Path | None = None,
) -> dict[str, Any]:
    """Assemble the Minnesota readiness receipt from measured evidence only."""
    manifest_path = inputs_dir / AGGREGATE_MANIFEST_FILE
    if not manifest_path.is_file():
        raise ReadinessError(f"aggregate manifest not found at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != AGGREGATE_MANIFEST_FORMAT:
        raise ReadinessError(
            f"aggregate manifest format is {manifest.get('format')!r}, "
            f"expected {AGGREGATE_MANIFEST_FORMAT!r}"
        )

    evidence_checks = verify_committed_evidence(manifest, inputs_dir)
    if failures := [
        check for check in evidence_checks if check["status"] != "verified"
    ]:
        raise ReadinessError(
            "committed aggregate evidence failed identity verification: "
            f"{json.dumps(failures, sort_keys=True)}"
        )

    gate = evaluate_topology_gate()
    mode = "topology" if gate["topology_mode_available"] else "aggregate"
    manifest_mode = manifest.get("model_mode")
    if manifest_mode is None:
        raise ReadinessError(
            f"aggregate manifest {manifest_path} declares no model_mode; this "
            "receipt will not publish a selected mode the manifest does not "
            "also carry"
        )
    if manifest_mode != mode:
        raise ReadinessError(
            f"aggregate manifest declares model_mode {manifest_mode!r} but the "
            f"topology gate selects {mode!r}; the two mode declarations "
            "disagree and must be reconciled before either is published"
        )
    source_authority = _source_authority_ledger(sources_dir, manifest, gate)
    receipt: dict[str, Any] = {
        "format": FORMAT,
        "state_scope": STATE_SCOPE,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "issue": "2WKG-417",
        "selected_model_mode": mode,
        "mode_decision": (
            "Aggregate mode is selected because the topology decision gate has "
            f"{len(gate['unmet_items'])} unmet items and no Minnesota case is "
            "present. Texas/ACTIVSg2000 topology is not a substitute."
        ),
        "topology_gate": gate,
        "source_decision_record": _source_decision_record(sources_dir),
        "source_authority_ledger": source_authority,
        "artifact_manifest": {
            "aggregate_manifest": manifest_path.relative_to(ROOT).as_posix(),
            "aggregate_manifest_retrieved_at": manifest.get("retrieved_at"),
            "model_mode": manifest_mode,
            "allocation_status": manifest.get("allocation_status"),
            "allocation_limit": manifest.get("allocation_limit"),
            "upstream_checksum_status": manifest.get("upstream_checksum_status"),
            "sources": [
                {
                    "id": source["id"],
                    "url": source["url"],
                    "filter": source.get("filter"),
                    "crs": source.get("crs"),
                    "units": source.get("units"),
                    "rows": source.get("rows"),
                    "label": source.get("label"),
                    "limit": source.get("limit") or source.get("geography_limit"),
                }
                for source in manifest["sources"]
            ],
            "committed_evidence_checks": evidence_checks,
        },
        "aggregate_output": {
            "stress_metric": dict(STRESS_METRIC),
            "measurements": measure_aggregate_evidence(inputs_dir),
        },
        "county_grain_store": probe_county_grain_store(database),
    }
    if mode == "aggregate":
        receipt["prohibited_claims"] = list(PROHIBITED_CLAIMS)
        receipt["prohibition_statement"] = (
            "In aggregate mode this artifact must not emit or imply any of "
            "prohibited_claims. Aggregate mode is a Minnesota aggregate stress "
            "model, not a grid twin."
        )
    receipt["readiness"] = {
        "aggregate_mode_ready": True,
        "topology_mode_ready": False,
        "dashboard_release_claim": (
            "This receipt makes no dashboard-release claim. It states a model "
            "mode and its limits."
        ),
        "unavailable": [
            {"input": "county_grain_store", **store}
            for store in [receipt["county_grain_store"]]
            if store["status"] != "measured"
        ],
    }
    if not gate["topology_mode_available"]:
        receipt["readiness"]["unavailable"].append(
            {
                "input": "minnesota_solver_case",
                "status": "unavailable",
                "reason": (
                    "no Minnesota case is present in this repository and no "
                    "licensed delivery has been obtained; the topology gate "
                    f"has {len(gate['unmet_items'])} unmet items "
                    f"({', '.join(gate['unmet_items'])})"
                ),
                "next_steps": [
                    item["next_step"]
                    for item in gate["items"]
                    if item["status"] != "met"
                ],
            }
        )
    if manifest.get("allocation_status") != "available":
        receipt["readiness"]["unavailable"].append(
            {
                "input": "ba_to_service_area_allocation_crosswalk",
                "status": manifest.get("allocation_status"),
                "reason": manifest.get("allocation_limit"),
                "next_steps": [
                    (
                        "Do not allocate. Report MISO balancing-authority "
                        "totals only until a reviewed, complete, "
                        "non-overlapping crosswalk is accepted and versioned."
                    )
                ],
            }
        )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs-dir", type=Path, default=DEFAULT_INPUTS_DIR)
    parser.add_argument("--sources-dir", type=Path, default=DEFAULT_SOURCES_DIR)
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="optional county-grain DuckDB store to measure",
    )
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        receipt = build_receipt(
            inputs_dir=args.inputs_dir,
            sources_dir=args.sources_dir,
            database=args.database,
        )
    except (ReadinessError, OSError, ValueError, duckdb.Error) as error:
        json.dump({"error": str(error), "state_scope": STATE_SCOPE}, sys.stderr)
        sys.stderr.write("\n")
        return 2
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
