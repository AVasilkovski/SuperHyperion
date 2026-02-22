"""
Tests for WriteIntent Lane Governance (Phase 16.2)

Verifies:
- WriteIntent has lane in envelope
- Lane is stripped from payload if present
- Registry forbids lane in payload
- Scope-lock policy uses envelope lane
"""

from datetime import datetime

import pytest

from src.hitl.intent_service import (
    ScopeLockRequiredError,
    WriteIntentService,
)


# Mock Store
class MockStore:
    def __init__(self):
        self.intents = {}
        self.events = []

    def insert_intent(self, **kwargs):
        self.intents[kwargs["intent_id"]] = kwargs

    def append_event(self, **kwargs):
        self.events.append(kwargs)

    def update_intent_status(self, intent_id, status):
        if intent_id in self.intents:
            self.intents[intent_id]["status"] = status

    def get_intent(self, intent_id):
        return self.intents.get(intent_id)


class TestWriteIntentLaneGovernance:
    """Tests for Phase 16.2 Lane Governance refactor."""

    def setup_method(self):
        self.store = MockStore()
        self.service = WriteIntentService(store=self.store)

    def test_stage_uses_envelope_lane(self):
        """Should store lane in envelope and strip from payload."""
        intent = self.service.stage(
            intent_type="metrics_update",
            payload={"metrics": {"test": 1}, "lane": "grounded"},  # passing lane in payload
            lane="grounded",
        )

        # Check intent object
        assert intent.lane == "grounded"
        assert "lane" not in intent.payload

        # Check store
        stored = self.store.intents[intent.intent_id]
        if "lane" in stored:
            assert stored["lane"] == "grounded"
        assert "lane" not in stored["payload"]

    def test_stage_mismatched_lane_raises(self):
        """Should raise error if payload lane matches mismatched envelope lane."""
        with pytest.raises(ValueError, match="mismatch envelope lane"):
            self.service.stage(
                intent_type="metrics_update",
                payload={"metrics": {}, "lane": "speculative"},
                lane="grounded",
            )

    def test_scope_lock_policy_uses_envelope_lane(self):
        """Should enforce scope lock using envelope lane."""
        # create_proposition requires scope lock in grounded
        with pytest.raises(ScopeLockRequiredError):
            self.service.stage(
                intent_type="create_proposition",
                payload={"claim_id": "c1", "content": "t"},
                lane="grounded",
                # missing scope_lock_id
            )

    def test_propose_agent_alignment(self):
        """Verify ProposeAgent WriteIntent structure aligns."""
        from src.agents.propose_agent import WriteIntent as AgentWriteIntent

        agent_intent = AgentWriteIntent(
            intent_id="i1", intent_type="update_epistemic_status", lane="grounded", payload={}
        )
        d = agent_intent.to_dict()
        assert d["lane"] == "grounded"
        assert d["intent_type"] == "update_epistemic_status"

    def test_registry_forbids_lane_in_payload_directly(self):
        """Registry validation should strictly forbid lane in payload."""
        from src.hitl.intent_registry import validate_intent_payload

        with pytest.raises(ValueError, match="Payload must not contain 'lane'"):
            validate_intent_payload(
                "metrics_update", {"metrics": {}, "lane": "grounded"}, "grounded"
            )

    def test_reconstruction_backward_compatibility(self):
        """Should default to 'grounded' if lane missing in store."""
        # Manually insert old record
        self.store.intents["old_intent"] = {
            "intent_id": "old_intent",
            "intent_type": "metrics_update",
            "payload": {"metrics": {}},
            "status": "staged",
            "created_at": datetime.now(),
            # No lane field
        }

        intent = self.service.get("old_intent")
        assert intent.lane == "grounded"
