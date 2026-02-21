"""
Tests for OntologySteward Proposal Wiring (Phase 16.2)

Verifies:
- _to_operator_tuples() handles TypeDB row keys (eid/cid/slid/conf/role/fm/rs)
- _derive_scope_lock_id() determinism (max conf, tie-break on evid)
- _generate_and_stage_proposals() stages correct intents
"""

from unittest.mock import MagicMock, patch

from src.agents.ontology_steward import (
    OntologySteward,
    q_delete_session_ended_at,
    q_delete_session_run_status,
)
from src.epistemology.evidence_roles import EvidenceRole


class TestToOperatorTuples:
    """Tests for _to_operator_tuples adapter."""

    def setup_method(self):
        self.steward = OntologySteward()

    def test_handles_typedb_row_keys(self):
        """Should correctly parse TypeDB variable-named keys."""
        rows = [
            {"eid": "ev-1", "cid": "c1", "slid": "sl-1", "conf": 0.9, "role": "support"},
            {"eid": "nev-1", "cid": "c1", "slid": "sl-1", "conf": 0.7, "role": "refute",
             "fm": "null_effect", "rs": 0.7},
        ]

        tuples = self.steward._to_operator_tuples(rows)

        assert len(tuples) == 2

        # First: validation channel (no fm/rs)
        ev1, role1, channel1 = tuples[0]
        assert role1 == EvidenceRole.SUPPORT
        assert channel1 == "validation"

        # Second: negative channel (has fm/rs)
        ev2, role2, channel2 = tuples[1]
        assert role2 == EvidenceRole.REFUTE
        assert channel2 == "negative"

    def test_handles_legacy_keys(self):
        """Should fall back to legacy keys if DB keys missing."""
        rows = [
            {"entity-id": "ev-2", "claim-id": "c2", "scope-lock-id": "sl-2",
             "confidence-score": 0.8, "evidence-role": "support"},
        ]

        tuples = self.steward._to_operator_tuples(rows)

        assert len(tuples) == 1
        _, role, channel = tuples[0]
        assert role == EvidenceRole.SUPPORT
        assert channel == "validation"

    def test_skips_invalid_roles(self):
        """Should skip rows with invalid roles."""
        rows = [
            {"eid": "ev-1", "cid": "c1", "role": "invalid_role"},
            {"eid": "ev-2", "cid": "c1", "role": "support"},
        ]

        tuples = self.steward._to_operator_tuples(rows)

        assert len(tuples) == 1
        assert tuples[0][1] == EvidenceRole.SUPPORT


class TestDeriveScopeLockId:
    """Tests for _derive_scope_lock_id determinism."""

    def setup_method(self):
        self.steward = OntologySteward()

    def test_selects_max_confidence(self):
        """Should select scope-lock from highest confidence evidence."""
        evidence = [
            {"eid": "ev-1", "conf": 0.7, "slid": "sl-low"},
            {"eid": "ev-2", "conf": 0.9, "slid": "sl-high"},
            {"eid": "ev-3", "conf": 0.8, "slid": "sl-mid"},
        ]

        result = self.steward._derive_scope_lock_id(evidence)
        assert result == "sl-high"

    def test_tiebreak_by_evidence_id(self):
        """Should use lexicographic evid for tie-break."""
        evidence = [
            {"eid": "ev-b", "conf": 0.9, "slid": "sl-b"},
            {"eid": "ev-a", "conf": 0.9, "slid": "sl-a"},
            {"eid": "ev-c", "conf": 0.9, "slid": "sl-c"},
        ]

        result = self.steward._derive_scope_lock_id(evidence)
        # ev-a comes first lexicographically
        assert result == "sl-a"

    def test_skips_missing_scope_lock(self):
        """Should skip evidence without scope-lock."""
        evidence = [
            {"eid": "ev-1", "conf": 0.9},  # no slid
            {"eid": "ev-2", "conf": 0.7, "slid": "sl-ok"},
        ]

        result = self.steward._derive_scope_lock_id(evidence)
        assert result == "sl-ok"

    def test_returns_none_if_all_missing(self):
        """Should return None if no evidence has scope-lock."""
        evidence = [
            {"eid": "ev-1", "conf": 0.9},
            {"eid": "ev-2", "conf": 0.7},
        ]

        result = self.steward._derive_scope_lock_id(evidence)
        assert result is None

    def test_handles_legacy_keys(self):
        """Should accept legacy scope-lock key names."""
        evidence = [
            {"entity-id": "ev-1", "confidence-score": 0.9, "scope-lock-id": "sl-legacy"},
        ]

        result = self.steward._derive_scope_lock_id(evidence)
        assert result == "sl-legacy"


