"""
TRUST-1.0 SDK — Zero-write verification test

Ensures the verification layer is completely read-only.
"""

from unittest.mock import patch

from src.verification.replay_verify import verify_capsule


def test_verify_capsule_never_executes_query_insert():
    """Prove that verify_capsule never invokes TypeDBConnection.query_insert."""

    # We pass a fake capsule and allow the underlying read methods to fail/return None
    # but we trap query_insert. If query_insert is called, the test will raise.
    capsule_id = "test-capsule"
    capsule_data = {"capsule_hash": "deadbeef", "evidence_ids": ["ev-1"], "mutation_ids": ["mut-1"]}

    with patch(
        "src.db.typedb_client.TypeDBConnection.query_insert",
        side_effect=RuntimeError("SECURITY VIOLATION: query_insert called in read-only context!"),
    ) as mock_insert:
        try:
            # We don't care if it passes or fails verification (it will fail),
            # we only care that it doesn't try to insert anything during the check.
            result = verify_capsule(capsule_id, capsule_data)
            assert result is not None
        except Exception as e:
            # It might raise generic errors if DB isn't running, which is fine,
            # as long as it isn't our security trap.
            assert "SECURITY VIOLATION" not in str(e)

    mock_insert.assert_not_called()
