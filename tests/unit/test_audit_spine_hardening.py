"""
Tests for G1-G3 audit spine hardening.

G1: Replay hash backward compatibility (legacy capsules without mutation_ids key).
G2: create_claim intent fails closed (NotImplementedError).
G3: SHOWCASE governance bypass denied in non-local environments.
"""

import os
from unittest.mock import patch

import pytest

# ============================================================================
# G1: Replay hash backward compatibility
# ============================================================================


def test_legacy_capsule_hash_matches():
    """
    Pre-16.8 capsules were hashed without a mutation_ids key.
    Replay must produce the same hash when _has_mutation_snapshot=False.
    """
    from src.governance.fingerprinting import make_capsule_manifest_hash

    # Build the exact manifest shape that was used at creation time (no mutation_ids)
    manifest_at_creation = {
        "session_id": "sess-legacy",
        "query_hash": "qh-abc",
        "scope_lock_id": "sl-1",
        "intent_id": "int-1",
        "proposal_id": "prop-1",
        "evidence_ids": ["ev-1", "ev-2"],
    }
    capsule_id = "run-legacy-001"
    original_hash = make_capsule_manifest_hash(capsule_id, manifest_at_creation, manifest_version="v1")

    # Now simulate replay: _has_mutation_snapshot=False → omit mutation_ids
    replay_manifest = {
        "session_id": "sess-legacy",
        "query_hash": "qh-abc",
        "scope_lock_id": "sl-1",
        "intent_id": "int-1",
        "proposal_id": "prop-1",
        "evidence_ids": sorted(["ev-1", "ev-2"]),
        # NO mutation_ids key (because _has_mutation_snapshot=False)
    }
    recomputed_hash = make_capsule_manifest_hash(capsule_id, replay_manifest)

    assert recomputed_hash == original_hash, (
        f"Legacy hash mismatch: {recomputed_hash} != {original_hash}. "
        "Replay must not add mutation_ids to legacy manifests."
    )


def test_current_capsule_hash_includes_mutation_ids():
    """
    Post-16.8 capsules include mutation_ids in the manifest.
    Replay must include them when _has_mutation_snapshot=True.
    """
    from src.governance.fingerprinting import make_capsule_manifest_hash

    manifest = {
        "session_id": "sess-new",
        "query_hash": "qh-xyz",
        "scope_lock_id": "sl-2",
        "intent_id": "int-2",
        "proposal_id": "prop-2",
        "evidence_ids": ["ev-3"],
        "mutation_ids": ["mut-1"],
    }
    capsule_id = "run-new-001"
    original_hash = make_capsule_manifest_hash(capsule_id, manifest, manifest_version="v2")

    replay_manifest = {
        "session_id": "sess-new",
        "query_hash": "qh-xyz",
        "scope_lock_id": "sl-2",
        "intent_id": "int-2",
        "proposal_id": "prop-2",
        "evidence_ids": sorted(["ev-3"]),
        "mutation_ids": sorted(["mut-1"]),
    }
    recomputed_hash = make_capsule_manifest_hash(capsule_id, replay_manifest)

    assert recomputed_hash == original_hash


def test_adding_mutation_ids_key_changes_hash():
    """
    Proves the G1 bug: adding mutation_ids=[] to a legacy manifest changes the hash.
    This is why replay must NOT add the key for legacy capsules.
    """
    from src.governance.fingerprinting import make_capsule_manifest_hash

    capsule_id = "run-test"
    manifest_without = {
        "session_id": "s",
        "evidence_ids": ["ev-1"],
    }
    manifest_with_empty = {
        "session_id": "s",
        "evidence_ids": ["ev-1"],
        "mutation_ids": [],
    }

    h1 = make_capsule_manifest_hash(capsule_id, manifest_without, manifest_version="v1")
    h2 = make_capsule_manifest_hash(capsule_id, manifest_with_empty, manifest_version="v2")

    assert h1 != h2, (
        "Adding an empty mutation_ids key should change the hash "
        "(this proves the G1 bug exists and our fix is needed)"
    )


# ============================================================================
# G2: create_claim fails closed
# ============================================================================


def test_execute_intent_create_claim_fails_closed():
    """
    create_claim intents must NOT silently succeed.
    They should raise NotImplementedError which is caught by the caller.
    """
    from src.agents.ontology_steward import OntologySteward

    steward = OntologySteward()
    intent = {
        "intent_id": "int-test-create",
        "intent_type": "create_claim",
        "payload": {"claim_id": "c-1", "content": "test claim"},
    }

    # _execute_intent wraps exceptions → (False, err_msg)
    success, err = steward._execute_intent(intent)
    assert not success, "create_claim should fail (not silently succeed)"
    assert "not yet implemented" in err.lower(), f"Expected NotImplementedError message, got: {err}"


