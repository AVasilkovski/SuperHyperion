"""
Epistemic Status Enum

v2.1: Defines the five-state epistemic classification for claims.
"""

from enum import Enum


class EpistemicStatus(str, Enum):
    """
    Epistemic status of a claim in the knowledge graph.
    
    Decision rules:
        SPECULATIVE: No evidence yet
        SUPPORTED: One experiment confirms
        PROVEN: Replication + low variance
        UNRESOLVED: Conflicting evidence
        REFUTED: Contradicted by evidence
    """
    PROVEN = "proven"
    SUPPORTED = "supported"
    UNRESOLVED = "unresolved"
    SPECULATIVE = "speculative"
    REFUTED = "refuted"

    @classmethod
    def from_evidence(
        cls,
        has_evidence: bool,
        experiment_count: int,
        variance: float,
        has_contradiction: bool,
        refuted: bool = False,
    ) -> "EpistemicStatus":
        """
        Determine epistemic status based on evidence.
        
        Decision rules (in order of precedence):
            1. Refuted by strong counter-evidence → REFUTED
            2. Has unresolved contradiction → UNRESOLVED
            3. No evidence → SPECULATIVE
            4. One experiment → SUPPORTED
            5. Replication (≥2) + low variance (≤0.1) → PROVEN
        """
        if refuted:
            return cls.REFUTED
        if has_contradiction:
            return cls.UNRESOLVED
        if not has_evidence:
            return cls.SPECULATIVE
        if experiment_count >= 2 and variance <= 0.1:
            return cls.PROVEN
        if experiment_count >= 1:
            return cls.SUPPORTED
        return cls.SPECULATIVE


# Transitions that require human approval (HITL)
HITL_REQUIRED_TRANSITIONS = frozenset([
    (EpistemicStatus.SPECULATIVE, EpistemicStatus.SUPPORTED),
    (EpistemicStatus.SUPPORTED, EpistemicStatus.PROVEN),
    (EpistemicStatus.UNRESOLVED, EpistemicStatus.REFUTED),
    (EpistemicStatus.SUPPORTED, EpistemicStatus.REFUTED),
])


def requires_hitl_approval(
    current: EpistemicStatus,
    proposed: EpistemicStatus
) -> bool:
    """Check if a status transition requires human approval."""
    return (current, proposed) in HITL_REQUIRED_TRANSITIONS
