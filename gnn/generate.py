"""CLI and orchestration for deterministic DC-solver-labelled sample generation."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from gnn.artifactwriter import ArtifactWriter, split_by_contingency
from gnn.contracts import SamplingError
from gnn.hours import DEFAULT_BA_CODE, hourly_demand_profile, select_hours
from gnn.label import label_sample, require_solver_backend
from gnn.sampler import SamplerConfig, build_plan, canonical_json


@dataclass(frozen=True)
class GenerationConfig:
    seed: int = 490
    hours: int = 3
    held_out_fraction: float = 0.2
    ba_code: str = DEFAULT_BA_CODE
    scale_dispatch: bool = True
    sampler: SamplerConfig = field(default_factory=SamplerConfig)

    def validate(self) -> None:
        if int(self.hours) < 1:
            raise SamplingError("hour count must be at least one")
        self.sampler.validate()

    def json(self) -> dict[str, Any]:
        value = asdict(self)
        value["sampler"] = self.sampler.json()
        return value


def generate_training_samples(
    db_path: str | Path,
    out_dir: str | Path,
    *,
    config: GenerationConfig | None = None,
) -> dict[str, Any]:
    """Generate or resume a bounded sample artifact without modifying DuckDB."""
    policy = config or GenerationConfig()
    policy.validate()
    # An unimportable solver backend is an environment failure. Refuse before a
    # single row is written rather than recording every row as a failed label.
    require_solver_backend()
    source = Path(db_path).resolve()
    profile = hourly_demand_profile(source, ba_code=policy.ba_code)
    hours = select_hours(profile, count=policy.hours, seed=policy.seed)
    if len(hours) != policy.hours:
        raise SamplingError(
            f"only {len(hours)} observed hours are available; requested {policy.hours}"
        )
    from twin.build import build_network, network_summary

    net = build_network(source)
    plans = build_plan(net, hours, seed=policy.seed, config=policy.sampler)
    scenario_identity = {
        "network_input_sha256": net.get("flux_input_sha256"),
        "network_summary": network_summary(net),
        "demand_hours": [point.json() for point in hours],
    }
    identity = {
        "config": policy.json(),
        "source_database_sha256": _sha256_file(source),
        "scenario_identity": scenario_identity,
        "plan_sha256": hashlib.sha256(
            canonical_json([plan.json() for plan in plans]).encode()
        ).hexdigest(),
    }
    writer = ArtifactWriter(out_dir, source_db=source, identity=identity)
    graph_dataset = writer.ensure_graph_dataset()
    by_hour = {point.hour: point for point in hours}
    for plan in plans:
        sample = label_sample(
            net,
            plan,
            by_hour[plan.hour],
            seed=policy.seed,
            scenario_id="observed_ba_load",
            scenario_identity=scenario_identity,
            ba_code=policy.ba_code,
            scale_dispatch=policy.scale_dispatch,
        )
        writer.append(sample)
    split = split_by_contingency(
        plans, seed=policy.seed, held_out_fraction=policy.held_out_fraction
    )
    return writer.finish(
        split,
        planned_count=len(plans),
        graph_dataset=graph_dataset,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/duck/grid.duckdb")
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=490)
    parser.add_argument("--hours", type=int, default=3)
    parser.add_argument("--ba-code", default=DEFAULT_BA_CODE)
    parser.add_argument("--held-out-fraction", type=float, default=0.2)
    parser.add_argument("--n1-per-hour", type=int, default=2)
    parser.add_argument("--n2-per-hour", type=int, default=1)
    parser.add_argument("--placement-per-hour", type=int, default=1)
    parser.add_argument("--generator-unit-mw", type=float, default=300.0)
    parser.add_argument("--added-load-mw", type=float, default=100.0)
    parser.add_argument("--min-site-kv", type=float, default=115.0)
    parser.add_argument("--no-scale-dispatch", action="store_true")
    args = parser.parse_args()
    result = generate_training_samples(
        args.db,
        args.out,
        config=GenerationConfig(
            seed=args.seed,
            hours=args.hours,
            held_out_fraction=args.held_out_fraction,
            ba_code=args.ba_code,
            scale_dispatch=not args.no_scale_dispatch,
            sampler=SamplerConfig(
                n1_per_hour=args.n1_per_hour,
                n2_per_hour=args.n2_per_hour,
                placement_per_hour=args.placement_per_hour,
                generator_unit_mw=args.generator_unit_mw,
                added_load_mw=args.added_load_mw,
                min_site_kv=args.min_site_kv,
            ),
        ),
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
