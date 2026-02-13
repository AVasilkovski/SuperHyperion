"""
P1-B: Scope-lock mixed-batch → HOLD policy tests.

Verifies execute_batch() enforces:
- Uniform scope_lock_id → all executed
- Mixed scope_lock_id  → all held (deferred)
- None treated as distinct scope (fail-closed)
- Empty batch → no-op
"""

import pytest

from src.hitl.intent_service import (
    IntentStatus,
    WriteIntentService,
)


@pytest.fixture
def svc():
    """Fresh WriteIntentService with InMemoryStore."""
    return WriteIntentService()


def _stage_and_approve(svc, intent_type="metrics_update", scope_lock_id=None, lane="grounded"):
    """Helper: stage an intent and ensure it's approved."""
    intent = svc.stage(
        intent_type=intent_type,
        payload={"metrics": {"cpu": 50}},
        scope_lock_id=scope_lock_id,
        lane=lane,
    )
    # approve explicitly since submit_for_review doesn't auto-approve in code yet
    svc.submit_for_review(intent.intent_id)
    svc.approve(intent.intent_id, approver_id="reviewer", rationale="ok")
    return svc.get(intent.intent_id)


class TestExecuteBatchUniformScope:
    """All intents share the same scope_lock_id → executed."""

    def test_uniform_scope_executes_all(self, svc):
        i1 = _stage_and_approve(svc, scope_lock_id="scope-A")
        i2 = _stage_and_approve(svc, scope_lock_id="scope-A")

        result = svc.execute_batch([i1.intent_id, i2.intent_id], "exec-1")

        assert len(result["executed"]) == 2
        assert len(result["held"]) == 0
        assert svc.get(i1.intent_id).status == IntentStatus.EXECUTED
        assert svc.get(i2.intent_id).status == IntentStatus.EXECUTED

    def test_uniform_none_scope_executes_all(self, svc):
        """All None scope_lock_id = single distinct scope → execute."""
        i1 = _stage_and_approve(svc, scope_lock_id=None)
        i2 = _stage_and_approve(svc, scope_lock_id=None)

        result = svc.execute_batch([i1.intent_id, i2.intent_id], "exec-2")

        assert len(result["executed"]) == 2
        assert len(result["held"]) == 0


class TestExecuteBatchMixedScope:
    """Mixed scope_lock_ids → all held (deferred)."""

    def test_mixed_scope_holds_all(self, svc):
        i1 = _stage_and_approve(svc, scope_lock_id="scope-A")
        i2 = _stage_and_approve(svc, scope_lock_id="scope-B")

        result = svc.execute_batch([i1.intent_id, i2.intent_id], "exec-3")

        assert len(result["executed"]) == 0
        assert len(result["held"]) == 2
        assert svc.get(i1.intent_id).status == IntentStatus.DEFERRED
        assert svc.get(i2.intent_id).status == IntentStatus.DEFERRED

    def test_none_vs_value_is_mixed(self, svc):
        """None + 'scope-A' = mixed → HOLD (fail-closed)."""
        i1 = _stage_and_approve(svc, scope_lock_id=None)
        i2 = _stage_and_approve(svc, scope_lock_id="scope-A")

        result = svc.execute_batch([i1.intent_id, i2.intent_id], "exec-4")

        assert len(result["executed"]) == 0
        assert len(result["held"]) == 2

    def test_held_intents_have_rationale_event(self, svc):
        """HOLD emits auditable status events with rationale."""
        i1 = _stage_and_approve(svc, scope_lock_id="scope-A")
        i2 = _stage_and_approve(svc, scope_lock_id="scope-B")

        svc.execute_batch([i1.intent_id, i2.intent_id], "exec-5")

        history = svc.get_history(i1.intent_id)
        hold_events = [e for e in history if e.rationale and "HOLD" in e.rationale]
        assert len(hold_events) == 1
        assert hold_events[0].to_status == IntentStatus.DEFERRED


class TestExecuteBatchEdgeCases:
    """Edge cases."""

    def test_empty_batch_noop(self, svc):
        result = svc.execute_batch([], "exec-6")
        assert result == {"executed": [], "held": []}

    def test_single_intent_batch(self, svc):
        """Single-intent batch always has uniform scope → execute."""
        i1 = _stage_and_approve(svc, scope_lock_id="scope-A")

        result = svc.execute_batch([i1.intent_id], "exec-7")

        assert len(result["executed"]) == 1
        assert len(result["held"]) == 0
