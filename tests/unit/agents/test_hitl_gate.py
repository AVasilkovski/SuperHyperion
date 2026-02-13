"""
HITL Gates Tests

v2.1: Tests for HITL gate triggering and audit logging.
"""


import pytest

from src.hitl.audit import HITLAuditLog
from src.hitl.base import HITLDecision
from src.hitl.epistemic_gate import EpistemicApprovalGate
from src.hitl.impact_gate import HighImpactWriteCheckpoint


class TestEpistemicApprovalGate:
    """Test epistemic gate triggering."""

    @pytest.fixture
    def gate(self):
        return EpistemicApprovalGate(confidence_threshold=0.7)

    def test_triggers_on_speculative_to_supported(self, gate):
        """Gate fires on SPECULATIVE → SUPPORTED."""
        context = {
            "current_status": "speculative",
            "proposed_status": "supported",
            "confidence": 0.6,
        }
        assert gate.should_trigger(context) is True

    def test_triggers_on_supported_to_proven(self, gate):
        """Gate fires on SUPPORTED → PROVEN."""
        context = {
            "current_status": "supported",
            "proposed_status": "proven",
            "confidence": 0.8,
        }
        assert gate.should_trigger(context) is True

    def test_skips_same_status(self, gate):
        """Gate does not fire on same status."""
        context = {
            "current_status": "supported",
            "proposed_status": "supported",
            "confidence": 0.6,
        }
        assert gate.should_trigger(context) is False

    def test_triggers_on_confidence_threshold_crossing(self, gate):
        """Gate fires when confidence crosses 0.7."""
        context = {
            "current_status": "speculative",
            "proposed_status": "speculative",
            "confidence": 0.8,
            "previous_confidence": 0.5,
        }
        assert gate.should_trigger(context) is True

    def test_creates_pending_item(self, gate):
        """Creates proper pending item."""
        context = {
            "claim_id": "C1",
            "current_status": "speculative",
            "proposed_status": "supported",
            "confidence": 0.75,
            "evidence": [{"success": True}],
        }

        pending = gate.create_pending_item(context)

        assert pending.claim_id == "C1"
        assert pending.item_type == "epistemic_transition"
        assert pending.current_status == "speculative"
        assert pending.proposed_status == "supported"


class TestHighImpactWriteCheckpoint:
    """Test impact gate triggering."""

    @pytest.fixture
    def gate(self):
        return HighImpactWriteCheckpoint(impact_threshold=0.5)

    def test_computes_impact_score(self, gate):
        """Impact score calculation."""
        context = {
            "graph_centrality": 0.5,
            "new_confidence": 0.8,
            "old_confidence": 0.3,
            "downstream_dependency_count": 10,
        }

        score = gate.compute_impact_score(context)
        assert score > 0

    def test_triggers_on_high_impact(self, gate):
        """Gate fires on high impact score."""
        context = {
            "graph_centrality": 0.8,
            "new_confidence": 0.9,
            "old_confidence": 0.1,
            "downstream_dependency_count": 20,
        }

        # High centrality, big delta, many dependencies
        assert gate.should_trigger(context) is True

    def test_skips_low_impact(self, gate):
        """Gate does not fire on low impact."""
        context = {
            "graph_centrality": 0.1,
            "new_confidence": 0.5,
            "old_confidence": 0.5,
            "downstream_dependency_count": 1,
        }

        assert gate.should_trigger(context) is False


class TestHITLAuditLog:
    """Test audit log immutability and queries."""

    @pytest.fixture
    def audit(self):
        return HITLAuditLog()

    def test_logs_decision(self, audit):
        """Logs a decision and returns event ID."""
        decision = HITLDecision(
            action="approve",
            rationale="Evidence sufficient",
            approver_id="user123",
        )

        event_id = audit.log_decision("C1", decision, "epistemic")

        assert event_id.startswith("evt_")

    def test_logs_gate_triggered(self, audit):
        """Logs gate trigger event."""
        event_id = audit.log_gate_triggered(
            claim_id="C1",
            gate_type="epistemic",
            trigger_reason="Status transition"
        )

        assert event_id.startswith("evt_")

    def test_get_decision_history(self, audit):
        """Retrieves decision history for a claim."""
        decision = HITLDecision(
            action="approve",
            rationale="OK",
            approver_id="user123",
        )

        audit.log_decision("C1", decision, "epistemic")
        audit.log_decision("C2", decision, "epistemic")
        audit.log_decision("C1", decision, "impact")

        history = audit.get_decision_history("C1")
        assert len(history) == 2

    def test_audit_is_append_only(self, audit):
        """Audit entries cannot be modified."""
        decision = HITLDecision(
            action="approve",
            rationale="OK",
            approver_id="user123",
        )

        audit.log_decision("C1", decision, "epistemic")

        # Get events
        events = audit.get_all_events()
        original_count = len(events)

        # Try to modify (should not affect internal state)
        events.append(None)

        # Internal state unchanged
        assert len(audit.get_all_events()) == original_count

    def test_count_by_action(self, audit):
        """Counts events by action type."""
        audit.log_decision("C1", HITLDecision(
            action="approve", rationale="", approver_id=""
        ), "")
        audit.log_decision("C2", HITLDecision(
            action="reject", rationale="", approver_id=""
        ), "")
        audit.log_decision("C3", HITLDecision(
            action="approve", rationale="", approver_id=""
        ), "")

        counts = audit.count_by_action()
        assert counts["approve"] == 2
        assert counts["reject"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
