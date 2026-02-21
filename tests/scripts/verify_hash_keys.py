
import hashlib
import json
from src.governance.fingerprinting import make_capsule_manifest_hash

def verify_hash_ignoring_unknown():
    capsule_id = "run-test-123"
    
    # Base manifest
    manifest_clean = {
        "session_id": "sess-1",
        "query_hash": "abc",
        "scope_lock_id": "slid-1",
        "intent_id": "iid-1",
        "proposal_id": "prop-1",
        "evidence_ids": ["ev-1"],
        "mutation_ids": ["mut-1"]
    }
    
    # Manifest with extra keys
    manifest_dirty = manifest_clean.copy()
    manifest_dirty["unknown_key"] = "noisy-data"
    manifest_dirty["metadata"] = {"foo": "bar"}
    
    hash_clean = make_capsule_manifest_hash(capsule_id, manifest_clean, manifest_version="v2")
    hash_dirty = make_capsule_manifest_hash(capsule_id, manifest_dirty, manifest_version="v2")
    
    print(f"Clean hash: {hash_clean}")
    print(f"Dirty hash: {hash_dirty}")
    
    assert hash_clean == hash_dirty, "Hashes should be identical even with extra keys"
    print("Verification SUCCESS: Extra keys are ignored.")

if __name__ == "__main__":
    try:
        verify_hash_ignoring_unknown()
    except Exception as e:
        print(f"Verification FAILED: {e}")
        exit(1)
