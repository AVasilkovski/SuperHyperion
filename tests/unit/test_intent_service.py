"""
Unit Tests: WriteIntentService

Constitutional invariant tests:
- Illegal transitions raise
- Terminal states are terminal
- executed can't happen without prior approved
- Expiration is deterministic
- Events are append-only and complete
"""

import pytest
from datetime import datetime, timedelta

from src.hitl.intent_service import (
    WriteIntentService,
    WriteIntent,
    IntentStatus,
    IntentStatusEvent,
    IntentTransitionError,
    IntentNotFoundError,
    ScopeLockRequiredError,
    TERMINAL_STATES,
    ALLOWED_TRANSITIONS,
)


from unittest.mock import patch
from src.hitl.intent_registry import IntentSpec, ScopeLockPolicy, ApprovalPolicy

# Define a permissible test spec
TEST_INTENT_SPEC = IntentSpec(
    intent_type="test",
    allowed_fields=frozenset({"v", "claim_id"}),
    required_fields=frozenset(),
    required_id_fields=frozenset(),
    allowed_lanes=frozenset({"grounded", "speculative"}),
    scope_lock_by_lane={"grounded": ScopeLockPolicy.OPTIONAL, "speculative": ScopeLockPolicy.OPTIONAL},
    approval_by_lane={"grounded": ApprovalPolicy.HITL, "speculative": ApprovalPolicy.HITL},
    description="Test intent"
)

# Define update_epistemic_status mock (strict)
STRICT_INTENT_SPEC = IntentSpec(
    intent_type="update_epistemic_status",
    allowed_fields=frozenset({"claim_id"}),
    required_fields=frozenset({"claim_id"}),
    required_id_fields=frozenset({"claim_id"}),
    allowed_lanes=frozenset({"grounded"}),
    scope_lock_by_lane={"grounded": ScopeLockPolicy.REQUIRED},
    approval_by_lane={"grounded": ApprovalPolicy.HITL},
    description="Strict intent"
)

class TestIntentStatus:
    # ... (existing content, simplified for brevity in replacement if needed, but replace tool handles chunks)
    """Tests for IntentStatus enum and state machine rules."""

    def test_terminal_states_are_defined(self):
        """Terminal states include rejected, cancelled, expired, executed, failed."""
        assert IntentStatus.REJECTED in TERMINAL_STATES
        assert IntentStatus.CANCELLED in TERMINAL_STATES
        assert IntentStatus.EXPIRED in TERMINAL_STATES
        assert IntentStatus.EXECUTED in TERMINAL_STATES
        assert IntentStatus.FAILED in TERMINAL_STATES

    def test_terminal_states_have_no_outgoing_transitions(self):
        """Terminal states have empty transition sets."""
        for status in TERMINAL_STATES:
            allowed = ALLOWED_TRANSITIONS.get(status, set())
            assert len(allowed) == 0, f"{status.value} should have no outgoing transitions"

    def test_staged_can_transition_to_awaiting_or_cancelled(self):
        """Staged can go to awaiting_hitl or cancelled."""
        allowed = ALLOWED_TRANSITIONS[IntentStatus.STAGED]
        assert IntentStatus.AWAITING_HITL in allowed
        assert IntentStatus.CANCELLED in allowed
        assert len(allowed) == 2

    def test_awaiting_hitl_has_all_decision_outcomes(self):
        """Awaiting HITL can go to approved, rejected, deferred, cancelled, expired."""
        allowed = ALLOWED_TRANSITIONS[IntentStatus.AWAITING_HITL]
        assert IntentStatus.APPROVED in allowed
        assert IntentStatus.REJECTED in allowed
        assert IntentStatus.DEFERRED in allowed
        assert IntentStatus.CANCELLED in allowed
        assert IntentStatus.EXPIRED in allowed


