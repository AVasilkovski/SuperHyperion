"""
Theory Change Operator (Phase 16.2)

Deterministic policy functions for computing theory change actions
based on aggregated evidence with roles.

This module implements the "proposal-only" mode:
- Computes actions (revise/fork/quarantine) deterministically
- Stages proposals via write-intent system
- Does NOT directly mutate propositions (HITL gate enforced)

INVARIANTS:
- All theory change actions go through HITL approval.
- Confidence/strength values are clamped and finite-checked.
- Evidence IDs are canonically resolved.
- Replicate role is interpreted by channel (validation=success, negative=failure).
"""

from dataclasses import dataclass
from typing import List, Tuple, Literal, Dict, Any, Optional
from enum import Enum
import logging

from src.epistemology.evidence_roles import EvidenceRole, clamp_probability

logger = logging.getLogger(__name__)


# =============================================================================
# Thresholds (configurable)
# =============================================================================

# Conflict score above which we recommend forking instead of revising
FORK_THRESHOLD = 0.6

# Undercut confidence above which we recommend quarantine
QUARANTINE_THRESHOLD = 0.8

# Minimum evidence count before making recommendations (reduces noise)
MIN_EVIDENCE_COUNT = 2


# =============================================================================
# Theory Change Actions
# =============================================================================

class TheoryAction(str, Enum):
    """Possible theory change actions."""
    REVISE = "revise"          # Update belief state in place
    FORK = "fork"              # Create competing hypothesis
    QUARANTINE = "quarantine"  # Suspend due to methodological issues
    HOLD = "hold"              # Insufficient evidence to act


# =============================================================================
# Canonical ID Resolver
# =============================================================================

def get_evidence_entity_id(ev: Dict[str, Any]) -> str:
    """
    Canonical resolver for evidence entity IDs.
    
    Handles all common key variations across Python/TypeQL:
    - DB row keys: eid
    - entity_id / entity-id
    - evidence_id / evidence-id
    """
    return (
        ev.get("eid")  # TypeDB query variable
        or ev.get("entity_id")
        or ev.get("entity-id")
        or ev.get("evidence_id")
        or ev.get("evidence-id")
        or "unknown"
    )


def get_claim_id(ev: Dict[str, Any]) -> str:
    """
    Canonical resolver for claim IDs.
    
    Handles all common key variations across Python/TypeQL:
    - DB row keys: cid
    - claim_id / claim-id
    - proposition_id / pid
    """
    val = (
        ev.get("cid")  # TypeDB query variable
        or ev.get("claim_id")
        or ev.get("claim-id")
        or ev.get("proposition_id")
        or ev.get("pid")
        or ""
    )
    return str(val).strip() if val else ""


def get_confidence_value(ev: Dict[str, Any]) -> float:
    """
    Canonical resolver for confidence/strength values with clamping.
    
    Handles all common key variations and applies numeric hygiene.
    - DB row keys: conf, rs
    - confidence_score / confidence-score
    - refutation_strength / refutation-strength / confidence
    """
    raw = (
        ev.get("conf")  # TypeDB query variable
        or ev.get("rs")  # refutation-strength variable
        or ev.get("confidence_score")
        or ev.get("confidence-score")
        or ev.get("refutation_strength")
        or ev.get("refutation-strength")
        or ev.get("confidence")
        or 0.5
    )
    return clamp_probability(raw, "confidence_value")


# =============================================================================
# Evidence Aggregation
# =============================================================================

# Channel type for evidence (determines replicate interpretation)
EvidenceChannel = Literal["validation", "negative"]


@dataclass
class EvidenceAggregate:
    """Aggregated evidence statistics for a claim."""
    claim_id: str
    support_count: int
    support_max_conf: float
    support_mean_conf: float
    refute_count: int
    refute_max_conf: float
    refute_mean_conf: float
    undercut_count: int
    undercut_max_conf: float
    replicate_success_count: int  # From validation channel
    replicate_fail_count: int     # From negative channel
    
    @property
    def total_count(self) -> int:
        return (
            self.support_count 
            + self.refute_count 
            + self.undercut_count 
            + self.replicate_success_count
            + self.replicate_fail_count
        )
    
    @property
    def has_sufficient_evidence(self) -> bool:
        return self.total_count >= MIN_EVIDENCE_COUNT
    
    @property
    def has_negative_evidence(self) -> bool:
        """True if any refute/undercut/replicate-fail evidence exists."""
        return (
            self.refute_count > 0 
            or self.undercut_count > 0 
            or self.replicate_fail_count > 0
        )


