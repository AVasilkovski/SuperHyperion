
import logging
from unittest.mock import MagicMock, patch

import pytest

from src.agents.ontology_steward import (
    OntologySteward,
    make_evidence_id,
    q_insert_validation_evidence,
)
from src.montecarlo.template_metadata import sha256_json_strict
from src.montecarlo.types import ExperimentSpec

# =============================================================================
# 1. ExperimentSpec Constitutional Rules
# =============================================================================

def test_experimentspec_requires_execution_fields():
    """Verify scope_lock_id and template_qid are enforced."""
    with pytest.raises(ValueError, match="Missing or invalid template_qid"):
        ExperimentSpec(
            claim_id="claim-123",
            hypothesis="abc",
            # missing template_qid, missing template_id
        )

def test_experimentspec_legacy_normalization(caplog):
    """Verify legacy template_id is normalized to pinned QID with warning."""
    with caplog.at_level(logging.WARNING):
        spec = ExperimentSpec(
            claim_id="claim-123",
            hypothesis="abc",
            template_id="bootstrap_ci", # Legacy
            scope_lock_id="scope-lock-xyz",
        )

    # Check normalization
    assert spec.template_qid == "bootstrap_ci@1.0.0"
    assert "LEGACY_TEMPLATE_ID_USED" in caplog.text

def test_experimentspec_invalid_qid_format():
    """Verify regex enforcement for QID."""
    with pytest.raises(ValueError, match="Invalid template_qid format"):
        ExperimentSpec(
            claim_id="claim-123",
            hypothesis="abc",
            template_qid="bootstrap_ci@latest", # Invalid (must be X.Y.Z)
            scope_lock_id="scope-lock-xyz",
        )

def test_experimentspec_requires_scope_lock():
    """Verify scope_lock_id is mandatory."""
    with pytest.raises(ValueError, match="scope_lock_id is REQUIRED"):
        ExperimentSpec(
            claim_id="claim-123",
            hypothesis="abc",
            template_qid="foo@1.0.0",
            # Missing scope_lock_id
        )

# =============================================================================
# 2. Deterministic IDs & Hashing
# =============================================================================

def test_make_evidence_id_determinism():
    """Verify evidence ID is stable and joinable."""
    sid = "sess-1"
    cid = "claim-1"
    eid = "exec-1"
    qid = "tpl@1.0.0"

    ev1 = make_evidence_id(sid, cid, eid, qid)
    ev2 = make_evidence_id(sid, cid, eid, qid)

    assert ev1 == ev2
    assert ev1.startswith("ev-")
    # Verify length extension (ev- + 32 chars = 35 chars)
    assert len(ev1) == 35

    # Changing any component changes ID
    ev3 = make_evidence_id(sid, cid, "exec-2", qid)
    assert ev1 != ev3

def test_sha256_json_strict():
    """Verify strict hashing."""
    data = {"a": 1, "b": 2}
    hash1 = sha256_json_strict(data)

    # Order independence (sort_keys=True)
    data2 = {"b": 2, "a": 1}
    hash2 = sha256_json_strict(data2)

    assert hash1 == hash2

# =============================================================================
# 3. Blocking Seal Gate & Hash Parity
# =============================================================================

@pytest.mark.asyncio
async def test_steward_blocks_on_seal_failure():
    """Verify hard fail (exception) if seal fails."""
    steward = OntologySteward()
    steward.insert_to_graph = MagicMock()
    # Mock seal to simulate Hash Failure (Raise ValueError)
    steward._seal_operator_before_mint = MagicMock(side_effect=ValueError("Hash Mismatch"))
    steward.db = MagicMock()

    context = MagicMock()
    context.graph_context = {
        "evidence": [{
            "claim_id": "c1",
            "execution_id": "e1",
            "template_qid": "t@1.0.0",
            "scope_lock_id": "s1",
            "success": True,
            "json": {"foo": "bar"}
        }]
    }

    # Expect Exception to bubble up (since we process one item loop)
    # The run method catches Exception, logs it.
    # WAIT: I changed run loop to catch exception and RAISE e if success.
    # So this SHOULD raise ValueError.
    with pytest.raises(ValueError, match="Hash Mismatch"):
        await steward.run(context)

    # Verify insert NOT called
    # Verify Evidence Insert NOT called
    # Note: insert_to_graph call_count > 0 due to Session/Traces inserts.
    # We must restrict check to validation-evidence.
    calls = steward.insert_to_graph.call_args_list
    validation_calls = [c.args[0] for c in calls if "validation-evidence" in str(c.args[0])]
    assert len(validation_calls) == 0, f"Evidence inserted despite seal failure: {validation_calls}"

