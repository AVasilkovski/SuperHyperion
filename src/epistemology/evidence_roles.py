"""
Evidence Roles — Phase 16.1

Defines typed evidence roles for the evidence→proposition relation.
These roles determine how evidence affects belief updates.

Evidence Roles:
- support: Evidence that confirms/supports the proposition
- refute: Evidence that contradicts/refutes the proposition  
- undercut: Evidence that attacks the method/assumptions (not the claim itself)
- replicate: Evidence from a replication attempt (success or failure)

Failure Modes (for negative-evidence):
- null_effect: No effect detected where one was expected
- sign_flip: Effect in opposite direction than expected
- violated_assumption: Critical assumption of the method was violated
- nonidentifiable: Parameters could not be identified from data
"""

from enum import Enum
from typing import Optional
import logging
import math

logger = logging.getLogger(__name__)


class EvidenceRole(str, Enum):
    """Typed evidence roles for epistemic semantics."""
    SUPPORT = "support"
    REFUTE = "refute"
    UNDERCUT = "undercut"
    REPLICATE = "replicate"


class FailureMode(str, Enum):
    """Typed failure modes for negative evidence."""
    NULL_EFFECT = "null_effect"
    SIGN_FLIP = "sign_flip"
    VIOLATED_ASSUMPTION = "violated_assumption"
    NONIDENTIFIABLE = "nonidentifiable"


def validate_evidence_role(role: Optional[str]) -> Optional[EvidenceRole]:
    """
    Validate and normalize an evidence role string.
    
    Args:
        role: String role value or None
        
    Returns:
        EvidenceRole enum value or None if input is None
        
    Raises:
        ValueError: If role is not a valid evidence role
    """
    if role is None:
        return None
    
    role_lower = role.lower().strip()
    try:
        return EvidenceRole(role_lower)
    except ValueError:
        valid_roles = [r.value for r in EvidenceRole]
        raise ValueError(
            f"Invalid evidence role '{role}'. "
            f"Valid roles are: {valid_roles}"
        )


def validate_failure_mode(mode: Optional[str]) -> Optional[FailureMode]:
    """
    Validate and normalize a failure mode string.
    
    Args:
        mode: String failure mode value or None
        
    Returns:
        FailureMode enum value or None if input is None
        
    Raises:
        ValueError: If mode is not a valid failure mode
    """
    if mode is None:
        return None
    
    mode_lower = mode.lower().strip()
    try:
        return FailureMode(mode_lower)
    except ValueError:
        valid_modes = [m.value for m in FailureMode]
        raise ValueError(
            f"Invalid failure mode '{mode}'. "
            f"Valid modes are: {valid_modes}"
        )


def require_evidence_role(role: Optional[str], default: EvidenceRole, *, strict: bool = True) -> EvidenceRole:
    """
    Validate and normalize evidence role with a required default (Phase 16.2-ready).
    
    This is stricter than validate_evidence_role: it never returns None,
    always falling back to the provided default.
    
    Args:
        role: String role value or None
        default: Default EvidenceRole to use if role is None or invalid
        strict: If True, raise on invalid values; if False, warn and use default
        
    Returns:
        EvidenceRole enum value (never None)
        
    Raises:
        ValueError: If role is invalid and strict=True
    """
    if role is None:
        return default
    
    try:
        role_lower = role.lower().strip()
        return EvidenceRole(role_lower)
    except ValueError:
        if strict:
            valid_roles = [r.value for r in EvidenceRole]
            raise ValueError(
                f"Invalid evidence role '{role}'. "
                f"Valid roles are: {valid_roles}"
            )
        else:
            logger.warning(
                f"Invalid evidence_role={role!r}; defaulting to {default.value}"
            )
            return default


def clamp_probability(value: float, name: str = "value") -> float:
    """
    Clamp a probability/strength value to [0, 1] (Phase 16.2-ready).
    
    Prevents garbage values (including NaN/inf) from drifting into TypeDB.
    
    Args:
        value: Numeric value to clamp
        name: Name of the value (for logging)
        
    Returns:
        Clamped value in [0, 1]
        
    Raises:
        ValueError: If value is NaN or infinite
    """
    raw = float(value)
    if not math.isfinite(raw):
        raise ValueError(f"{name} must be finite, got {value}")
    
    clamped = max(0.0, min(1.0, raw))
    if clamped != raw:
        logger.warning(f"{name} clamped from {raw} to {clamped}")
    return clamped


def evidence_role_affects_belief(role: EvidenceRole) -> dict:
    """
    Describe how an evidence role affects belief updates.
    
    Returns a dict with:
    - direction: +1 (increases confidence), -1 (decreases), 0 (neutral), None (depends on context)
    - requires_hitl: Whether this role typically requires HITL review
    - can_prove: Whether this role can upgrade status to 'proven'
    
    Args:
        role: The evidence role to analyze
        
    Returns:
        Dict describing the role's epistemic effects
    """
    effects = {
        EvidenceRole.SUPPORT: {
            "direction": 1,
            "requires_hitl": False,
            "can_prove": True,
        },
        EvidenceRole.REFUTE: {
            "direction": -1,
            "requires_hitl": True,  # Refutations should be reviewed
            "can_prove": False,
        },
        EvidenceRole.UNDERCUT: {
            "direction": 0,  # Doesn't directly affect claim, attacks method
            "requires_hitl": True,  # Method attacks are serious
            "can_prove": False,
        },
        EvidenceRole.REPLICATE: {
            "direction": None,  # Depends on outcome (success/failure)
            "requires_hitl": False,
            "can_prove": True,  # Multiple successful replications can prove
        },
    }
    return effects[role]