class TestWriteIntentService:
    """Tests for WriteIntentService lifecycle operations."""

    @pytest.fixture(autouse=True)
    def mock_registry(self):
        """Mock the registry with test intents."""
        with patch.dict("src.hitl.intent_registry.INTENT_REGISTRY", {
            "test": TEST_INTENT_SPEC,
            "update_epistemic_status": STRICT_INTENT_SPEC,
            "housekeeping": IntentSpec(
                intent_type="housekeeping",
                allowed_fields=frozenset(),
                required_fields=frozenset(),
                required_id_fields=frozenset(),
                allowed_lanes=frozenset({"grounded"}),
                scope_lock_by_lane={"grounded": ScopeLockPolicy.OPTIONAL},
                approval_by_lane={"grounded": ApprovalPolicy.AUTO},
            )
        }):
            yield

    @pytest.fixture
    def service(self):
        """Fresh service instance for each test."""
        return WriteIntentService()

    def test_stage_creates_intent_in_staged_status(self, service):
        """Staging creates intent with STAGED status."""
        intent = service.stage(
            intent_type="test",  # switch to test
            payload={"claim_id": "claim-001"},
            impact_score=0.5,
        )
        
        assert intent.status == IntentStatus.STAGED
        assert intent.intent_type == "test"
        assert intent.impact_score == 0.5

    def test_stage_sets_default_expiry(self, service):
        """Staging sets default 7-day expiry."""
        intent = service.stage(
            intent_type="test",
            payload={},
        )
        
        assert intent.expires_at is not None
        # Should be ~7 days from now
        delta = intent.expires_at - intent.created_at
        assert delta.days == 7

    def test_submit_for_review_transitions_to_awaiting(self, service):
        """Submit transitions staged → awaiting_hitl."""
        intent = service.stage(intent_type="test", payload={})
        intent = service.submit_for_review(intent.intent_id)
        
        assert intent.status == IntentStatus.AWAITING_HITL

    def test_approve_transitions_to_approved(self, service):
        """Approve transitions awaiting_hitl → approved."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        intent = service.approve(
            intent.intent_id,
            approver_id="human-001",
            rationale="Looks good",
        )
        
        assert intent.status == IntentStatus.APPROVED

    def test_reject_transitions_to_rejected(self, service):
        """Reject transitions awaiting_hitl → rejected."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        intent = service.reject(
            intent.intent_id,
            rejector_id="human-001",
            rationale="Too risky",
        )
        
        assert intent.status == IntentStatus.REJECTED

    def test_defer_transitions_to_deferred(self, service):
        """Defer transitions awaiting_hitl → deferred."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        intent = service.defer(
            intent.intent_id,
            deferrer_id="human-001",
            until=datetime.now() + timedelta(days=2),
            rationale="Need more info",
        )
        
        assert intent.status == IntentStatus.DEFERRED

    def test_cancel_transitions_to_cancelled(self, service):
        """Cancel transitions staged/awaiting_hitl → cancelled."""
        intent = service.stage(intent_type="test", payload={})
        intent = service.cancel(
            intent.intent_id,
            actor_id="human-001",
            rationale="No longer needed",
        )
        
        assert intent.status == IntentStatus.CANCELLED


class TestIllegalTransitions:
    """Tests for illegal transition enforcement."""

    @pytest.fixture(autouse=True)
    def mock_registry(self):
        with patch.dict("src.hitl.intent_registry.INTENT_REGISTRY", {"test": TEST_INTENT_SPEC}):
            yield

    @pytest.fixture
    def service(self):
        return WriteIntentService()

    def test_cannot_approve_from_staged(self, service):
        """Cannot approve directly from staged."""
        intent = service.stage(intent_type="test", payload={})
        
        with pytest.raises(IntentTransitionError):
            service.approve(intent.intent_id, "human", "reason")

    def test_cannot_execute_from_staged(self, service):
        """Cannot execute from staged."""
        intent = service.stage(intent_type="test", payload={})
        
        with pytest.raises(IntentTransitionError):
            service.execute(intent.intent_id, "exec-001")

    def test_cannot_execute_from_awaiting_hitl(self, service):
        """Cannot execute from awaiting_hitl (must be approved first)."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        
        with pytest.raises(IntentTransitionError):
            service.execute(intent.intent_id, "exec-001")


