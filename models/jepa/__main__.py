from __future__ import annotations

import argparse
from pathlib import Path

from .experiment import JepaConfig, run_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Train bounded experimental EAGLE-I count JEPA")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-reference", help="stable provenance path recorded in the artifact")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--max-windows", type=int, default=2400)
    args = parser.parse_args()
    print(run_experiment(source=args.source, output_dir=args.output_dir, source_reference=args.source_reference, config=JepaConfig(epochs=args.epochs, max_windows=args.max_windows)))


if __name__ == "__main__":
    main()
