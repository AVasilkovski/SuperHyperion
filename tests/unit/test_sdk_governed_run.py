"""
TRUST-1.0 SDK unit tests.

Tests mock the workflow and replay verification to avoid LLM / TypeDB deps.
"""

from __future__ import annotations

import json
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — realistic AgentState stubs
# ---------------------------------------------------------------------------


def _make_staged_state() -> dict:
    """AgentState dict for a successful COMMIT run."""
    return {
        "governance": {
            "contract_version": "v1",
            "status": "STAGED",
            "lane": "grounded",
            "session_id": "sess-test-001",
            "persisted_evidence_ids": ["ev-aaa", "ev-bbb"],
            "intent_id": "int-001",
            "proposal_id": "prop-001",
            "mutation_ids": ["mut-001"],
            "scope_lock_id": "sl-001",
            "hold_code": None,
            "hold_reason": None,
            "gate_code": "FULL_COHERENCE",
            "failure_reason": None,
            "duration_ms": 42,
        },
        "run_capsule": {
            "capsule_id": "run-abc123",
            "capsule_hash": "deadbeef" * 8,
            "session_id": "sess-test-001",
            "query_hash": "qh-xyz",
            "scope_lock_id": "sl-001",
            "intent_id": "int-001",
            "proposal_id": "prop-001",
            "evidence_ids": ["ev-aaa", "ev-bbb"],
            "mutation_ids": ["mut-001"],
        },
        "response": "Protein X inhibits pathway Y via mechanism Z.",
        "session_id": "sess-test-001",
    }