def aggregate_evidence(
    claim_id: str,
    evidence_with_roles: List[Tuple[Dict[str, Any], EvidenceRole, EvidenceChannel]],
) -> EvidenceAggregate:
    """
    Aggregate evidence by role and channel for a claim.
    
    Args:
        claim_id: The claim being evaluated
        evidence_with_roles: List of (evidence_dict, role, channel) tuples
        
    Returns:
        EvidenceAggregate with summary statistics
    """
    support = []
    refute = []
    undercut = []
    replicate_success = []
    replicate_fail = []
    
    for ev, role, channel in evidence_with_roles:
        conf = get_confidence_value(ev)
        
        if role == EvidenceRole.SUPPORT:
            support.append(conf)
        elif role == EvidenceRole.REFUTE:
            refute.append(conf)
        elif role == EvidenceRole.UNDERCUT:
            undercut.append(conf)
        elif role == EvidenceRole.REPLICATE:
            # Replicate interpretation depends on channel
            if channel == "validation":
                replicate_success.append(conf)
            else:  # negative
                replicate_fail.append(conf)
    
    def safe_max(lst: List[float]) -> float:
        return max(lst) if lst else 0.0
    
    def safe_mean(lst: List[float]) -> float:
        return sum(lst) / len(lst) if lst else 0.0
    
    return EvidenceAggregate(
        claim_id=claim_id,
        support_count=len(support),
        support_max_conf=safe_max(support),
        support_mean_conf=safe_mean(support),
        refute_count=len(refute),
        refute_max_conf=safe_max(refute),
        refute_mean_conf=safe_mean(refute),
        undercut_count=len(undercut),
        undercut_max_conf=safe_max(undercut),
        replicate_success_count=len(replicate_success),
        replicate_fail_count=len(replicate_fail),
    )


# =============================================================================
# Conflict Metrics
# =============================================================================

def compute_conflict_score(agg: EvidenceAggregate) -> float:
    """
    Compute conflict score between support and refutation evidence.
    
    Returns value in [0, 1]:
    - 0.0: No conflict (all evidence agrees)
    - 1.0: Maximum conflict (equal support and refutation)
    
    Formula: 2 * min(support_weight, refute_weight) / total_weight
    """
    # Include replicate_success in support weight
    support_weight = (
        agg.support_count * agg.support_mean_conf
        + agg.replicate_success_count * 0.5  # Lower weight for replicate
    )
    # Include replicate_fail in refute weight  
    refute_weight = (
        agg.refute_count * agg.refute_mean_conf
        + agg.replicate_fail_count * 0.5  # Lower weight for replicate
    )
    
    total_weight = support_weight + refute_weight
    if total_weight == 0:
        return 0.0
    
    conflict = 2 * min(support_weight, refute_weight) / total_weight
    return min(1.0, max(0.0, conflict))


def compute_entropy_proxy(agg: EvidenceAggregate) -> float:
    """
    Compute entropy proxy for evidence distribution.
    
    Higher values indicate more uncertainty/disagreement.
    """
    counts = [agg.support_count, agg.refute_count, agg.undercut_count]
    total = sum(counts)
    if total == 0:
        return 0.0
    
    import math
    entropy = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            entropy -= p * math.log2(p)
    
    # Normalize to [0, 1] (max entropy is log2(3) ≈ 1.58)
    return entropy / 1.585


# =============================================================================
# Theory Change Decision
# =============================================================================

