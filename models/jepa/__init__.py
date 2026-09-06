"""Bounded experimental JEPA for observed outage-count trajectories.

This package is deliberately separate from ``models.outage``.  Its outputs are
experimental count forecasts, never outage probabilities or qualified records.
"""

from .experiment import JepaConfig, run_experiment

__all__ = ["JepaConfig", "run_experiment"]
