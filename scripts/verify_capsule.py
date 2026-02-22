"""
Verify a Run Capsule from the Engine Start showcase.
Tests the Phase 16.5 Ledger Primacy logic.
"""

import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from src.agents.integrator_agent import integrator_agent
from src.db.typedb_client import typedb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CapsuleVerifier")


def reverify(capsule_path: str):
    logger.info(f"Loading capsule from {capsule_path}")
    with open(capsule_path, "r") as f:
        capsule = json.load(f)

    session_id = capsule.get("session_id")
    evidence_ids = capsule.get("evidence_ids", [])
    scope_lock = capsule.get("scope_lock_id")

    logger.info(f"Verifying session: {session_id}")
    logger.info(f"Evidence count:   {len(evidence_ids)}")

    # Ensure TypeDB state is initialized (triggers mock-mode if driver missing)
    typedb.connect()

    # Run primacy check
    passed, code, details = integrator_agent._verify_evidence_primacy(
        session_id=session_id, evidence_ids=evidence_ids, expected_scope_lock_id=scope_lock
    )

    if passed:
        logger.info("✅ PRIMACY VERIFIED: Capsule integrity confirmed.")
        print("\n================================================================================")
        print("CAPSULE VERIFICATION SUCCESSFUL")
        print(f"ID:     {capsule.get('capsule_id')}")
        print("STATUS: VERIFIED")
        print("================================================================================\n")
    else:
        logger.error(f"❌ PRIMACY FAILED: [{code}] {details.get('hold_reason')}")
        sys.exit(1)


if __name__ == "__main__":
    path = "last_capsule.json"
    if len(sys.argv) > 1:
        path = sys.argv[1]

    reverify(path)
