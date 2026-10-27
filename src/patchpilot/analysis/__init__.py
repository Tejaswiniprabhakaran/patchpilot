"""Failure analysis: rule-based classifier, LLM judge and agreement statistics (A5)."""

from patchpilot.analysis.failures import (
    CATEGORIES,
    DESCRIPTIONS,
    Classification,
    classify,
    cohen_kappa,
)

__all__ = ["CATEGORIES", "DESCRIPTIONS", "Classification", "classify", "cohen_kappa"]