# ============================================================================
# G3: SHOWCASE bypass denied in non-local environments
# ============================================================================


@pytest.mark.asyncio
async def test_bypass_denied_in_nonlocal_env():
    """
    Setting SUPERHYPERION_UNSAFE_BYPASS_GOVERNANCE=true with a cloud host
    must NOT override governance holds.
    """
    from src.graph.nodes.governance_gate import governance_gate_node
    from src.graph.state import create_initial_state

    state = create_initial_state("test bypass")
    # Ensure governance gate will HOLD (no evidence persisted)
    state["graph_context"] = {"session_id": "sess-bypass"}

    env = {
        "SUPERHYPERION_UNSAFE_BYPASS_GOVERNANCE": "true",
        "TYPEDB_HOST": "cloud.typedb.com",  # NOT local
        "ENVIRONMENT": "staging",
    }
    with patch.dict(os.environ, env, clear=False):
        result = await governance_gate_node(state)

    gov = result.get("governance", {})
    assert gov["status"] == "HOLD", (
        f"Bypass should be DENIED in non-local env, but got status={gov['status']}"
    )


@pytest.mark.asyncio
async def test_bypass_allowed_in_local_dev():
    """
    Setting SUPERHYPERION_UNSAFE_BYPASS_GOVERNANCE=true with localhost/dev
    should allow override (for demos).
    """
    from src.graph.nodes.governance_gate import governance_gate_node
    from src.graph.state import create_initial_state

    state = create_initial_state("test local bypass")
    state["graph_context"] = {"session_id": "sess-local"}

    env = {
        "SUPERHYPERION_UNSAFE_BYPASS_GOVERNANCE": "true",
        "TYPEDB_HOST": "localhost",
        "ENVIRONMENT": "dev",
    }
    # Ensure CI is not set
    env_clear = {
        "CI": "",
        "GITHUB_ACTIONS": "",
    }
    with patch.dict(os.environ, {**env, **env_clear}, clear=False):
        result = await governance_gate_node(state)

    gov = result.get("governance", {})
    assert gov["status"] == "STAGED", (
        f"Local dev bypass should be allowed, but got status={gov['status']}"
    )


@pytest.mark.asyncio
async def test_old_showcase_env_has_no_effect():
    """
    The old SUPERHYPERION_SHOWCASE env var must have no effect.
    Only SUPERHYPERION_UNSAFE_BYPASS_GOVERNANCE is recognized.
    """
    from src.graph.nodes.governance_gate import governance_gate_node
    from src.graph.state import create_initial_state

    state = create_initial_state("test old showcase")
    state["graph_context"] = {"session_id": "sess-old"}

    env = {
        "SUPERHYPERION_SHOWCASE": "true",  # Old name — should be ignored
        "TYPEDB_HOST": "localhost",
        "ENVIRONMENT": "dev",
    }
    # Ensure the new bypass var is NOT set, nor CI
    env_clear = {
        "SUPERHYPERION_UNSAFE_BYPASS_GOVERNANCE": "",
        "CI": "",
        "GITHUB_ACTIONS": "",
    }
    with patch.dict(os.environ, {**env, **env_clear}, clear=False):
        result = await governance_gate_node(state)

    gov = result.get("governance", {})
    assert gov["status"] == "HOLD", (
        f"Old SHOWCASE env var should have no effect, but got status={gov['status']}"
    )


@pytest.mark.asyncio
async def test_bypass_denied_in_ci():
    """
    Setting SUPERHYPERION_UNSAFE_BYPASS_GOVERNANCE=true MUST be denied if CI is detected.
    """
    from src.graph.nodes.governance_gate import governance_gate_node
    from src.graph.state import create_initial_state

    state = create_initial_state("test ci bypass")
    state["graph_context"] = {"session_id": "sess-ci"}

    env = {
        "SUPERHYPERION_UNSAFE_BYPASS_GOVERNANCE": "true",
        "TYPEDB_HOST": "localhost",
        "ENVIRONMENT": "dev",
        "CI": "true",  # CI overrides local dev safety
    }
    with patch.dict(os.environ, env, clear=False):
        result = await governance_gate_node(state)

    gov = result.get("governance", {})
    assert gov["status"] == "HOLD", "Bypass should be DENIED in CI environments"
