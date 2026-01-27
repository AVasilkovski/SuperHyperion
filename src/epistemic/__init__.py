"""
Epistemic Control Layer

v2.1: Implements the core epistemic types and agents for
the dual-lane scientific reasoning architecture.
"""

from .status import EpistemicStatus, requires_hitl_approval
from .classifier import EpistemicClassifierAgent
from .uncertainty import calculate_scientific_uncertainty, uncertainty_from_codeact_result
from .reputation import SourceReputationModel, source_reputation_model

__all__ = [
    "EpistemicStatus",
    "requires_hitl_approval",
    "EpistemicClassifierAgent",
    "calculate_scientific_uncertainty",
    "uncertainty_from_codeact_result",
    "SourceReputationModel",
    "source_reputation_model",
]

