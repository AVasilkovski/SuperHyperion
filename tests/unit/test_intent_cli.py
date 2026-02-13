"""
Unit Tests: Intent CLI

Tests for CLI commands using CliRunner.
Injects InMemoryIntentStore to avoid TypeDB dependency.
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from src.cli import wiring
from src.cli.main import app
from src.hitl.intent_registry import ApprovalPolicy, IntentSpec, ScopeLockPolicy
from src.hitl.intent_service import IntentStatus, WriteIntentService
from src.hitl.intent_store import InMemoryIntentStore

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

# Define generic test_type spec
TEST_TYPE_SPEC = IntentSpec(
    intent_type="test_type",
    allowed_fields=frozenset({"claim_id"}),
    required_fields=frozenset(),
    required_id_fields=frozenset(),
    allowed_lanes=frozenset({"grounded"}),
    scope_lock_by_lane={"grounded": ScopeLockPolicy.OPTIONAL},
    approval_by_lane={"grounded": ApprovalPolicy.HITL},
    description="Test type"
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


runner = CliRunner()


@pytest.fixture
def test_service():
    """Create a fresh test service with InMemory store and mocked registry."""
    store = InMemoryIntentStore()

    with patch.dict("src.hitl.intent_registry.INTENT_REGISTRY", {
        "test": TEST_INTENT_SPEC,
        "test_type": TEST_TYPE_SPEC,
        "update_epistemic_status": STRICT_INTENT_SPEC,
    }):
        service = WriteIntentService(store=store)
        yield service


@pytest.fixture(autouse=True)
def inject_test_service(test_service, monkeypatch):
    """Inject test service into wiring."""
    monkeypatch.setattr(wiring, "_service", test_service)
    yield


class TestIntentList:
    """Tests for `superhyperion intent list`."""

    def test_list_empty_shows_no_intents(self):
        """Empty list shows 'No intents found'."""
        result = runner.invoke(app, ["intent", "list"])

        assert result.exit_code == 0
        assert "No intents found" in result.output

    def test_list_shows_pending_intents(self, test_service):
        """List shows intents awaiting review."""
        # Stage and submit an intent
        intent = test_service.stage(
            intent_type="test_type",
            payload={"claim_id": "claim-001"},
        )
        test_service.submit_for_review(intent.intent_id)

        result = runner.invoke(app, ["intent", "list"])

        assert result.exit_code == 0
        # Table truncates IDs, check for prefix match
        assert "intent_" in result.output
        assert "test_type" in result.output
        assert "awaiting" in result.output

    def test_list_with_status_filter(self, test_service):
        """List filters by status."""
        intent = test_service.stage(intent_type="test", payload={})

        # Staged, not yet submitted
        result = runner.invoke(app, ["intent", "list", "--status", "staged"])

        assert result.exit_code == 0
        # Table truncates IDs, check for partial match
        assert intent.intent_id[:12] in result.output

    def test_list_json_output(self, test_service):
        """--json outputs valid JSON."""
        intent = test_service.stage(intent_type="test", payload={})
        test_service.submit_for_review(intent.intent_id)

        result = runner.invoke(app, ["intent", "list", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["intent_id"] == intent.intent_id


class TestIntentShow:
    """Tests for `superhyperion intent show`."""

    def test_show_displays_intent_details(self, test_service):
        """Show displays intent fields."""
        intent = test_service.stage(
            intent_type="update_epistemic_status",
            payload={"claim_id": "claim-001"},
            scope_lock_id="lock-123",
        )

        result = runner.invoke(app, ["intent", "show", intent.intent_id])

        assert result.exit_code == 0
        assert intent.intent_id in result.output
        assert "update_epistemic_status" in result.output
        assert "lock-123" in result.output

    def test_show_not_found_exits_1(self):
        """Show exits 1 for unknown intent."""
        result = runner.invoke(app, ["intent", "show", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_show_with_history(self, test_service):
        """Show --history includes events."""
        intent = test_service.stage(intent_type="test", payload={})
        test_service.submit_for_review(intent.intent_id)

        result = runner.invoke(app, ["intent", "show", intent.intent_id, "--history"])

        assert result.exit_code == 0
        assert "Event History" in result.output
        assert "awaiting_hitl" in result.output

    def test_show_json_output(self, test_service):
        """--json outputs valid JSON with intent and history."""
        intent = test_service.stage(intent_type="test", payload={})
        test_service.submit_for_review(intent.intent_id)

        result = runner.invoke(app, ["intent", "show", intent.intent_id, "--json", "--history"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "intent" in data
        assert "history" in data
        assert data["intent"]["intent_id"] == intent.intent_id


class TestIntentApprove:
    """Tests for `superhyperion intent approve`."""

    def test_approve_transitions_to_approved(self, test_service):
        """Approve sets status to approved."""
        intent = test_service.stage(intent_type="test", payload={})
        test_service.submit_for_review(intent.intent_id)

        result = runner.invoke(
            app,
            ["intent", "approve", intent.intent_id, "--by", "Anton", "--why", "Looks good"],
        )

        assert result.exit_code == 0
        assert "Approved" in result.output

        # Verify in service
        updated = test_service.get(intent.intent_id)
        assert updated.status == IntentStatus.APPROVED

    def test_approve_not_found_exits_1(self):
        """Approve exits 1 for unknown intent."""
        result = runner.invoke(
            app,
            ["intent", "approve", "nonexistent", "--by", "Anton", "--why", "test"],
        )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_approve_illegal_transition_exits_1(self, test_service):
        """Approve from staged (not awaiting) exits 1."""
        intent = test_service.stage(intent_type="test", payload={})
        # Not submitted for review

        result = runner.invoke(
            app,
            ["intent", "approve", intent.intent_id, "--by", "Anton", "--why", "test"],
        )

        assert result.exit_code == 1
        assert "Transition error" in result.output


class TestIntentReject:
    """Tests for `superhyperion intent reject`."""

    def test_reject_transitions_to_rejected(self, test_service):
        """Reject sets status to rejected."""
        intent = test_service.stage(intent_type="test", payload={})
        test_service.submit_for_review(intent.intent_id)

        result = runner.invoke(
            app,
            ["intent", "reject", intent.intent_id, "--by", "Anton", "--why", "Too risky"],
        )

        assert result.exit_code == 0
        assert "Rejected" in result.output


class TestIntentDefer:
    """Tests for `superhyperion intent defer`."""

    def test_defer_transitions_to_deferred(self, test_service):
        """Defer sets status to deferred."""
        intent = test_service.stage(intent_type="test", payload={})
        test_service.submit_for_review(intent.intent_id)

        result = runner.invoke(
            app,
            [
                "intent", "defer", intent.intent_id,
                "--by", "Anton",
                "--until", "2026-02-01T10:00:00Z",
                "--why", "Need more info",
            ],
        )

        assert result.exit_code == 0
        assert "Deferred" in result.output

    def test_defer_invalid_date_exits_1(self, test_service):
        """Defer with invalid date exits 1."""
        intent = test_service.stage(intent_type="test", payload={})
        test_service.submit_for_review(intent.intent_id)

        result = runner.invoke(
            app,
            [
                "intent", "defer", intent.intent_id,
                "--by", "Anton",
                "--until", "not-a-date",
                "--why", "test",
            ],
        )

        assert result.exit_code == 1
        assert "Invalid datetime" in result.output


class TestIntentCancel:
    """Tests for `superhyperion intent cancel`."""

    def test_cancel_transitions_to_cancelled(self, test_service):
        """Cancel sets status to cancelled."""
        intent = test_service.stage(intent_type="test", payload={})

        result = runner.invoke(
            app,
            ["intent", "cancel", intent.intent_id, "--by", "Anton", "--why", "No longer needed"],
        )

        assert result.exit_code == 0
        assert "Cancelled" in result.output


class TestExpireStale:
    """Tests for `superhyperion intent expire-stale`."""

    def test_expire_stale_no_intents(self):
        """Expire-stale with no stale intents."""
        result = runner.invoke(app, ["intent", "expire-stale"])

        assert result.exit_code == 0
        assert "No stale intents" in result.output

    def test_expire_stale_expires_old_intents(self, test_service):
        """Expire-stale expires intents past expiry."""
        intent = test_service.stage(
            intent_type="test",
            payload={},
            expires_in_days=-1,  # Already expired
        )
        test_service.submit_for_review(intent.intent_id)

        result = runner.invoke(app, ["intent", "expire-stale"])

        assert result.exit_code == 0
        assert intent.intent_id in result.output

    def test_expire_stale_json_output(self, test_service):
        """--json outputs list of expired IDs."""
        result = runner.invoke(app, ["intent", "expire-stale", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "expired" in data
        assert isinstance(data["expired"], list)