class TestGenerateAndStageProposals:
    """Integration tests for _generate_and_stage_proposals."""

    def setup_method(self):
        self.steward = OntologySteward()

    @patch.object(OntologySteward, '_fetch_session_evidence')
    @patch('src.hitl.intent_service.write_intent_service')
    def test_stages_proposal_for_sufficient_evidence(self, mock_service, mock_fetch):
        """Should stage proposal when MIN_EVIDENCE_COUNT met."""
        mock_fetch.return_value = [
            {"eid": "ev-1", "cid": "claim-1", "slid": "sl-1", "conf": 0.9, "role": "support"},
            {"eid": "ev-2", "cid": "claim-1", "slid": "sl-1", "conf": 0.8, "role": "support"},
        ]
        mock_service.stage = MagicMock()

        self.steward._generate_and_stage_proposals("sess-123")

        # Should have called stage once
        assert mock_service.stage.call_count == 1

        call_kwargs = mock_service.stage.call_args[1]
        assert call_kwargs["intent_type"] == "stage_epistemic_proposal"
        assert call_kwargs["lane"] == "grounded"
        assert "lane" not in call_kwargs["payload"]  # lane in envelope, not payload

    @patch.object(OntologySteward, '_fetch_session_evidence')
    @patch('src.hitl.intent_service.write_intent_service')
    def test_skips_hold_action(self, mock_service, mock_fetch):
        """Should NOT stage if action is HOLD (insufficient evidence)."""
        # Only 1 evidence row (below MIN_EVIDENCE_COUNT=2)
        mock_fetch.return_value = [
            {"eid": "ev-1", "cid": "claim-1", "slid": "sl-1", "conf": 0.9, "role": "support"},
        ]
        mock_service.stage = MagicMock()

        self.steward._generate_and_stage_proposals("sess-123")

        # Should NOT have called stage (HOLD action)
        assert mock_service.stage.call_count == 0

    @patch.object(OntologySteward, '_fetch_session_evidence')
    @patch('src.hitl.intent_service.write_intent_service')
    def test_groups_by_claim(self, mock_service, mock_fetch):
        """Should group evidence by claim and stage separate proposals."""
        mock_fetch.return_value = [
            {"eid": "ev-1", "cid": "claim-1", "slid": "sl-1", "conf": 0.9, "role": "support"},
            {"eid": "ev-2", "cid": "claim-1", "slid": "sl-1", "conf": 0.8, "role": "support"},
            {"eid": "ev-3", "cid": "claim-2", "slid": "sl-2", "conf": 0.9, "role": "support"},
            {"eid": "ev-4", "cid": "claim-2", "slid": "sl-2", "conf": 0.8, "role": "support"},
        ]
        mock_service.stage = MagicMock()

        self.steward._generate_and_stage_proposals("sess-123")

        # Should have staged 2 proposals (one per claim)
        assert mock_service.stage.call_count == 2

    @patch.object(OntologySteward, '_fetch_session_evidence')
    @patch('src.hitl.intent_service.write_intent_service')
    def test_derives_scope_lock_from_evidence(self, mock_service, mock_fetch):
        """Should pass derived scope_lock_id to stage()."""
        mock_fetch.return_value = [
            {"eid": "ev-1", "cid": "claim-1", "slid": "sl-high", "conf": 0.95, "role": "support"},
            {"eid": "ev-2", "cid": "claim-1", "slid": "sl-low", "conf": 0.7, "role": "support"},
        ]
        mock_service.stage = MagicMock()

        self.steward._generate_and_stage_proposals("sess-123")

        call_kwargs = mock_service.stage.call_args[1]
        assert call_kwargs["scope_lock_id"] == "sl-high"


class TestTypeQL3QuerySyntax:
    """Regression checks for TypeQL 3 query forms used by steward."""

    def setup_method(self):
        self.steward = OntologySteward()

    def test_fetch_session_evidence_uses_select_not_get(self):
        captured_queries = []

        def _fake_read_query(query: str):
            captured_queries.append(query)
            return []

        self.steward._read_query = _fake_read_query  # type: ignore[method-assign]

        rows = self.steward._fetch_session_evidence("sess-1")

        assert rows == []
        assert len(captured_queries) == 2
        assert "select $eid, $cid, $slid, $conf, $role, $pid;" in captured_queries[0]
        assert "select $eid, $fm, $rs;" in captured_queries[1]
        assert "get $eid" not in captured_queries[0]
        assert "get $eid" not in captured_queries[1]

    def test_delete_session_queries_use_ownership_delete_form(self):
        ended_at_query = q_delete_session_ended_at("sess-1")
        status_query = q_delete_session_run_status("sess-1")

        assert "delete has $t of $s;" in ended_at_query
        assert "delete $s has ended-at $t;" not in ended_at_query
        assert "delete has $old of $s;" in status_query
        assert "delete $s has run-status $old;" not in status_query
