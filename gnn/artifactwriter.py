"""Crash-resumable, source-safe JSONL artifact writing for GNN samples."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from gnn.contracts import (
    SAMPLE_SCHEMA_VERSION,
    PlannedSample,
    SamplingError,
    TrainingSample,
)
from gnn.normalization import fit_graph_normalization
from gnn.sampler import canonical_json

ARTIFACT_SCHEMA_VERSION = "gnn-training-artifact/v1"
# ``graph`` is the immutable graph-export companion for this sample artifact.
# It is deliberately an owned directory rather than a link back into the source
# tree: a training run must be portable without making the DuckDB writable.
_OWNED_FILES = {
    "manifest.json",
    "normalization.json",
    "samples.jsonl",
    "timings.jsonl",
    "split.json",
    "graph",
}


def split_by_contingency(
    plans: Iterable[PlannedSample], *, seed: int, held_out_fraction: float
) -> dict[str, Any]:
    """Assign complete contingency families to train or held-out deterministically."""
    if not 0.0 < float(held_out_fraction) < 1.0:
        raise SamplingError("held-out fraction must be strictly between zero and one")
    by_group: dict[str, list[PlannedSample]] = {}
    for plan in plans:
        by_group.setdefault(plan.group_key, []).append(plan)
    if not by_group:
        raise SamplingError("cannot split an empty sample plan")
    ranked = sorted(
        by_group,
        key=lambda key: hashlib.sha256(f"{int(seed)}\x1f{key}".encode()).hexdigest(),
    )
    held_out_count = round(len(ranked) * float(held_out_fraction))
    if len(ranked) > 1:
        held_out_count = min(max(held_out_count, 1), len(ranked) - 1)
    else:
        held_out_count = 0
    held_out_groups = set(ranked[:held_out_count])
    train, held_out = [], []
    for group in sorted(by_group):
        destination = held_out if group in held_out_groups else train
        destination.extend(sorted(by_group[group], key=lambda item: item.sample_index))
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "holdout_axes": {
            "contingency_family": {
                "group_field": "group_key",
                "seed": int(seed),
                "held_out_fraction": float(held_out_fraction),
                "temporal_holdout": "not_claimed",
            }
        },
        "train_sample_ids": [item.sample_index for item in train],
        "held_out_sample_ids": [item.sample_index for item in held_out],
        "train_group_keys": sorted({item.group_key for item in train}),
        "held_out_group_keys": sorted({item.group_key for item in held_out}),
    }


class ArtifactWriter:
    """Append samples safely and resume only a matching in-progress generation."""

    def __init__(
        self, out_dir: str | Path, *, source_db: str | Path, identity: dict[str, Any]
    ):
        self.source = Path(source_db).resolve()
        self.target = Path(out_dir).resolve()
        self.identity = identity
        self._validate_target()
        self.target.mkdir(parents=True, exist_ok=True)
        self.samples_path = self.target / "samples.jsonl"
        self.timings_path = self.target / "timings.jsonl"
        self.manifest_path = self.target / "manifest.json"
        self._existing_ids = self._prepare_or_resume()

    @property
    def existing_ids(self) -> frozenset[str]:
        return frozenset(self._existing_ids)

    def append(self, sample: TrainingSample) -> bool:
        """Persist a sample once.  Returns false when the existing row is reused."""
        if sample.sample_id in self._existing_ids:
            return False
        payload = canonical_json(sample.json()).encode("utf-8") + b"\n"
        with self.samples_path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Wall-clock timings live beside the samples, never inside them, so that
        # samples.jsonl and manifest.samples_sha256 are byte-reproducible.
        timing = canonical_json(sample.timing_json()).encode("utf-8") + b"\n"
        with self.timings_path.open("ab") as handle:
            handle.write(timing)
            handle.flush()
            os.fsync(handle.fileno())
        self._existing_ids.add(sample.sample_id)
        return True

    def ensure_graph_dataset(self) -> dict[str, Any]:
        """Create or verify the graph-export companion for this artifact.

        The graph exporter is intentionally imported here instead of at module
        import time.  That keeps this package usable by the solver-only test
        fixtures while making a real training artifact fail loudly if the
        graph-export contract has not been integrated.
        """
        graph_dir = self.target / "graph"
        if graph_dir.exists():
            if graph_dir.is_symlink() or not graph_dir.is_dir():
                raise SamplingError("training graph dataset must be a real directory")
            return _verified_graph_manifest(graph_dir)
        try:
            from pipelines.graph_export import export_texas_graph_dataset
        except ImportError as exc:
            raise SamplingError(
                "training generation requires the current pipelines.graph_export contract"
            ) from exc
        try:
            export_texas_graph_dataset(self.source, graph_dir)
        except Exception as exc:
            raise SamplingError(
                f"unable to export training graph dataset: {exc}"
            ) from exc
        return _verified_graph_manifest(graph_dir)

    def finish(
        self,
        split: dict[str, Any],
        *,
        planned_count: int,
        graph_dataset: dict[str, Any],
    ) -> dict[str, Any]:
        """Publish the split and completed manifest after all planned rows exist."""
        records = self._read_records()
        if len(records) != int(planned_count):
            raise SamplingError(
                f"cannot finish incomplete artifact: expected {planned_count}, found {len(records)}"
            )
        labelled_count = sum(record["status"] == "labelled" for record in records)
        if not labelled_count:
            raise SamplingError(
                "refusing to publish a complete artifact with zero labelled samples"
            )
        index_to_id = {
            record["plan"]["sample_index"]: record["sample_id"] for record in records
        }
        split = dict(split)
        split["train_sample_ids"] = [
            index_to_id[index] for index in split["train_sample_ids"]
        ]
        split["held_out_sample_ids"] = [
            index_to_id[index] for index in split["held_out_sample_ids"]
        ]
        _atomic_json(self.target / "split.json", split)
        normalization = fit_graph_normalization(
            self.target / "graph", graph_dataset, split
        )
        _atomic_json(self.target / "normalization.json", normalization)
        manifest = {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "sample_schema_version": SAMPLE_SCHEMA_VERSION,
            "generation_status": "complete",
            "identity": self.identity,
            "planned_count": int(planned_count),
            "labelled_count": labelled_count,
            "failed_count": sum(record["status"] == "failed" for record in records),
            # timings.jsonl is deliberately absent from the digest set: it holds
            # wall-clock values, which are not reproducible.
            "samples_sha256": _sha256(self.samples_path),
            "split_sha256": _sha256(self.target / "split.json"),
            "normalization_sha256": _sha256(self.target / "normalization.json"),
            "source_database": str(self.source),
            "graph_dataset": graph_dataset,
        }
        _atomic_json(self.manifest_path, manifest)
        return manifest

    def _validate_target(self) -> None:
        if self.target == self.source or self.source.is_relative_to(self.target):
            raise SamplingError(
                "training artifact output must not contain the source database"
            )
        if self.target.exists() and not self.target.is_dir():
            raise SamplingError("training artifact output must be a directory")
        if self.target.exists() and not self.target.is_symlink():
            names = {entry.name for entry in self.target.iterdir()}
            if names and not names.issubset(_OWNED_FILES):
                raise SamplingError(
                    "refusing to write into a non-training-artifact directory"
                )
        if self.target.is_symlink():
            raise SamplingError(
                "training artifact output directory must not be a symlink"
            )

    def _prepare_or_resume(self) -> set[str]:
        if self.manifest_path.exists():
            try:
                manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SamplingError("existing artifact manifest is invalid") from exc
            if manifest.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
                raise SamplingError("existing artifact has an incompatible schema")
            if manifest.get("identity") != self.identity:
                raise SamplingError(
                    "existing artifact identity does not match this generation"
                )
        else:
            _atomic_json(
                self.manifest_path,
                {
                    "schema_version": ARTIFACT_SCHEMA_VERSION,
                    "sample_schema_version": SAMPLE_SCHEMA_VERSION,
                    "generation_status": "in_progress",
                    "identity": self.identity,
                    "source_database": str(self.source),
                },
            )
        return {record["sample_id"] for record in self._read_records()}

    def _read_records(self) -> list[dict[str, Any]]:
        if not self.samples_path.exists():
            return []
        records: list[dict[str, Any]] = []
        ids: set[str] = set()
        for line_number, line in enumerate(
            self.samples_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SamplingError(
                    f"invalid JSONL record at line {line_number}"
                ) from exc
            sample_id = record.get("sample_id")
            if not isinstance(sample_id, str) or sample_id in ids:
                raise SamplingError(
                    f"invalid or duplicate sample ID at line {line_number}"
                )
            ids.add(sample_id)
            records.append(record)
        return records


def _atomic_json(path: Path, value: object) -> None:
    payload = canonical_json(value).encode("utf-8") + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _verified_graph_manifest(graph_dir: Path) -> dict[str, Any]:
    """Return the graph-export binding after validating its published hashes."""
    manifest_path = graph_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SamplingError("training graph dataset has no valid manifest") from exc
    if manifest.get("schema_version") != "1.0.0":
        raise SamplingError("training graph dataset has an unsupported schema version")
    if manifest.get("topology_label") != "synthetic (ACTIVSg2000)":
        raise SamplingError("training graph dataset has an unexpected topology label")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != {"nodes.json", "edges.json"}:
        raise SamplingError("training graph dataset manifest has an invalid file set")
    for name, expected in files.items():
        if not isinstance(expected, str) or _sha256(graph_dir / name) != expected:
            raise SamplingError(f"training graph dataset hash mismatch for {name}")
    return {
        "dataset_sha256": manifest.get("dataset_sha256"),
        "manifest_sha256": _sha256(manifest_path),
        "schema_version": manifest["schema_version"],
        "topology_label": manifest["topology_label"],
        "files": dict(sorted(files.items())),
    }
