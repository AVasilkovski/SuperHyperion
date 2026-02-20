from __future__ import annotations

import json

from src.sdk.sandbox import simulate_policies


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def test_policy_sandbox_deterministic_output_and_ordering(tmp_path):
    bundles = tmp_path / "bundles"
    out = tmp_path / "out"
    bundles.mkdir()

    prefix = "run-1"
    _write(
        bundles / f"{prefix}_governance_summary.json",
        {
            "contract_version": "v1",
            "status": "STAGED",
            "session_id": "sess-1",
            "persisted_evidence_ids": ["ev-1"],
            "intent_id": "int-1",
            "proposal_id": "prop-1",
            "mutation_ids": [],
            "scope_lock_id": "scope-1",
            "hold_code": None,
            "hold_reason": None,
            "gate_code": "GOVERNANCE_STAGED",
            "failure_reason": None,
            "duration_ms": 1,
            "source_refs": {},
        },
    )
    _write(
        bundles / f"{prefix}_run_capsule_manifest.json",
        {"capsule_id": prefix, "tenant_id": "acme"},
    )
    _write(
        bundles / f"{prefix}_replay_verify_verdict.json",
        {
            "contract_version": "v1",
            "status": "PASS",
            "reasons": [],
            "details": {},
            "source_refs": {},
        },
    )

    written = simulate_policies(str(bundles), "src.policies.builtin", str(out))
    assert len(written) == 1

    data = json.loads((out / f"{prefix}_policy_simulation.json").read_text())
    policy_ids = [d["policy_id"] for d in data["decisions"]]
    assert policy_ids == sorted(policy_ids)
    assert data["aggregate_decision"] == "ALLOW"
