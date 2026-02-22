from __future__ import annotations

from unittest.mock import patch

from src.verification.replay_verify import verify_capsule


def _capsule_data() -> dict:
    return {
        "session_id": "sess-1",
        "query_hash": "hash-1",
        "scope_lock_id": "scope-1",
        "intent_id": "int-1",
        "proposal_id": "prop-1",
        "evidence_ids": [],
        "mutation_ids": [],
        "capsule_hash": "hash",  # integrity is patched in tests
        "_has_mutation_snapshot": True,
        "tenant_id": "tenant-a",
    }


def test_verify_capsule_tenant_match_proceeds():
    responses = [[{"c": "cap-1"}]]

    class FakeDB:
        _mock_mode = False

        def query_fetch(self, _q: str):
            return responses.pop(0)

    with patch("src.db.typedb_client.TypeDBConnection", return_value=FakeDB()):
        with patch(
            "src.verification.replay_verify._verify_hash_integrity", return_value=(True, {})
        ):
            with patch(
                "src.verification.replay_verify._verify_primacy", return_value=(True, "PASS", {})
            ):
                result = verify_capsule("cap-1", _capsule_data(), tenant_id="tenant-a")

    assert result.status == "PASS"


def test_verify_capsule_tenant_mismatch_fails_closed():
    responses = [[], [{"any_t": "tenant-other"}]]

    class FakeDB:
        _mock_mode = False

        def query_fetch(self, _q: str):
            return responses.pop(0)

    with patch("src.db.typedb_client.TypeDBConnection", return_value=FakeDB()):
        with patch("src.verification.replay_verify._verify_primacy") as primacy:
            result = verify_capsule("cap-2", _capsule_data(), tenant_id="tenant-a")

    assert result.status == "FAIL"
    assert result.details["tenant_scope"]["code"] == "TENANT_FORBIDDEN"
    primacy.assert_not_called()


def test_verify_capsule_missing_tenant_link_fails_closed():
    responses = [[], []]

    class FakeDB:
        _mock_mode = False

        def query_fetch(self, _q: str):
            return responses.pop(0)

    with patch("src.db.typedb_client.TypeDBConnection", return_value=FakeDB()):
        with patch("src.verification.replay_verify._verify_primacy") as primacy:
            result = verify_capsule("cap-legacy", _capsule_data(), tenant_id="tenant-a")

    assert result.status == "FAIL"
    assert result.details["tenant_scope"]["code"] == "TENANT_SCOPE_MISSING"
    primacy.assert_not_called()
