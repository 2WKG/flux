"""Labelled training-sample generation for the GNN cascade surrogate.

This package produces ``(network state, contingency) -> (solver outcome)``
rows by calling the existing DC solver in :mod:`twin.cascade` as the labeller.
It is the *data* half of the surrogate lane and deliberately imports no
machine-learning framework: ``torch`` must never become a hard dependency of
the ingest/simulation pipeline, so model code lives elsewhere and reads the
JSONL emitted here.

Nothing in this package invents a physical quantity.  A missing branch rating,
a missing hourly demand observation, and a failed solve are each recorded as
missing or failed with a reason; none of them is replaced with a plausible
default.  All topology is synthetic ACTIVSg2000 and every emitted row says so.
"""

from gnn.contracts import (
    BranchFlow,
    HourPoint,
    PlannedSample,
    SampleLabels,
    SamplingError,
    SamplingUnavailableError,
    TrainingSample,
)

__all__ = [
    "BranchFlow",
    "GenerationConfig",
    "HourPoint",
    "PlannedSample",
    "SampleLabels",
    "SamplerConfig",
    "SamplingError",
    "SamplingUnavailableError",
    "TrainingSample",
    "generate_training_samples",
]


def __getattr__(name: str):
    """Delay solver imports until a caller asks to generate or label samples."""
    if name in {"GenerationConfig", "generate_training_samples"}:
        from gnn.generate import GenerationConfig, generate_training_samples

        return {
            "GenerationConfig": GenerationConfig,
            "generate_training_samples": generate_training_samples,
        }[name]
    if name == "SamplerConfig":
        from gnn.sampler import SamplerConfig

        return SamplerConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