@pytest.mark.asyncio
async def test_steward_succeeds_if_seal_passes():
    """Verify success path."""
    steward = OntologySteward()
    steward.insert_to_graph = MagicMock()
    steward._seal_operator_before_mint = MagicMock() # Success
    steward.db = MagicMock()

    context = MagicMock()
    context.graph_context = {
        "evidence": [{
            "claim_id": "c1",
            "execution_id": "e1",
            "template_qid": "t@1.0.0",
            "scope_lock_id": "s1",
            "success": True,  # Critical: Must be True to trigger seal
            "json": {"foo": "bar"}
        }]
    }

    await steward.run(context)

    steward._seal_operator_before_mint.assert_called_once()

    # Verify evidence inserted
    calls = steward.insert_to_graph.call_args_list
    validation_calls = [c.args[0] for c in calls if "validation-evidence" in c.args[0]]
    assert len(validation_calls) == 1

@pytest.mark.asyncio
async def test_steward_rejects_failed_evidence():
    """Verify failed evidence raises policy violation (Phase 16.1: reject loud, not silent skip)."""
    steward = OntologySteward()
    steward.insert_to_graph = MagicMock()
    steward._seal_operator_before_mint = MagicMock()
    steward.db = MagicMock()

    context = MagicMock()
    context.graph_context = {
        "evidence": [{
            "claim_id": "c1",
            "execution_id": "e1",
            "template_qid": "t@1.0.0",
            "scope_lock_id": "s1",
            "success": False,  # Failed evidence
            "json": {"foo": "bar"}
        }]
    }

    # Phase 16.1: Failed evidence should raise ValueError (reject loud, not silent skip)
    with pytest.raises(ValueError) as exc_info:
        await steward.run(context)

    assert "success-only" in str(exc_info.value).lower() or "policy violation" in str(exc_info.value).lower()

@pytest.mark.asyncio
async def test_seal_method_checks_hash_parity():
    """Verify _seal_operator_before_mint logic specifically (mocking registry stuff)."""
    steward = OntologySteward()
    # Mock Store
    mock_store = MagicMock()
    steward.template_store = mock_store

    # Data
    qid = "test@1.0.0"
    _tid = "test"
    _ver = "1.0.0"

    # Mock Metadata
    mock_meta = MagicMock()
    mock_meta.spec_hash = "h1"
    mock_meta.code_hash = "h2"
    mock_store.get_metadata.return_value = mock_meta

    # Mock Registry Modules
    # Patch the source module because _seal imports it locally
    with patch("src.montecarlo.versioned_registry.VERSIONED_REGISTRY") as mock_reg, \
         patch("src.montecarlo.template_metadata.compute_code_hash_strict") as mock_code_hash:

        # Test Case 1: Spec Hash Mismatch
        mock_spec = MagicMock()
        mock_spec.spec_hash.return_value = "DIFFERENT_HASH"
        mock_reg.get_spec.return_value = mock_spec

        with pytest.raises(ValueError, match="Spec hash mismatch"):
            steward._seal_operator_before_mint(qid, "ev1", "c1", "s1")

        # Test Case 2: Code Hash Mismatch
        mock_spec.spec_hash.return_value = "h1" # Fix spec hash
        mock_code_hash.return_value = "DIFFERENT_CODE_HASH"
        mock_reg.get.return_value = MagicMock() # Template instance

        with pytest.raises(ValueError, match="Code hash mismatch"):
            steward._seal_operator_before_mint(qid, "ev1", "c1", "s1")

        # Test Case 3: Null Template Instance
        mock_reg.get.return_value = None
        with pytest.raises(ValueError, match="Seal failed: Template instance .* not found"):
             steward._seal_operator_before_mint(qid, "ev1", "c1", "s1")

        # Test Case 4: Corrupt Metadata
        mock_reg.get.return_value = MagicMock() # Restore instance
        mock_meta.spec_hash = None # Corrupt
        with pytest.raises(ValueError, match="Corrupt metadata"):
             steward._seal_operator_before_mint(qid, "ev1", "c1", "s1")

        # Test Case 5: Success
        mock_meta.spec_hash = "h1" # Restore from TC4
        mock_code_hash.return_value = "h2" # Fix code hash

        steward._seal_operator_before_mint(qid, "ev1", "c1", "s1")
        mock_store.freeze.assert_called_once()


