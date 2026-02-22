from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from scripts.ops12_ci_trust_gates import (
    _run_gate,
    _should_enforce_typedb,
    _typedb_ready,
)
from src.agents.integrator_agent import IntegratorAgent
from src.sdk.types import ReplayVerdictV1


@pytest.mark.asyncio
async def test_commit_gate_success_with_mocked_steward_and_verify(tmp_path):
    async def _fake_run(ctx):
        ctx.graph_context["persisted_all_evidence_ids"] = ["ev-ci-1"]
        ctx.graph_context["mutation_ids"] = []
        return ctx

    with (
        patch("scripts.ops12_ci_trust_gates.OntologySteward.insert_to_graph", return_value=None),
        patch(
            "scripts.ops12_ci_trust_gates.OntologySteward.query_graph",
            return_value=[{"eid": "ev-ci-1"}],
        ),
        patch(
            "scripts.ops12_ci_trust_gates.OntologySteward.run", new=AsyncMock(side_effect=_fake_run)
        ),
        patch.object(
            IntegratorAgent,
            "_verify_evidence_primacy",
            return_value=(True, "PASS", {"verified_count": 1}),
        ),
        patch(
            "scripts.ops12_ci_trust_gates.verify_capsule",
            return_value=ReplayVerdictV1(status="PASS", reasons=[], details={}),
        ),
    ):
        ok, payload = await _run_gate("commit", str(tmp_path))

    assert ok is True
    assert payload["replay_status"] == "PASS"
    assert payload["replay_verdict"]["reasons"] == []
    assert payload["governance"]["status"] == "STAGED"


@pytest.mark.asyncio
async def test_commit_gate_fails_early_when_persisted_id_not_linked_in_ledger(tmp_path):
    async def _fake_run(ctx):
        ctx.graph_context["persisted_all_evidence_ids"] = ["ev-ci-1"]
        return ctx

    with (
        patch("scripts.ops12_ci_trust_gates.OntologySteward.insert_to_graph", return_value=None),
        patch("scripts.ops12_ci_trust_gates.OntologySteward.query_graph", return_value=[]),
        patch(
            "scripts.ops12_ci_trust_gates.OntologySteward.run", new=AsyncMock(side_effect=_fake_run)
        ),
    ):
        ok, payload = await _run_gate("commit", str(tmp_path))

    assert ok is False
    assert payload["error"] == "Persisted evidence IDs missing from ledger linkage"
    assert payload["missing_evidence_ids"] == ["ev-ci-1"]


@pytest.mark.asyncio
async def test_hold_gate_success(tmp_path):
    async def _fake_run(ctx):
        ctx.graph_context["persisted_all_evidence_ids"] = []
        ctx.graph_context["mutation_ids"] = []
        return ctx

    with (
        patch("scripts.ops12_ci_trust_gates.OntologySteward.insert_to_graph", return_value=None),
        patch(
            "scripts.ops12_ci_trust_gates.OntologySteward.run", new=AsyncMock(side_effect=_fake_run)
        ),
    ):
        ok, payload = await _run_gate("hold", str(tmp_path))

    assert ok is True
    assert payload["governance"]["status"] == "HOLD"
    assert payload["governance"]["hold_code"] == "NO_EVIDENCE_PERSISTED"


def test_typedb_ready_reports_mock_mode_unavailable():
    class FakeDB:
        _mock_mode = True

        def connect(self):
            return None

    with patch("src.db.typedb_client.TypeDBConnection", return_value=FakeDB()):
        ready, reason = _typedb_ready()

    assert ready is False
    assert reason == "typedb_unavailable_or_mock_mode"


def test_should_enforce_typedb_only_in_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    assert _should_enforce_typedb() is True

    monkeypatch.setenv("CI", "")
    assert _should_enforce_typedb() is False
