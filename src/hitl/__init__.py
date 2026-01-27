"""
Human-in-the-Loop (HITL) Module

v2.1: Implements gates for human oversight of belief transitions.
"""

from .base import HITLGate, HITLDecision, HITLPendingItem
from .epistemic_gate import EpistemicApprovalGate
from .impact_gate import HighImpactWriteCheckpoint
from .audit import HITLAuditLog, audit_log

__all__ = [
    "HITLGate",
    "HITLDecision",
    "HITLPendingItem",
    "EpistemicApprovalGate",
    "HighImpactWriteCheckpoint",
    "HITLAuditLog",
    "audit_log",
]
