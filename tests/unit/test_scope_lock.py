"""
Unit Tests: Scope Lock Gate

Tests for HITL Boundary 1: Scope Lock.
"""

import pytest
from datetime import datetime, timedelta

from src.hitl.scope_lock_gate import (
    ScopeLockGate,
    ScopeDraft,
    ScopeLock,
    ScopeStatus,
)
from src.hitl.base import HITLDecision


class TestScopeDraft:
    """Tests for ScopeDraft (pre-commitment artifact)."""

    def test_draft_creation_assigns_version(self):
        """New draft starts at version 1."""
        draft = ScopeDraft(
            draft_id="draft-001",
            session_id="sess-001",
            hypothesis_h_prime="Aspirin reduces inflammation",
            atomic_claims=[
                {"claim_id": "claim-001", "content": "COX-2 inhibition"},
            ],
        )
        assert draft.version == 1

    def test_draft_digest_is_deterministic(self):
        """Same content produces same digest."""
        params = {
            "draft_id": "draft-002",
            "session_id": "sess-002",
            "hypothesis_h_prime": "Hypothesis X",
            "atomic_claims": [{"claim_id": "claim-x"}],
        }
        draft1 = ScopeDraft(**params)
        draft2 = ScopeDraft(**params)
        
        assert draft1.digest() == draft2.digest()

    def test_draft_digest_differs_for_different_claims(self):
        """Different claims produce different digest."""
        draft1 = ScopeDraft(
            draft_id="draft-003",
            session_id="sess-003",
            hypothesis_h_prime="Hypothesis Y",
            atomic_claims=[{"claim_id": "claim-y1"}],
        )
        draft2 = ScopeDraft(
            draft_id="draft-003",
            session_id="sess-003",
            hypothesis_h_prime="Hypothesis Y",
            atomic_claims=[{"claim_id": "claim-y2"}],
        )
        
        assert draft1.digest() != draft2.digest()


class TestScopeLock:
    """Tests for ScopeLock (immutable commitment artifact)."""

    def test_lock_is_valid_when_not_expired(self):
        """Lock is valid within expiry window."""
        lock = ScopeLock(
            lock_id="lock-001",
            session_id="sess-001",
            hypothesis_h_prime="Test hypothesis",
            claim_ids=["claim-001"],
            constraints={},
            derivation_hash="abc123",
            approver_id="human-001",
            approved_at=datetime.now(),
        )
        
        assert lock.is_valid()

    def test_lock_invalid_when_expired(self):
        """Lock is invalid after expiry."""
        lock = ScopeLock(
            lock_id="lock-002",
            session_id="sess-002",
            hypothesis_h_prime="Test hypothesis",
            claim_ids=["claim-002"],
            constraints={},
            derivation_hash="def456",
            approver_id="human-001",
            approved_at=datetime.now() - timedelta(days=10),
            expires_at=datetime.now() - timedelta(days=3),
        )
        
        assert not lock.is_valid()

    def test_lock_invalid_when_status_expired(self):
        """Lock is invalid when status is EXPIRED."""
        lock = ScopeLock(
            lock_id="lock-003",
            session_id="sess-003",
            hypothesis_h_prime="Test hypothesis",
            claim_ids=["claim-003"],
            constraints={},
            derivation_hash="ghi789",
            approver_id="human-001",
            approved_at=datetime.now(),
            status=ScopeStatus.EXPIRED,
        )
        
        assert not lock.is_valid()


class TestScopeLockGate:
    """Tests for ScopeLockGate (HITL Boundary 1)."""

    def test_gate_triggers_when_claims_exist_but_no_lock(self):
        """Gate triggers after decomposition without existing lock."""
        gate = ScopeLockGate()
        
        context = {
            "atomic_claims": [{"claim_id": "claim-001"}],
            "hypothesis_h_prime": "Test hypothesis",
        }
        
        assert gate.should_trigger(context)

    def test_gate_does_not_trigger_without_claims(self):
        """Gate does not trigger if no claims from decomposition."""
        gate = ScopeLockGate()
        
        context = {
            "hypothesis_h_prime": "Test hypothesis",
        }
        
        assert not gate.should_trigger(context)

    def test_gate_creates_pending_item(self):
        """Gate creates pending item with draft reference."""
        gate = ScopeLockGate()
        
        context = {
            "session_id": "sess-test",
            "hypothesis_h_prime": "Test hypothesis",
            "atomic_claims": [
                {"claim_id": "claim-a", "content": "Claim A"},
                {"claim_id": "claim-b", "content": "Claim B"},
            ],
        }
        
        pending = gate.create_pending_item(context)
        
        assert pending.item_type == "scope_lock"
        assert pending.current_status == ScopeStatus.REVIEW.value
        assert "draft_" in pending.claim_id

    def test_gate_approval_creates_lock(self):
        """Approving pending item creates scope lock."""
        gate = ScopeLockGate()
        
        context = {
            "session_id": "sess-approval-test",
            "hypothesis_h_prime": "Approved hypothesis",
            "atomic_claims": [{"claim_id": "claim-approved"}],
        }
        
        pending = gate.create_pending_item(context)
        
        decision = HITLDecision(
            action="approve",
            rationale="Scope looks good",
            approver_id="human-tester",
        )
        
        result = gate.process_decision(pending, decision)
        
        assert result["approved"]
        assert "scope_lock_id" in result
        assert result["scope_lock_id"].startswith("lock_")

    def test_gate_rejection_returns_expired_status(self):
        """Rejecting pending item returns expired status."""
        gate = ScopeLockGate()
        
        context = {
            "session_id": "sess-reject-test",
            "hypothesis_h_prime": "Rejected hypothesis",
            "atomic_claims": [{"claim_id": "claim-rejected"}],
        }
        
        pending = gate.create_pending_item(context)
        
        decision = HITLDecision(
            action="reject",
            rationale="Scope too broad",
            approver_id="human-tester",
        )
        
        result = gate.process_decision(pending, decision)
        
        assert not result["approved"]
        assert result["status"] == ScopeStatus.EXPIRED.value

    def test_validate_scope_lock_returns_true_for_valid_lock(self):
        """validate_scope_lock returns True for valid lock."""
        gate = ScopeLockGate()
        
        # Create and approve a scope
        context = {
            "atomic_claims": [{"claim_id": "claim-valid"}],
            "hypothesis_h_prime": "Valid hypothesis",
        }
        pending = gate.create_pending_item(context)
        decision = HITLDecision(
            action="approve",
            rationale="Approved",
            approver_id="human-001",
        )
        result = gate.process_decision(pending, decision)
        
        lock_id = result["scope_lock_id"]
        
        assert gate.validate_scope_lock(lock_id)

    def test_validate_scope_lock_returns_false_for_unknown_lock(self):
        """validate_scope_lock returns False for unknown lock."""
        gate = ScopeLockGate()
        
        assert not gate.validate_scope_lock("lock_nonexistent")