def _make_hold_state() -> dict:
    """AgentState dict for a HOLD run (evidence mismatch)."""
    return {
        "governance": {
            "contract_version": "v1",
            "status": "HOLD",
            "lane": "grounded",
            "session_id": "sess-test-002",
            "persisted_evidence_ids": [],
            "intent_id": None,
            "proposal_id": None,
            "mutation_ids": [],
            "scope_lock_id": None,
            "hold_code": "COH_EVIDENCE_MISMATCH",
            "hold_reason": "No evidence persisted in ledger",
            "gate_code": "HOLD_COH",
            "failure_reason": None,
            "duration_ms": 5,
        },
        "run_capsule": None,
        "response": "HOLD: [COH_EVIDENCE_MISMATCH] No evidence persisted in ledger",
        "session_id": "sess-test-002",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sdk_governed_run_happy_path_returns_capsule_and_replay_passes():
    """
    COMMIT path: governance STAGED + capsule present → status COMMIT,
    capsule_id populated, replay verdict PASS.
    """
    from src.sdk.types import ReplayVerdictV1

    mock_state = _make_staged_state()
    mock_verdict = ReplayVerdictV1(status="PASS", reasons=[], details={})

    with (
        patch(
            "src.graph.workflow_v21.run_v21_query",
            new_callable=AsyncMock,
            return_value=mock_state,
        ),
        patch(
            "src.verification.replay_verify.verify_capsule",
            return_value=mock_verdict,
        ),
    ):
        from src.sdk.governed_run import GovernedRun

        result = await GovernedRun.run("Protein X inhibits pathway Y")

    assert result.status == "COMMIT"
    assert result.capsule_id == "run-abc123"
    assert result.replay_verdict is not None
    assert result.replay_verdict.status == "PASS"
    assert result.governance is not None
    assert result.governance.status == "STAGED"
    assert result.evidence_ids == ["ev-aaa", "ev-bbb"]
    assert result.mutation_ids == ["mut-001"]
    assert result.intent_id == "int-001"
    assert result.proposal_id == "prop-001"
    assert result.tenant_id == "default"


@pytest.mark.asyncio
async def test_sdk_hold_contains_hold_code_and_no_capsule():
    """
    HOLD path: governance HOLD → status HOLD, capsule_id None,
    hold_code present, response contains hold reason.
    """
    mock_state = _make_hold_state()

    with patch(
        "src.graph.workflow_v21.run_v21_query",
        new_callable=AsyncMock,
        return_value=mock_state,
    ):
        from src.sdk.governed_run import GovernedRun

        result = await GovernedRun.run("Something that triggers HOLD")

    assert result.status == "HOLD"
    assert result.capsule_id is None
    assert result.hold_code == "COH_EVIDENCE_MISMATCH"
    assert result.hold_reason is not None
    assert "evidence" in result.hold_reason.lower()
    assert result.replay_verdict is None


@pytest.mark.asyncio
async def test_sdk_threads_tenant_id_field():
    """
    tenant_id passed into run() must appear in GovernedResultV1 and audit bundle.
    """
    from src.sdk.types import ReplayVerdictV1

    mock_state = _make_staged_state()
    mock_verdict = ReplayVerdictV1(status="PASS", reasons=[], details={})

    with (
        patch(
            "src.graph.workflow_v21.run_v21_query",
            new_callable=AsyncMock,
            return_value=mock_state,
        ) as mock_run_v21_query,
        patch(
            "src.verification.replay_verify.verify_capsule",
            return_value=mock_verdict,
        ),
    ):
        from src.sdk.governed_run import GovernedRun

        result = await GovernedRun.run(
            "Tenant test query", tenant_id="acme-corp"
        )

    # Tenant must be threaded into workflow entrypoint
    assert mock_run_v21_query.await_count == 1
    assert mock_run_v21_query.await_args.kwargs["tenant_id"] == "acme-corp"

    # Tenant must appear in result
    assert result.tenant_id == "acme-corp"

    # Tenant must appear in audit bundle
    with tempfile.TemporaryDirectory() as tmpdir:
        written = result.export_audit_bundle(tmpdir)
        assert len(written) > 0

        # Check capsule manifest includes tenant_id
        manifest_files = [f for f in written if "manifest" in f]
        assert len(manifest_files) == 1
        with open(manifest_files[0], "r") as fh:
            manifest_data = json.load(fh)
        assert manifest_data["tenant_id"] == "acme-corp"


@pytest.mark.asyncio
async def test_sdk_no_governance_returns_hold():
    """
    When governance is missing from pipeline output → HOLD with NO_GOVERNANCE.
    """
    mock_state = {
        "governance": None,
        "run_capsule": None,
        "response": "",
        "session_id": "sess-no-gov",
    }

    with patch(
        "src.graph.workflow_v21.run_v21_query",
        new_callable=AsyncMock,
        return_value=mock_state,
    ):
        from src.sdk.governed_run import GovernedRun

        result = await GovernedRun.run("No governance test")

    assert result.status == "HOLD"
    assert result.hold_code == "NO_GOVERNANCE"
    assert result.capsule_id is None


@pytest.mark.asyncio
async def test_sdk_staged_but_missing_capsule_returns_hold():
    """
    Governance STAGED but capsule missing → HOLD with MISSING_CAPSULE.
    """
    mock_state = _make_staged_state()
    mock_state["run_capsule"] = None  # capsule failed to build

    with patch(
        "src.graph.workflow_v21.run_v21_query",
        new_callable=AsyncMock,
        return_value=mock_state,
    ):
        from src.sdk.governed_run import GovernedRun

        result = await GovernedRun.run("Missing capsule test")

    assert result.status == "HOLD"
    assert result.hold_code == "MISSING_CAPSULE"


@pytest.mark.asyncio
async def test_sdk_workflow_exception_returns_error():
    """
    If the workflow raises, GovernedRun should return ERROR, not crash.
    """

    with patch(
        "src.graph.workflow_v21.run_v21_query",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM provider down"),
    ):
        from src.sdk.governed_run import GovernedRun

        result = await GovernedRun.run("Crash test")

    assert result.status == "ERROR"
    assert "LLM provider down" in result.response