# =============================================================================
# 4. Final Hardening: Query Builder Policy & Seal Regex
# =============================================================================

def test_q_insert_validation_evidence_success_canonicalization():
    """Verify 'false' string prevents minting (raise ValueError) or sets success=False."""
    # The policy now says: q_insert_validation_evidence RAISES if success is false.
    # So if we pass success="false", it should parse to False, and then raise ValueError.

    ev = {
        "success": "false",
        "claim_id": "c1",
        "template_qid": "t@1.0.0",
        "scope_lock_id": "sl1"
    }

    with pytest.raises(ValueError, match="Policy violation: validation-evidence is success-only"):
        q_insert_validation_evidence("sess1", ev)

def test_q_insert_validation_evidence_rejects_failed_evidence():
    """Verify built-in policy violation for success=False."""
    ev = {
        "success": False,
        "claim_id": "c1",
        "template_qid": "t@1.0.0",
        "scope_lock_id": "sl1"
    }
    with pytest.raises(ValueError, match="Policy violation: validation-evidence is success-only"):
        q_insert_validation_evidence("sess1", ev)

def test_q_insert_validation_evidence_derives_template_id():
    """Verify template_id is derived from qid if missing."""
    ev = {
        "success": True,
        "execution_id": "e1",
        "evidence_id": "ev1",
        "claim_id": "c1",
        "template_qid": "foo_bar@1.2.3",
        "scope_lock_id": "sl1"
    }

    query = q_insert_validation_evidence("sess1", ev)

    # Check that template-id "foo_bar" was inserted
    assert 'has template-id "foo_bar"' in query
    assert 'has template-qid "foo_bar@1.2.3"' in query

@pytest.mark.asyncio
async def test_seal_rejects_malformed_qid_regex():
    """Verify seal checks QID format strictness."""
    steward = OntologySteward()

    # Should fail regex check before even hitting store/registry
    with pytest.raises(ValueError, match="Invalid template_qid format for seal"):
        steward._seal_operator_before_mint(
            template_qid="bootstrap_ci@1", # Invalid format (missing .X.X or similar) - wait, regex depends on exact def.
            # Assuming standard strict regex from types.py
            evidence_id="ev1",
            claim_id="c1",
            scope_lock_id="sl1"
        )


# =============================================================================
# P1-A: authorized-by-intent-id linkage
# =============================================================================

def test_validation_evidence_includes_intent_id_when_provided():
    """Q_insert_validation_evidence emits authorized-by-intent-id when intent_id is given."""
    ev = {
        "claim_id": "claim-abc",
        "execution_id": "exec-1",
        "template_qid": "bootstrap_ci@1.0.0",
        "template_id": "bootstrap_ci",
        "scope_lock_id": "scope-xyz",
        "success": True,
        "confidence_score": 0.85,
    }
    query = q_insert_validation_evidence("sess-1", ev, intent_id="intent_abc123")
    assert 'has authorized-by-intent-id "intent_abc123"' in query


def test_validation_evidence_omits_intent_id_when_absent():
    """Q_insert_validation_evidence does NOT emit authorized-by-intent-id when intent_id is None."""
    ev = {
        "claim_id": "claim-abc",
        "execution_id": "exec-1",
        "template_qid": "bootstrap_ci@1.0.0",
        "template_id": "bootstrap_ci",
        "scope_lock_id": "scope-xyz",
        "success": True,
        "confidence_score": 0.85,
    }
    query = q_insert_validation_evidence("sess-1", ev)
    assert "authorized-by-intent-id" not in query