def compute_theory_change_action(
    claim_id: str,
    evidence_with_roles: List[Tuple[Dict[str, Any], EvidenceRole, EvidenceChannel]],
) -> Tuple[TheoryAction, Dict[str, Any]]:
    """
    Deterministic policy function for computing theory change action.
    
    Args:
        claim_id: The claim being evaluated
        evidence_with_roles: List of (evidence_dict, role, channel) tuples
        
    Returns:
        Tuple of (action, metadata_dict) where metadata contains:
        - conflict_score
        - entropy
        - rationale
        - evidence_summary
    """
    agg = aggregate_evidence(claim_id, evidence_with_roles)
    
    # Insufficient evidence
    if not agg.has_sufficient_evidence:
        return TheoryAction.HOLD, {
            "conflict_score": 0.0,
            "entropy": 0.0,
            "rationale": f"Insufficient evidence (count={agg.total_count}, min={MIN_EVIDENCE_COUNT})",
            "evidence_summary": agg.__dict__,
        }
    
    # Check for undercut first (methodological issues)
    if agg.undercut_count > 0 and agg.undercut_max_conf > QUARANTINE_THRESHOLD:
        return TheoryAction.QUARANTINE, {
            "conflict_score": 0.0,
            "entropy": compute_entropy_proxy(agg),
            "rationale": f"High-confidence undercut ({agg.undercut_max_conf:.2f}) suggests methodological issues",
            "evidence_summary": agg.__dict__,
        }
    
    # Compute conflict
    conflict = compute_conflict_score(agg)
    entropy = compute_entropy_proxy(agg)
    
    # Fork if high conflict
    if conflict > FORK_THRESHOLD:
        return TheoryAction.FORK, {
            "conflict_score": conflict,
            "entropy": entropy,
            "rationale": f"Conflict score {conflict:.2f} exceeds threshold {FORK_THRESHOLD}",
            "evidence_summary": agg.__dict__,
        }
    
    # Revise (default: update belief state)
    return TheoryAction.REVISE, {
        "conflict_score": conflict,
        "entropy": entropy,
        "rationale": "Evidence is consistent enough to revise belief state",
        "evidence_summary": agg.__dict__,
    }


# =============================================================================
# Proposal Generation (Proposal-Only Mode)
# =============================================================================

@dataclass
class TheoryChangeProposal:
    """A staged theory change proposal for HITL review."""
    proposal_id: str
    claim_id: str
    action: TheoryAction
    conflict_score: float
    entropy: float
    rationale: str
    evidence_ids: List[str]
    evidence_summary: Dict[str, Any]
    
    def to_intent_payload(self) -> Dict[str, Any]:
        """Convert to write-intent payload for staging."""
        return {
            "proposal_id": self.proposal_id,
            "action": self.action.value,
            "claim_id": self.claim_id,
            "evidence_ids": self.evidence_ids,
            "conflict_score": self.conflict_score,
            "rationale": self.rationale,
        }


def generate_proposal(
    claim_id: str,
    evidence_with_roles: List[Tuple[Dict[str, Any], EvidenceRole, EvidenceChannel]],
    proposal_id: Optional[str] = None,
) -> TheoryChangeProposal:
    """
    Generate a theory change proposal for a claim.
    
    This creates a proposal object that can be staged as a write-intent.
    The actual mutation requires HITL approval.
    
    Args:
        claim_id: The claim being evaluated
        evidence_with_roles: List of (evidence_dict, role, channel) tuples
        proposal_id: Optional ID for the proposal (generated if not provided)
        
    Returns:
        TheoryChangeProposal ready for staging
    """
    import uuid
    
    action, metadata = compute_theory_change_action(claim_id, evidence_with_roles)
    
    # Extract evidence IDs using canonical resolver
    evidence_ids = [
        get_evidence_entity_id(ev)
        for ev, _, _ in evidence_with_roles
    ]
    
    return TheoryChangeProposal(
        proposal_id=proposal_id or f"prop-{uuid.uuid4().hex[:12]}",
        claim_id=claim_id,
        action=action,
        conflict_score=metadata["conflict_score"],
        entropy=metadata["entropy"],
        rationale=metadata["rationale"],
        evidence_ids=evidence_ids,
        evidence_summary=metadata["evidence_summary"],
    )