class TestTerminalStateInvariants:
    """Tests for terminal state immutability."""

    @pytest.fixture(autouse=True)
    def mock_registry(self):
        with patch.dict("src.hitl.intent_registry.INTENT_REGISTRY", {"test": TEST_INTENT_SPEC}):
            yield

    @pytest.fixture
    def service(self):
        return WriteIntentService()

    def test_rejected_is_terminal(self, service):
        """Cannot transition from rejected."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        service.reject(intent.intent_id, "human", "reason")
        
        # Try all possible transitions
        with pytest.raises(IntentTransitionError):
            service.approve(intent.intent_id, "human", "reason")
        
        with pytest.raises(IntentTransitionError):
            service.cancel(intent.intent_id, "human", "reason")

    def test_cancelled_is_terminal(self, service):
        """Cannot transition from cancelled."""
        intent = service.stage(intent_type="test", payload={})
        service.cancel(intent.intent_id, "human", "reason")
        
        with pytest.raises(IntentTransitionError):
            service.submit_for_review(intent.intent_id)

    def test_expired_is_terminal(self, service):
        """Cannot transition from expired."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        service.expire(intent.intent_id)
        
        with pytest.raises(IntentTransitionError):
            service.approve(intent.intent_id, "human", "reason")

    def test_executed_is_terminal(self, service):
        """Cannot transition from executed."""
        intent = service.stage(
            intent_type="test",  # Not a type requiring scope_lock
            payload={},
        )
        service.submit_for_review(intent.intent_id)
        service.approve(intent.intent_id, "human", "reason")
        service.execute(intent.intent_id, "exec-001")
        
        with pytest.raises(IntentTransitionError):
            service.fail(intent.intent_id, "error")


class TestExecutedRequiresApproved:
    """Tests for the critical invariant: executed requires prior approved."""

    @pytest.fixture(autouse=True)
    def mock_registry(self):
        with patch.dict("src.hitl.intent_registry.INTENT_REGISTRY", {"test": TEST_INTENT_SPEC}):
            yield

    @pytest.fixture
    def service(self):
        return WriteIntentService()

    def test_execute_requires_approved_event(self, service):
        """Execute checks for approved event in history."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        service.approve(intent.intent_id, "human", "reason")
        
        # This should work
        intent = service.execute(intent.intent_id, "exec-001")
        assert intent.status == IntentStatus.EXECUTED

    def test_execute_fails_without_approved_event(self, service):
        """Execute fails if no approved event exists."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        
        # Force status to APPROVED without event (simulating corruption)
        intent.status = IntentStatus.APPROVED
        
        # Should still fail because no approved event exists
        with pytest.raises(IntentTransitionError) as exc_info:
            service.execute(intent.intent_id, "exec-001")
        
        assert "no prior 'approved' event" in str(exc_info.value)

    def test_has_approved_event_returns_false_for_new_intent(self, service):
        """_has_approved_event returns False for new intents."""
        intent = service.stage(intent_type="test", payload={})
        
        assert not service._has_approved_event(intent.intent_id)

    def test_has_approved_event_returns_true_after_approval(self, service):
        """_has_approved_event returns True after approval."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        service.approve(intent.intent_id, "human", "reason")
        
        assert service._has_approved_event(intent.intent_id)


class TestScopeLockRequired:
    """Tests for scope_lock_id requirement enforcement."""

    @pytest.fixture(autouse=True)
    def mock_registry(self):
        with patch.dict("src.hitl.intent_registry.INTENT_REGISTRY", {
            "test": TEST_INTENT_SPEC,
            "update_epistemic_status": STRICT_INTENT_SPEC,
            "housekeeping": IntentSpec(
                intent_type="housekeeping",
                allowed_fields=frozenset(),
                required_fields=frozenset(),
                required_id_fields=frozenset(),
                allowed_lanes=frozenset({"grounded"}),
                scope_lock_by_lane={"grounded": ScopeLockPolicy.OPTIONAL},
                approval_by_lane={"grounded": ApprovalPolicy.AUTO},
            )
        }):
            yield

    @pytest.fixture
    def service(self):
        return WriteIntentService()

    def test_stage_fails_missing_scope_lock_strict(self, service):
        """Strict intent fails at stage if scope_lock missing."""
        with pytest.raises(ScopeLockRequiredError):
            service.stage(
                intent_type="update_epistemic_status",
                payload={"claim_id": "claim-001"},
                # No scope_lock_id
            )

    def test_execute_succeeds_with_scope_lock(self, service):
        """Execution succeeds when scope_lock_id is provided."""
        intent = service.stage(
            intent_type="update_epistemic_status",
            payload={"claim_id": "claim-001"},
            scope_lock_id="lock_abc123",
        )
        service.submit_for_review(intent.intent_id)
        service.approve(intent.intent_id, "human", "reason")
        
        intent = service.execute(intent.intent_id, "exec-001")
        assert intent.status == IntentStatus.EXECUTED

    def test_housekeeping_intents_dont_require_scope_lock(self, service):
        """Non-critical intents don't require scope_lock_id."""
        intent = service.stage(
            intent_type="housekeeping",
            payload={},
        )
        service.submit_for_review(intent.intent_id)
        service.approve(intent.intent_id, "human", "reason")
        
        # Should succeed without scope_lock_id
        intent = service.execute(intent.intent_id, "exec-001")
        assert intent.status == IntentStatus.EXECUTED


