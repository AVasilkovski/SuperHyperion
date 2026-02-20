from __future__ import annotations

import json

from src.sdk.bundles import load_bundles
from src.sdk.compliance import build_compliance_report
from src.sdk.sandbox import simulate_policies


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def _bundle(bundles, prefix: str, tenant: str, status: str = "STAGED"):
    _write(
        bundles / f"{prefix}_governance_summary.json",
        {
            "contract_version": "v1",
            "status": status,
            "session_id": f"sess-{prefix}",
            "persisted_evidence_ids": ["ev-1"] if status == "STAGED" else [],
            "intent_id": None,
            "proposal_id": None,
            "mutation_ids": [],
            "scope_lock_id": None,
            "hold_code": None if status == "STAGED" else "NO_EVIDENCE_PERSISTED",
            "hold_reason": None,
            "gate_code": "GOVERNANCE_STAGED" if status == "STAGED" else "NO_EVIDENCE_PERSISTED",
            "failure_reason": None,
            "duration_ms": 1,
            "source_refs": {},
        },
    )
    _write(bundles / f"{prefix}_run_capsule_manifest.json", {"capsule_id": prefix, "tenant_id": tenant})


def test_load_bundles_and_tooling_filter_by_tenant(tmp_path):
    bundles = tmp_path / "bundles"
    policy_out = tmp_path / "policy"
    bundles.mkdir()

    _bundle(bundles, "run-a", "tenant-a")
    _bundle(bundles, "run-b", "tenant-b")

    loaded = load_bundles(str(bundles), tenant_id="tenant-a")
    assert [b.prefix for b in loaded] == ["run-a"]

    written = simulate_policies(str(bundles), "src.policies.builtin", str(policy_out), tenant_id="tenant-b")
    assert len(written) == 1
    assert written[0].endswith("run-b_policy_simulation.json")

    report = build_compliance_report(str(bundles), tenant_id="tenant-a")
    assert report["total_runs"] == 1
    assert report["runs"][0]["prefix"] == "run-a"
