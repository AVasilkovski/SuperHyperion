from __future__ import annotations

import json

from src.sdk.policy_conflicts import run_policy_conflicts


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def _bundle(bundles, prefix: str, tenant: str):
    _write(
        bundles / f"{prefix}_governance_summary.json",
        {
            "contract_version": "v1",
            "status": "STAGED",
            "session_id": f"sess-{prefix}",
            "persisted_evidence_ids": ["ev-1"],
            "intent_id": None,
            "proposal_id": None,
            "mutation_ids": [],
            "scope_lock_id": None,
            "hold_code": None,
            "hold_reason": None,
            "gate_code": "GOVERNANCE_STAGED",
            "failure_reason": None,
            "duration_ms": 1,
            "source_refs": {},
        },
    )
    _write(bundles / f"{prefix}_run_capsule_manifest.json", {"capsule_id": prefix, "tenant_id": tenant})


def test_policy_conflict_detector_static_and_dynamic(tmp_path, monkeypatch):
    bundles = tmp_path / "bundles"
    out = tmp_path / "out"
    moddir = tmp_path / "mods"
    bundles.mkdir()
    moddir.mkdir()

    _bundle(bundles, "run-a", "tenant-a")

    module_file = moddir / "policy_pack.py"
    module_file.write_text(
        """
def policy_alpha(bundle):
    return {"policy_id":"dup","decision":"ALLOW","code":"SAME_CODE","reason":"ok"}

def policy_beta(bundle):
    return {"policy_id":"dup","decision":"HOLD","code":"SAME_CODE","reason":"block"}
"""
    )
    monkeypatch.syspath_prepend(str(moddir))

    written = run_policy_conflicts(str(bundles), "policy_pack", str(out))
    assert any(p.endswith("policy_conflicts_summary.json") for p in written)
    assert any(p.endswith("run-a_policy_conflicts.json") for p in written)

    summary = json.loads((out / "policy_conflicts_summary.json").read_text())
    static_types = [c["type"] for c in summary["static_conflicts"]]
    assert "duplicate_policy_id" in static_types

    dynamic_types = [c["type"] for c in summary["dynamic_conflicts"]]
    assert "contradictory_decisions" in dynamic_types


def test_duplicate_code_scoped_to_blocking_decisions(tmp_path, monkeypatch):
    bundles = tmp_path / "bundles"
    out = tmp_path / "out"
    moddir = tmp_path / "mods"
    bundles.mkdir()
    moddir.mkdir()

    _bundle(bundles, "run-a", "tenant-a")

    module_file = moddir / "policy_pack_non_blocking.py"
    module_file.write_text(
        """
def policy_allow_a(bundle):
    return {"policy_id":"allow-a","decision":"ALLOW","code":"ALLOW_CODE","reason":"ok"}

def policy_allow_b(bundle):
    return {"policy_id":"allow-b","decision":"ALLOW","code":"ALLOW_CODE","reason":"ok"}
"""
    )
    monkeypatch.syspath_prepend(str(moddir))

    run_policy_conflicts(str(bundles), "policy_pack_non_blocking", str(out))
    summary = json.loads((out / "policy_conflicts_summary.json").read_text())

    duplicate_code = [c for c in summary["static_conflicts"] if c["type"] == "duplicate_decision_code"]
    assert duplicate_code == []


def test_duplicate_code_payload_includes_policy_names(tmp_path, monkeypatch):
    bundles = tmp_path / "bundles"
    out = tmp_path / "out"
    moddir = tmp_path / "mods"
    bundles.mkdir()
    moddir.mkdir()

    _bundle(bundles, "run-a", "tenant-a")

    module_file = moddir / "policy_pack_blocking.py"
    module_file.write_text(
        """
def policy_hold_a(bundle):
    return {"policy_id":"hold-a","decision":"HOLD","code":"HOLD_CODE","reason":"hold"}

def policy_hold_b(bundle):
    return {"policy_id":"hold-b","decision":"HOLD","code":"HOLD_CODE","reason":"hold"}
"""
    )
    monkeypatch.syspath_prepend(str(moddir))

    run_policy_conflicts(str(bundles), "policy_pack_blocking", str(out))
    summary = json.loads((out / "policy_conflicts_summary.json").read_text())

    duplicate_code = [c for c in summary["static_conflicts"] if c["type"] == "duplicate_decision_code"]
    assert len(duplicate_code) == 1
    assert duplicate_code[0]["decision"] == "HOLD"
    assert duplicate_code[0]["policy_ids"] == ["hold-a", "hold-b"]
    assert duplicate_code[0]["policy_names"] == ["policy_hold_a", "policy_hold_b"]