class TestEventAuditTrail:
    """Tests for append-only event logging."""

    @pytest.fixture(autouse=True)
    def mock_registry(self):
        with patch.dict("src.hitl.intent_registry.INTENT_REGISTRY", {"test": TEST_INTENT_SPEC}):
            yield

    @pytest.fixture
    def service(self):
        return WriteIntentService()

    def test_events_are_recorded_for_each_transition(self, service):
        """Each transition creates an event."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        service.approve(intent.intent_id, "human", "approved")
        service.execute(intent.intent_id, "exec-001")
        
        events = service.get_history(intent.intent_id)
        
        assert len(events) == 3  # submit, approve, execute

    def test_events_contain_actor_and_timestamp(self, service):
        """Events contain actor_type, actor_id, and created_at."""
        intent = service.stage(intent_type="test", payload={})
        
        # Go through full approval flow
        service.submit_for_review(intent.intent_id)
        service.approve(intent.intent_id, "human-001", "reason")
        
        events = service.get_history(intent.intent_id)
        approve_event = [e for e in events if e.to_status == IntentStatus.APPROVED][0]
        
        assert approve_event.actor_type == "human"
        assert approve_event.actor_id == "human-001"
        assert approve_event.created_at is not None

    def test_events_record_from_and_to_status(self, service):
        """Events record both from_status and to_status."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        
        events = service.get_history(intent.intent_id)
        
        assert len(events) == 1
        assert events[0].from_status == IntentStatus.STAGED
        assert events[0].to_status == IntentStatus.AWAITING_HITL

    def test_defer_event_records_defer_until(self, service):
        """Defer events record defer_until timestamp."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        
        defer_until = datetime.now() + timedelta(days=3)
        service.defer(intent.intent_id, "human", defer_until, "waiting for data")
        
        events = service.get_history(intent.intent_id)
        defer_event = [e for e in events if e.to_status == IntentStatus.DEFERRED][0]
        
        assert defer_event.defer_until == defer_until

    def test_execute_event_records_execution_id(self, service):
        """Execute events record execution_id."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        service.approve(intent.intent_id, "human", "reason")
        service.execute(intent.intent_id, "exec-12345")
        
        events = service.get_history(intent.intent_id)
        exec_event = [e for e in events if e.to_status == IntentStatus.EXECUTED][0]
        
        assert exec_event.execution_id == "exec-12345"

    def test_fail_event_records_error(self, service):
        """Fail events record error message."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        service.approve(intent.intent_id, "human", "reason")
        service.fail(intent.intent_id, "Database connection failed")
        
        events = service.get_history(intent.intent_id)
        fail_event = [e for e in events if e.to_status == IntentStatus.FAILED][0]
        
        assert fail_event.error == "Database connection failed"


class TestExpiration:
    """Tests for expiration behavior."""

    @pytest.fixture(autouse=True)
    def mock_registry(self):
        with patch.dict("src.hitl.intent_registry.INTENT_REGISTRY", {"test": TEST_INTENT_SPEC}):
            yield

    @pytest.fixture
    def service(self):
        return WriteIntentService()

    def test_expire_stale_expires_old_intents(self, service):
        """expire_stale expires intents past their expires_at."""
        # Create intent with very short expiry
        intent = service.stage(
            intent_type="test",
            payload={},
            expires_in_days=-1,  # Already expired
        )
        service.submit_for_review(intent.intent_id)
        
        expired_ids = service.expire_stale()
        
        assert intent.intent_id in expired_ids
        assert intent.status == IntentStatus.EXPIRED

    def test_expire_stale_skips_terminal_states(self, service):
        """expire_stale doesn't modify terminal intents."""
        intent = service.stage(intent_type="test", payload={})
        service.cancel(intent.intent_id, "human", "reason")
        
        # Manually set past expiry
        intent.expires_at = datetime.now() - timedelta(days=1)
        
        expired_ids = service.expire_stale()
        
        assert intent.intent_id not in expired_ids
        assert intent.status == IntentStatus.CANCELLED  # Unchanged


