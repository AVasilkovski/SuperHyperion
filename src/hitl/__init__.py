"""
Human-in-the-Loop (HITL) Module

v2.1: Implements gates for human oversight of belief transitions.
v2.2: Adds ScopeLockGate for constitutional scope commitment.
v2.2: Adds WriteIntentService for Phase 14 write-intent lifecycle.
"""

from .base import HITLGate, HITLDecision, HITLPendingItem
from .epistemic_gate import EpistemicApprovalGate
from .impact_gate import HighImpactWriteCheckpoint
from .audit import HITLAuditLog, audit_log
from .scope_lock_gate import ScopeLockGate, ScopeDraft, ScopeLock, ScopeStatus, scope_lock_gate
from .intent_service import (
    WriteIntentService,
    WriteIntent,
    IntentStatus,
    IntentStatusEvent,
    IntentTransitionError,
    write_intent_service,
)

__all__ = [
    "HITLGate",
    "HITLDecision",
    "HITLPendingItem",
    "EpistemicApprovalGate",
    "HighImpactWriteCheckpoint",
    "HITLAuditLog",
    "audit_log",
    # v2.2 Scope Lock
    "ScopeLockGate",
    "ScopeDraft",
    "ScopeLock",
    "ScopeStatus",
    "scope_lock_gate",
    # v2.2 Write Intent
    "WriteIntentService",
    "WriteIntent",
    "IntentStatus",
    "IntentStatusEvent",
    "IntentTransitionError",
    "write_intent_service",
]

