"""
Scope Lock Gate (HITL Boundary 1)

Constitutional boundary: Nothing in Experimentation stage without scope_lock_id.

Implements the scope lifecycle state machine:
    scope-draft → scope-review → scope-lock | scope-expired

Human approves:
    - Clarified hypothesis H'
    - Atomic claim decomposition
    - Claim ID assignments
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from src.hitl.base import HITLDecision, HITLGate, HITLPendingItem

logger = logging.getLogger(__name__)


class ScopeStatus(str, Enum):
    """Scope lifecycle states."""
    DRAFT = "draft"           # Mutable, iterative
    REVIEW = "review"         # Pending human approval
    LOCKED = "locked"         # Immutable, signed
    EXPIRED = "expired"       # Terminal, safe failure


@dataclass
class ScopeDraft:
    """
    Mutable scope draft (pre-commitment).
    
    Can be versioned and iterated until human approves.
    """
    draft_id: str
    session_id: str
    hypothesis_h_prime: str
    atomic_claims: List[Dict[str, Any]]
    constraints: Dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_at: datetime = field(default_factory=datetime.now)

    def digest(self) -> str:
        """Compute stable hash of the draft."""
        data = {
            "hypothesis": self.hypothesis_h_prime,
            "claims": sorted([c.get("claim_id", "") for c in self.atomic_claims]),
            "constraints": self.constraints,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "session_id": self.session_id,
            "hypothesis_h_prime": self.hypothesis_h_prime,
            "atomic_claims": self.atomic_claims,
            "constraints": self.constraints,
            "version": self.version,
            "digest": self.digest(),
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ScopeLock:
    """
    Immutable signed scope artifact (commitment point).
    
    INVARIANT: Once created, cannot be modified.
    INVARIANT: All grounded artifacts must reference scope_lock_id.
    """
    lock_id: str
    session_id: str
    hypothesis_h_prime: str
    claim_ids: List[str]
    constraints: Dict[str, Any]
    derivation_hash: str
    approver_id: str
    approved_at: datetime
    status: ScopeStatus = ScopeStatus.LOCKED

    # Expiry control
    expires_at: Optional[datetime] = None

    def __post_init__(self):
        if self.expires_at is None:
            # Default: 7 day hard expiry
            self.expires_at = self.approved_at + timedelta(days=7)

    def is_valid(self) -> bool:
        """Check if lock is still valid (not expired)."""
        if self.status == ScopeStatus.EXPIRED:
            return False
        if datetime.now() > self.expires_at:
            return False
        return self.status == ScopeStatus.LOCKED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lock_id": self.lock_id,
            "session_id": self.session_id,
            "hypothesis_h_prime": self.hypothesis_h_prime,
            "claim_ids": self.claim_ids,
            "constraints": self.constraints,
            "derivation_hash": self.derivation_hash,
            "approver_id": self.approver_id,
            "approved_at": self.approved_at.isoformat(),
            "status": self.status.value,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


class ScopeLockGate(HITLGate):
    """
    HITL Boundary 1: Scope Lock Gate.
    
    Triggered after decomposition, before experimentation.
    
    Human approves:
        - Clarified hypothesis H'
        - Atomic claims with claim_ids
        - Scope constraints and boundaries
    
    INVARIANT: Experimentation cannot proceed without scope_lock_id.
    """

    def __init__(
        self,
        soft_sla_hours: int = 24,
        hard_expiry_days: int = 7,
    ):
        self.soft_sla_hours = soft_sla_hours
        self.hard_expiry_days = hard_expiry_days
        self._pending_drafts: Dict[str, ScopeDraft] = {}
        self._locks: Dict[str, ScopeLock] = {}

    def should_trigger(self, context: Dict[str, Any]) -> bool:
        """
        Trigger when decomposition is complete and scope not yet locked.
        """
        # Must have atomic claims from decomposition
        if not context.get("atomic_claims"):
            return False

        # Must not already have a valid scope lock
        scope_lock_id = context.get("scope_lock_id")
        if scope_lock_id and self._is_lock_valid(scope_lock_id):
            return False

        return True

    def create_pending_item(self, context: Dict[str, Any]) -> HITLPendingItem:
        """Create a pending scope lock request."""
        session_id = context.get("session_id", str(uuid.uuid4()))

        # Create draft from context
        draft = ScopeDraft(
            draft_id=f"draft_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            hypothesis_h_prime=context.get("hypothesis_h_prime", context.get("query", "")),
            atomic_claims=context.get("atomic_claims", []),
            constraints=context.get("constraints", {}),
        )

        self._pending_drafts[draft.draft_id] = draft

        return HITLPendingItem(
            item_id=f"scope_{draft.draft_id}",
            item_type="scope_lock",
            claim_id=draft.draft_id,  # Using draft_id as reference
            current_status=ScopeStatus.REVIEW.value,
            proposed_status=ScopeStatus.LOCKED.value,
            evidence_summary=self._build_summary(draft),
            confidence=1.0,  # Scope approval is binary
        )

    def process_decision(
        self,
        pending: HITLPendingItem,
        decision: HITLDecision,
    ) -> Dict[str, Any]:
        """Process human decision on scope lock request."""
        result = super().process_decision(pending, decision)

        draft_id = pending.claim_id
        draft = self._pending_drafts.get(draft_id)

        if not draft:
            result["error"] = f"Draft not found: {draft_id}"
            return result

        if decision.action == "approve":
            # Create immutable scope lock
            lock = ScopeLock(
                lock_id=f"lock_{uuid.uuid4().hex[:8]}",
                session_id=draft.session_id,
                hypothesis_h_prime=draft.hypothesis_h_prime,
                claim_ids=[c.get("claim_id") for c in draft.atomic_claims],
                constraints=draft.constraints,
                derivation_hash=draft.digest(),
                approver_id=decision.approver_id,
                approved_at=datetime.now(),
            )
            self._locks[lock.lock_id] = lock
            result["scope_lock_id"] = lock.lock_id
            result["scope_lock"] = lock.to_dict()

            logger.info(f"Scope locked: {lock.lock_id} by {decision.approver_id}")

        elif decision.action == "reject":
            # Mark as expired (terminal)
            result["status"] = ScopeStatus.EXPIRED.value
            logger.info(f"Scope rejected: {draft_id}")

        elif decision.action == "request_evidence":
            # Return to draft state for refinement
            result["status"] = ScopeStatus.DRAFT.value
            result["feedback"] = decision.rationale
            logger.info(f"Scope returned for refinement: {draft_id}")

        return result

    def get_lock(self, lock_id: str) -> Optional[ScopeLock]:
        """Get a scope lock by ID."""
        return self._locks.get(lock_id)

    def validate_scope_lock(self, scope_lock_id: str) -> bool:
        """
        Validate that a scope lock exists and is still valid.
        
        INVARIANT: VerifyAgent refuses to proceed without valid scope_lock_id.
        """
        return self._is_lock_valid(scope_lock_id)

    def _is_lock_valid(self, lock_id: str) -> bool:
        """Check if a lock ID is valid."""
        lock = self._locks.get(lock_id)
        if not lock:
            return False
        return lock.is_valid()

    def _build_summary(self, draft: ScopeDraft) -> str:
        """Build summary for human review."""
        parts = [
            f"Hypothesis: {draft.hypothesis_h_prime[:100]}...",
            f"Claims: {len(draft.atomic_claims)}",
            f"Digest: {draft.digest()}",
        ]

        if draft.constraints:
            parts.append(f"Constraints: {len(draft.constraints)} defined")

        return " | ".join(parts)


# Global instance
scope_lock_gate = ScopeLockGate()
