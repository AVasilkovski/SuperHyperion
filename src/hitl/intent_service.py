"""
Write Intent Service (Phase 14 Core)

Constitutional layer for write-intent lifecycle.
UI is replaceable, lifecycle is not.

State machine:
    staged → awaiting_hitl → approved | rejected | deferred | cancelled | expired → executed | failed

INVARIANTS:
    - Every terminal state has a final event (actor, rationale, timestamp)
    - executed requires prior approved
    - expired/cancelled/rejected prevent resurrection (use supersedes_intent_id)
    - Events are append-only
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Literal, Set
from enum import Enum
import uuid
import json
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Intent Status Enum
# =============================================================================

class IntentStatus(str, Enum):
    """Write-intent lifecycle states."""
    # Initial
    STAGED = "staged"
    
    # Awaiting human decision
    AWAITING_HITL = "awaiting_hitl"
    
    # Human decisions (HITL outcomes)
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    CANCELLED = "cancelled"
    
    # System transitions
    EXPIRED = "expired"
    
    # Execution outcomes
    EXECUTED = "executed"
    FAILED = "failed"


# Terminal states - no outgoing transitions
TERMINAL_STATES: Set[IntentStatus] = {
    IntentStatus.REJECTED,
    IntentStatus.CANCELLED,
    IntentStatus.EXPIRED,
    IntentStatus.EXECUTED,
    IntentStatus.FAILED,
}

# States that require human action
HITL_REQUIRED_STATES: Set[IntentStatus] = {
    IntentStatus.AWAITING_HITL,
}

# Allowed transitions (from -> set of to states)
ALLOWED_TRANSITIONS: Dict[IntentStatus, Set[IntentStatus]] = {
    IntentStatus.STAGED: {
        IntentStatus.AWAITING_HITL,
        IntentStatus.CANCELLED,
    },
    IntentStatus.AWAITING_HITL: {
        IntentStatus.APPROVED,
        IntentStatus.REJECTED,
        IntentStatus.DEFERRED,
        IntentStatus.CANCELLED,
        IntentStatus.EXPIRED,  # System only
    },
    IntentStatus.DEFERRED: {
        IntentStatus.AWAITING_HITL,  # Re-review when defer_until reached
        IntentStatus.EXPIRED,  # System only
    },
    IntentStatus.APPROVED: {
        IntentStatus.EXECUTED,
        IntentStatus.FAILED,
    },
    # Terminal states have no outgoing transitions
    IntentStatus.REJECTED: set(),
    IntentStatus.CANCELLED: set(),
    IntentStatus.EXPIRED: set(),
    IntentStatus.EXECUTED: set(),
    IntentStatus.FAILED: set(),
}


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class WriteIntent:
    """A write-intent record."""
    intent_id: str
    intent_type: str  # "update_epistemic_status", "create_proposition", etc.
    payload: Dict[str, Any]
    impact_score: float
    status: IntentStatus
    created_at: datetime
    expires_at: Optional[datetime] = None
    scope_lock_id: Optional[str] = None
    supersedes_intent_id: Optional[str] = None
    
    def __post_init__(self):
        if self.expires_at is None:
            # Default: 7 day hard expiry
            self.expires_at = self.created_at + timedelta(days=7)
    
    def is_expired(self) -> bool:
        """Check if intent has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at
    
    def is_terminal(self) -> bool:
        """Check if intent is in a terminal state."""
        return self.status in TERMINAL_STATES
    
    def requires_scope_lock(self) -> bool:
        """Check if this intent type requires a scope_lock_id."""
        # Types that require scope lock for execution
        REQUIRES_SCOPE_LOCK = {
            "update_epistemic_status",
            "create_proposition",
            "refute_proposition",
            "ontology_mutation",
            "operator_approval",
        }
        return self.intent_type in REQUIRES_SCOPE_LOCK
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "intent_type": self.intent_type,
            "payload": self.payload,
            "impact_score": self.impact_score,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "scope_lock_id": self.scope_lock_id,
            "supersedes_intent_id": self.supersedes_intent_id,
        }