class TestDeferredReactivation:
    """Tests for deferred intent reactivation."""

    @pytest.fixture(autouse=True)
    def mock_registry(self):
        with patch.dict("src.hitl.intent_registry.INTENT_REGISTRY", {"test": TEST_INTENT_SPEC}):
            yield

    @pytest.fixture
    def service(self):
        return WriteIntentService()

    def test_reactivate_deferred_resubmits_past_defer_until(self, service):
        """Reactivate transitions deferred → awaiting_hitl when defer_until passed."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        
        # Defer to past time
        defer_until = datetime.now() - timedelta(hours=1)
        service.defer(intent.intent_id, "human", defer_until, "reason")
        
        reactivated = service.reactivate_deferred()
        
        assert intent.intent_id in reactivated
        assert intent.status == IntentStatus.AWAITING_HITL


class TestSupersedes:
    """Tests for intent supersession (back from Bali scenario)."""

    @pytest.fixture(autouse=True)
    def mock_registry(self):
        with patch.dict("src.hitl.intent_registry.INTENT_REGISTRY", {"test": TEST_INTENT_SPEC}):
            yield

    @pytest.fixture
    def service(self):
        return WriteIntentService()

    def test_new_intent_can_supersede_expired(self, service):
        """New intent can reference expired intent via supersedes_intent_id."""
        # Create and expire first intent
        original = service.stage(intent_type="test", payload={"v": 1})
        service.submit_for_review(original.intent_id)
        service.expire(original.intent_id)
        
        # Create new intent that supersedes
        replacement = service.stage(
            intent_type="test",
            payload={"v": 2},
            supersedes_intent_id=original.intent_id,
        )
        
        assert replacement.supersedes_intent_id == original.intent_id
        assert original.status == IntentStatus.EXPIRED  # Unchanged

    def test_expired_intent_remains_immutable(self, service):
        """Expired intent cannot be modified."""
        intent = service.stage(intent_type="test", payload={})
        service.submit_for_review(intent.intent_id)
        service.expire(intent.intent_id)
        
        # Cannot transition
        with pytest.raises(IntentTransitionError):
            service.approve(intent.intent_id, "human", "reason")
