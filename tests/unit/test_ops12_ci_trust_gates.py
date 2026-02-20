from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from scripts.ops12_ci_trust_gates import _run_gate
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
        patch("scripts.ops12_ci_trust_gates.OntologySteward.run", new=AsyncMock(side_effect=_fake_run)),
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
    assert payload["governance"]["status"] == "STAGED"


@pytest.mark.asyncio
async def test_hold_gate_success(tmp_path):
    async def _fake_run(ctx):
        ctx.graph_context["persisted_all_evidence_ids"] = []
        ctx.graph_context["mutation_ids"] = []
        return ctx

    with (
        patch("scripts.ops12_ci_trust_gates.OntologySteward.insert_to_graph", return_value=None),
        patch("scripts.ops12_ci_trust_gates.OntologySteward.run", new=AsyncMock(side_effect=_fake_run)),
    ):
        ok, payload = await _run_gate("hold", str(tmp_path))

    assert ok is True
    assert payload["governance"]["status"] == "HOLD"
    assert payload["governance"]["hold_code"] == "NO_EVIDENCE_PERSISTED"
