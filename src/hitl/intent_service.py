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

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Set

if TYPE_CHECKING:
    from .intent_store import IntentStore

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
        IntentStatus.DEFERRED,  # P1-B: System hold (e.g. mixed-scope batch)
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
    lane: str  # "grounded" | "speculative" - Envelope metadata
    payload: Dict[str, Any]
    impact_score: float
    status: IntentStatus
    created_at: datetime
    expires_at: Optional[datetime] = None
    scope_lock_id: Optional[str] = None
    supersedes_intent_id: Optional[str] = None
    proposal_id: Optional[str] = None

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
        # Delegate to registry (single source of truth)
        from .intent_registry import requires_scope_lock as registry_requires_scope_lock

        try:
            return registry_requires_scope_lock(self.intent_type, self.lane)
        except ValueError:
            # Unknown intent type - fail safe (require scope lock)
            return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "intent_type": self.intent_type,
            "lane": self.lane,
            "payload": self.payload,
            "impact_score": self.impact_score,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "scope_lock_id": self.scope_lock_id,
            "supersedes_intent_id": self.supersedes_intent_id,
            "proposal_id": self.proposal_id,
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
    
    Uses IntentStore for persistence:
    - InMemoryIntentStore for tests
    - TypeDBIntentStore for production
    """

    def __init__(self, store: Optional["IntentStore"] = None):
        """
        Initialize with optional IntentStore.
        
        If no store provided, uses InMemoryIntentStore.
        """
        if store is None:
            from .intent_store import InMemoryIntentStore
            store = InMemoryIntentStore()
        self._store = store

        # In-memory cache for WriteIntent objects (reconstructed from store)
        self._intent_cache: Dict[str, WriteIntent] = {}

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
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        now = datetime.now()

        # Persist event to store
        self._store.append_event(
            event_id=event_id,
            intent_id=intent.intent_id,
            from_status=intent.status.value,
            to_status=to_status.value,
            actor_type=actor_type,
            actor_id=actor_id,
            created_at=now,
            rationale=rationale,
            defer_until=defer_until,
            execution_id=execution_id,
            error=error,
        )

        # Update intent status in store
        self._store.update_intent_status(intent.intent_id, to_status.value)

        # Update cached intent
        old_status = intent.status
        intent.status = to_status

        # Create event object for return
        event = IntentStatusEvent(
            event_id=event_id,
            intent_id=intent.intent_id,
            from_status=old_status,
            to_status=to_status,
            actor_type=actor_type,
            actor_id=actor_id,
            created_at=now,
            rationale=rationale,
            defer_until=defer_until,
            execution_id=execution_id,
            error=error,
        )

        logger.info(
            f"Intent {intent.intent_id}: {old_status.value} → {to_status.value} "
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
        *,
        lane: str = "grounded",
        impact_score: float = 0.0,
        scope_lock_id: Optional[str] = None,
        supersedes_intent_id: Optional[str] = None,
        expires_in_days: int = 7,
        proposal_id: Optional[str] = None,
    ) -> WriteIntent:
        """
        Stage a new write-intent.
        
        New in 16.3: 
        - proposal_id is envelope metadata (rejected from payload)
        - deduplication via get_by_proposal_id
        - lane is envelope metadata (removed from payload if present)
        - full policy enforcement at stage time (registry validation + scope lock check)
        
        Returns a new intent in STAGED status.
        """
        from .intent_registry import ScopeLockPolicy, get_intent_spec, validate_intent_payload

        # Phase 16.3: proposal_id is envelope-only
        if "proposal_id" in payload:
            raise ValueError("proposal_id is envelope metadata, not payload")

        # Phase 16.3: deduplication
        if proposal_id:
            existing = self._store.get_by_proposal_id(proposal_id)
            if existing:
                logger.info(f"Dedupe: proposal {proposal_id} already staged as {existing['intent_id']}")
                return self._reconstruct_intent(existing)

        # 1. Enforce envelope lane invariant (strip from payload if matched)
        if "lane" in payload:
            if payload["lane"] != lane:
                raise ValueError(f"Payload lane '{payload['lane']}' mismatch envelope lane '{lane}'")
            # Remove from payload (it's envelope only now)
            payload = {k: v for k, v in payload.items() if k != "lane"}

        # 1b. Strip scope_lock_id from payload (envelope invariant)
        if "scope_lock_id" in payload:
            payload = {k: v for k, v in payload.items() if k != "scope_lock_id"}

        # 2. Validate payload against registry (using envelope lane)
        validate_intent_payload(intent_type, payload, lane)

        # 3. Enforce scope-lock policy strictly
        spec = get_intent_spec(intent_type)
        sl_policy = spec.get_scope_lock_policy(lane)
        has_sl = bool(scope_lock_id)

        if sl_policy == ScopeLockPolicy.REQUIRED and not has_sl:
            raise ScopeLockRequiredError(f"{intent_type} requires scope_lock_id in lane={lane}")
        if sl_policy == ScopeLockPolicy.FORBIDDEN and has_sl:
            raise ValueError(f"{intent_type} forbids scope_lock_id in lane={lane}")

        intent_id = f"intent_{uuid.uuid4().hex[:12]}"
        now = datetime.now()
        expires_at = now + timedelta(days=expires_in_days)

        self._store.insert_intent(
            intent_id=intent_id,
            intent_type=intent_type,
            payload=payload,
            impact_score=impact_score,
            status=IntentStatus.STAGED.value,
            created_at=now,
            expires_at=expires_at,
            scope_lock_id=scope_lock_id,
            supersedes_intent_id=supersedes_intent_id,
            lane=lane,
            proposal_id=proposal_id,
        )

        # Create and cache intent object
        intent = WriteIntent(
            intent_id=intent_id,
            intent_type=intent_type,
            lane=lane,
            payload=payload,
            impact_score=impact_score,
            status=IntentStatus.STAGED,
            created_at=now,
            expires_at=expires_at,
            scope_lock_id=scope_lock_id,
            supersedes_intent_id=supersedes_intent_id,
            proposal_id=proposal_id,
        )
        self._intent_cache[intent_id] = intent

        logger.info(f"Intent staged: {intent_id} (type={intent_type}, lane={lane})")
        return intent

    def _reconstruct_intent(self, data: Dict[str, Any]) -> WriteIntent:
        """Reconstruct a WriteIntent from a store dict."""
        created = data["created_at"]
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        expires = data.get("expires_at")
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires)
        return WriteIntent(
            intent_id=data["intent_id"],
            intent_type=data["intent_type"],
            lane=data.get("lane", "grounded"),
            payload=data.get("payload", {}),
            impact_score=float(data.get("impact_score", 0.0)),
            status=IntentStatus(data["status"]),
            created_at=created,
            expires_at=expires,
            scope_lock_id=data.get("scope_lock_id"),
            supersedes_intent_id=data.get("supersedes_intent_id"),
            proposal_id=data.get("proposal_id"),
        )

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

    def execute_batch(
        self,
        intent_ids: List[str],
        execution_id: str,
    ) -> Dict[str, Any]:
        """
        Execute a batch of approved intents atomically.

        POLICY (P1-B): Scope-lock uniformity enforcement.
        - If all intents share the same scope_lock_id → execute all.
        - If intents have mixed scope_lock_ids → HOLD all (defer).
        - None is treated as a distinct scope (fail-closed).
        - Status events are emitted for each HOLD (auditable).

        Returns dict with 'executed' and 'held' lists of intent IDs.
        """
        if not intent_ids:
            return {"executed": [], "held": []}

        # Resolve all intents and check they're approved
        intents = []
        for iid in intent_ids:
            intent = self._get_or_raise(iid)
            if intent.status != IntentStatus.APPROVED:
                raise ValueError(f"Intent {iid} is not APPROVED (status={intent.status.value})")
            intents.append(intent)

        # Collect distinct scope_lock_ids (None counts as distinct scope)
        scope_ids = {i.scope_lock_id for i in intents}

        # Mixed-scope check (>1 distinct value, including None)
        if len(scope_ids) > 1:
            held_ids = []
            for intent in intents:
                try:
                    self._assert_transition_allowed(intent.status, IntentStatus.DEFERRED)
                    self._append_event(
                        intent,
                        to_status=IntentStatus.DEFERRED,
                        actor_type="system",
                        actor_id="batch_policy",
                        rationale="HOLD: mixed scope-lock batch",
                    )
                    held_ids.append(intent.intent_id)
                except IntentTransitionError:
                    logger.warning(
                        f"Cannot HOLD intent {intent.intent_id} "
                        f"(status={intent.status}): transition not allowed"
                    )
            return {"executed": [], "held": held_ids}

        # Uniform scope — execute all
        executed_ids = []
        for intent in intents:
            result = self.execute(intent.intent_id, execution_id)
            executed_ids.append(result.intent_id)
        return {"executed": executed_ids, "held": []}

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

        # Get expirable intents from store
        expirable = self._store.list_expirable_intents(now)

        for intent_data in expirable:
            intent_id = intent_data["intent_id"]
            try:
                # Load intent to cache if not present
                _intent = self._get_or_raise(intent_id)  # noqa: F841
                self.expire(intent_id)
                expired_ids.append(intent_id)
            except IntentTransitionError:
                pass  # Already in a state that can't expire
            except IntentNotFoundError:
                pass  # Intent doesn't exist in cache

        return expired_ids

    def reactivate_deferred(self) -> List[str]:
        """
        Reactivate deferred intents where defer_until has passed.
        
        Returns list of reactivated intent IDs.
        """
        reactivated_ids = []
        now = datetime.now()

        # Get deferred intents from store
        deferred = self._store.list_intents_by_status(IntentStatus.DEFERRED.value)

        for intent_data in deferred:
            intent_id = intent_data["intent_id"]

            # Get events for this intent
            events = self._store.get_events(intent_id)

            # Find the defer event with defer_until
            defer_until = None
            for e in reversed(events):
                if e.get("to_status") == IntentStatus.DEFERRED.value and e.get("defer_until"):
                    defer_until = e["defer_until"]
                    break

            if defer_until and now >= defer_until:
                try:
                    # Load intent and reactivate
                    intent = self._get_or_raise(intent_id)
                    self._append_event(
                        intent,
                        to_status=IntentStatus.AWAITING_HITL,
                        actor_type="system",
                        actor_id="defer_service",
                        rationale=f"Reactivated after defer_until={defer_until.isoformat()}",
                    )
                    reactivated_ids.append(intent_id)
                except IntentNotFoundError:
                    pass

        return reactivated_ids

    # =========================================================================
    # Queries
    # =========================================================================

    def list_staged(self, intent_type: str = None) -> list:
        staged = self._store.list_intents_by_status('staged')
        if intent_type:
            staged = [i for i in staged if i['intent_type'] == intent_type]
        return staged

    def get(self, intent_id: str) -> Optional[WriteIntent]:
        """Get an intent by ID."""
        # Check cache first
        if intent_id in self._intent_cache:
            return self._intent_cache[intent_id]

        # Load from store
        data = self._store.get_intent(intent_id)
        if not data:
            return None

        # Reconstruct WriteIntent and cache
        intent = WriteIntent(
            intent_id=data["intent_id"],
            intent_type=data["intent_type"],
            lane=data.get("lane", "grounded"),  # Fallback for old records
            payload=data.get("payload", {}),
            impact_score=data.get("impact_score", 0.0),
            status=IntentStatus(data["status"]),
            created_at=data["created_at"] if isinstance(data["created_at"], datetime) else datetime.fromisoformat(data["created_at"]),
            expires_at=data.get("expires_at"),
            scope_lock_id=data.get("scope_lock_id"),
            supersedes_intent_id=data.get("supersedes_intent_id"),
        )
        self._intent_cache[intent_id] = intent
        return intent

    def _get_or_raise(self, intent_id: str) -> WriteIntent:
        """Get an intent or raise IntentNotFoundError."""
        intent = self.get(intent_id)
        if not intent:
            raise IntentNotFoundError(f"Intent not found: {intent_id}")
        return intent

    def list_by_status(self, status: IntentStatus) -> List[WriteIntent]:
        """List intents by status."""
        data_list = self._store.list_intents_by_status(status.value)
        intents = []
        for data in data_list:
            intent = self.get(data["intent_id"])
            if intent:
                intents.append(intent)
        return intents

    def list_pending(self) -> List[WriteIntent]:
        """List intents awaiting human decision."""
        return self.list_by_status(IntentStatus.AWAITING_HITL)

    def get_history(self, intent_id: str) -> List[IntentStatusEvent]:
        """Get all events for an intent."""
        event_data = self._store.get_events(intent_id)
        events = []
        for e in event_data:
            events.append(IntentStatusEvent(
                event_id=e["event_id"],
                intent_id=e["intent_id"],
                from_status=IntentStatus(e["from_status"]),
                to_status=IntentStatus(e["to_status"]),
                actor_type=e["actor_type"],
                actor_id=e["actor_id"],
                created_at=e["created_at"] if isinstance(e["created_at"], datetime) else datetime.fromisoformat(e["created_at"]),
                rationale=e.get("rationale"),
                defer_until=e.get("defer_until"),
                execution_id=e.get("execution_id"),
                error=e.get("error"),
            ))
        return events

    def _has_approved_event(self, intent_id: str) -> bool:
        """Check if intent has an approved event in its history."""
        return self._store.has_event_with_status(intent_id, IntentStatus.APPROVED.value)


# Global instance (no DB client - must be configured)
write_intent_service = WriteIntentService()