@dataclass
class IntentStatusEvent:
    """An append-only status transition event."""
    event_id: str
    intent_id: str
    from_status: IntentStatus
    to_status: IntentStatus
    actor_type: Literal["human", "system"]
    actor_id: str
    created_at: datetime
    rationale: Optional[str] = None
    defer_until: Optional[datetime] = None
    execution_id: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "intent_id": self.intent_id,
            "from_status": self.from_status.value,
            "to_status": self.to_status.value,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "created_at": self.created_at.isoformat(),
            "rationale": self.rationale,
            "defer_until": self.defer_until.isoformat() if self.defer_until else None,
            "execution_id": self.execution_id,
            "error": self.error,
        }


# =============================================================================
# Transition Errors
# =============================================================================

class IntentTransitionError(Exception):
    """Raised when an illegal transition is attempted."""
    pass


class IntentNotFoundError(Exception):
    """Raised when intent is not found."""
    pass


class ScopeLockRequiredError(Exception):
    """Raised when scope_lock_id is required but missing."""
    pass


# =============================================================================
# Write Intent Service (Core)
# =============================================================================

class WriteIntentService:
    """
    Core service for write-intent lifecycle.
    
    Pure Python, no UI. This is the constitutional layer.
    Streamlit/CLI are just ports that call this service.
    """
    
    def __init__(self, db_client=None):
        """
        Initialize with optional TypeDB client.
        
        For testing, runs in-memory without DB.
        """
        self.db_client = db_client
        self._intents: Dict[str, WriteIntent] = {}  # In-memory store
        self._events: Dict[str, List[IntentStatusEvent]] = {}  # intent_id -> events
    
    # =========================================================================
    # State Machine Core
    # =========================================================================
    
    def _assert_transition_allowed(
        self,
        from_status: IntentStatus,
        to_status: IntentStatus,
    ) -> None:
        """Raise if transition is not allowed."""
        allowed = ALLOWED_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise IntentTransitionError(
                f"Transition {from_status.value} → {to_status.value} not allowed. "
                f"Allowed: {[s.value for s in allowed]}"
            )
    
    def _append_event(
        self,
        intent: WriteIntent,
        to_status: IntentStatus,
        actor_type: Literal["human", "system"],
        actor_id: str,
        rationale: Optional[str] = None,
        defer_until: Optional[datetime] = None,
        execution_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> IntentStatusEvent:
        """Append an event to the intent's history."""
        event = IntentStatusEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            intent_id=intent.intent_id,
            from_status=intent.status,
            to_status=to_status,
            actor_type=actor_type,
            actor_id=actor_id,
            created_at=datetime.now(),
            rationale=rationale,
            defer_until=defer_until,
            execution_id=execution_id,
            error=error,
        )
        
        if intent.intent_id not in self._events:
            self._events[intent.intent_id] = []
        self._events[intent.intent_id].append(event)
        
        # Update intent status
        intent.status = to_status
        
        logger.info(
            f"Intent {intent.intent_id}: {event.from_status.value} → {event.to_status.value} "
            f"by {actor_type}:{actor_id}"
        )
        
        return event
    
    # =========================================================================
    # Lifecycle Operations
    # =========================================================================
    
    def stage(
        self,
        intent_type: str,
        payload: Dict[str, Any],
        impact_score: float = 0.0,
        scope_lock_id: Optional[str] = None,
        supersedes_intent_id: Optional[str] = None,
        expires_in_days: int = 7,
    ) -> WriteIntent:
        """
        Stage a new write-intent.
        
        Returns a new intent in STAGED status.
        """
        intent = WriteIntent(
            intent_id=f"intent_{uuid.uuid4().hex[:12]}",
            intent_type=intent_type,
            payload=payload,
            impact_score=impact_score,
            status=IntentStatus.STAGED,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(days=expires_in_days),
            scope_lock_id=scope_lock_id,
            supersedes_intent_id=supersedes_intent_id,
        )
        
        self._intents[intent.intent_id] = intent
        self._events[intent.intent_id] = []
        
        logger.info(f"Intent staged: {intent.intent_id} (type={intent_type})")
        return intent
    
    def submit_for_review(
        self,
        intent_id: str,
        actor_id: str = "system",
    ) -> WriteIntent:
        """
        Submit a staged intent for HITL review.
        
        Transition: staged → awaiting_hitl
        """
        intent = self._get_or_raise(intent_id)
        self._assert_transition_allowed(intent.status, IntentStatus.AWAITING_HITL)
        
        self._append_event(
            intent,
            to_status=IntentStatus.AWAITING_HITL,
            actor_type="system",
            actor_id=actor_id,
            rationale="Submitted for human review",
        )
        
        return intent
    
    def approve(
        self,
        intent_id: str,
        approver_id: str,
        rationale: str,
    ) -> WriteIntent:
        """
        Approve an intent for execution.
        
        Transition: awaiting_hitl → approved
        """
        intent = self._get_or_raise(intent_id)
        self._assert_transition_allowed(intent.status, IntentStatus.APPROVED)
        
        self._append_event(
            intent,
            to_status=IntentStatus.APPROVED,
            actor_type="human",
            actor_id=approver_id,
            rationale=rationale,
        )
        
        return intent
    
    def reject(
        self,
        intent_id: str,
        rejector_id: str,
        rationale: str,
    ) -> WriteIntent:
        """
        Reject an intent (terminal).
        
        Transition: awaiting_hitl → rejected
        """
        intent = self._get_or_raise(intent_id)
        self._assert_transition_allowed(intent.status, IntentStatus.REJECTED)
        
        self._append_event(
            intent,
            to_status=IntentStatus.REJECTED,
            actor_type="human",
            actor_id=rejector_id,
            rationale=rationale,
        )
        
        return intent
    
    def defer(
        self,
        intent_id: str,
        deferrer_id: str,
        until: datetime,
        rationale: str,
    ) -> WriteIntent:
        """
        Defer an intent for later review.
        
        Transition: awaiting_hitl → deferred
        """
        intent = self._get_or_raise(intent_id)
        self._assert_transition_allowed(intent.status, IntentStatus.DEFERRED)
        
        self._append_event(
            intent,
            to_status=IntentStatus.DEFERRED,
            actor_type="human",
            actor_id=deferrer_id,
            rationale=rationale,
            defer_until=until,
        )
        
        return intent
    
    def cancel(
        self,
        intent_id: str,
        actor_id: str,
        rationale: str,
        actor_type: Literal["human", "system"] = "human",
    ) -> WriteIntent:
        """
        Cancel an intent (terminal).
        
        Transition: staged | awaiting_hitl → cancelled
        """
        intent = self._get_or_raise(intent_id)
        self._assert_transition_allowed(intent.status, IntentStatus.CANCELLED)
        
        self._append_event(
            intent,
            to_status=IntentStatus.CANCELLED,
            actor_type=actor_type,
            actor_id=actor_id,
            rationale=rationale,
        )
        
        return intent
    
    def expire(
        self,
        intent_id: str,
    ) -> WriteIntent:
        """
        Expire an intent (system transition, terminal).
        
        Transition: awaiting_hitl | deferred → expired
        """
        intent = self._get_or_raise(intent_id)
        self._assert_transition_allowed(intent.status, IntentStatus.EXPIRED)
        
        self._append_event(
            intent,
            to_status=IntentStatus.EXPIRED,
            actor_type="system",
            actor_id="expiry_service",
            rationale=f"Expired at {intent.expires_at.isoformat() if intent.expires_at else 'N/A'}",
        )
        
        return intent
    
    def execute(
        self,
        intent_id: str,
        execution_id: str,
    ) -> WriteIntent:
        """
        Mark intent as executed.
        
        INVARIANT: Requires prior approved event.
        Transition: approved → executed
        """
        intent = self._get_or_raise(intent_id)
        
        # CONSTITUTIONAL INVARIANT: executed requires prior approved
        if not self._has_approved_event(intent_id):
            raise IntentTransitionError(
                f"Intent {intent_id} cannot be executed: no prior 'approved' event"
            )
        
        # CONSTITUTIONAL INVARIANT: scope_lock_id required for certain types
        if intent.requires_scope_lock() and not intent.scope_lock_id:
            raise ScopeLockRequiredError(
                f"Intent {intent_id} requires scope_lock_id for execution"
            )
        
        self._assert_transition_allowed(intent.status, IntentStatus.EXECUTED)
        
        self._append_event(
            intent,
            to_status=IntentStatus.EXECUTED,
            actor_type="system",
            actor_id="executor",
            execution_id=execution_id,
        )
        
        return intent
    
    def fail(
        self,
        intent_id: str,
        error: str,
    ) -> WriteIntent:
        """
        Mark intent as failed.
        
        Transition: approved → failed
        """
        intent = self._get_or_raise(intent_id)
        self._assert_transition_allowed(intent.status, IntentStatus.FAILED)
        
        self._append_event(
            intent,
            to_status=IntentStatus.FAILED,
            actor_type="system",
            actor_id="executor",
            error=error,
        )
        
        return intent
    
    def expire_stale(self, max_age_days: int = 7) -> List[str]:
        """
        Expire all stale intents.
        
        Returns list of expired intent IDs.
        """
        expired_ids = []
        now = datetime.now()
        
        for intent in self._intents.values():
            if intent.status in TERMINAL_STATES:
                continue
            if intent.expires_at and now > intent.expires_at:
                try:
                    self.expire(intent.intent_id)
                    expired_ids.append(intent.intent_id)
                except IntentTransitionError:
                    pass  # Already in a state that can't expire
        
        return expired_ids
    
    def reactivate_deferred(self) -> List[str]:
        """
        Reactivate deferred intents where defer_until has passed.
        
        Returns list of reactivated intent IDs.
        """
        reactivated_ids = []
        now = datetime.now()
        
        for intent in self._intents.values():
            if intent.status != IntentStatus.DEFERRED:
                continue
            
            # Find the defer event
            events = self._events.get(intent.intent_id, [])
            defer_event = None
            for e in reversed(events):
                if e.to_status == IntentStatus.DEFERRED and e.defer_until:
                    defer_event = e
                    break
            
            if defer_event and defer_event.defer_until and now >= defer_event.defer_until:
                # Re-submit for review
                self._append_event(
                    intent,
                    to_status=IntentStatus.AWAITING_HITL,
                    actor_type="system",
                    actor_id="defer_service",
                    rationale=f"Reactivated after defer_until={defer_event.defer_until.isoformat()}",
                )
                reactivated_ids.append(intent.intent_id)
        
        return reactivated_ids
    
    # =========================================================================
    # Queries
    # =========================================================================
    
    def get(self, intent_id: str) -> Optional[WriteIntent]:
        """Get an intent by ID."""
        return self._intents.get(intent_id)
    
    def _get_or_raise(self, intent_id: str) -> WriteIntent:
        """Get an intent or raise IntentNotFoundError."""
        intent = self.get(intent_id)
        if not intent:
            raise IntentNotFoundError(f"Intent not found: {intent_id}")
        return intent
    
    def list_by_status(self, status: IntentStatus) -> List[WriteIntent]:
        """List intents by status."""
        return [i for i in self._intents.values() if i.status == status]
    
    def list_pending(self) -> List[WriteIntent]:
        """List intents awaiting human decision."""
        return self.list_by_status(IntentStatus.AWAITING_HITL)
    
    def get_history(self, intent_id: str) -> List[IntentStatusEvent]:
        """Get all events for an intent."""
        return self._events.get(intent_id, [])
    
    def _has_approved_event(self, intent_id: str) -> bool:
        """Check if intent has an approved event in its history."""
        events = self._events.get(intent_id, [])
        return any(e.to_status == IntentStatus.APPROVED for e in events)


# Global instance (no DB client - must be configured)
write_intent_service = WriteIntentService()
