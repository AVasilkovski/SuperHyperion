from __future__ import annotations

import json
from pathlib import Path

from src.graph.contracts import GovernanceSummaryV1
from src.sdk.bundles import BundleView, load_bundles, output_prefix
from src.sdk.compliance import build_compliance_report
from src.sdk.sandbox import simulate_policies


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def _bundle(bundles, prefix: str, tenant: str | None, status: str = "STAGED"):
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
    manifest = {"capsule_id": prefix}
    if tenant is not None:
        manifest["tenant_id"] = tenant
    _write(bundles / f"{prefix}_run_capsule_manifest.json", manifest)


def test_load_bundles_and_tooling_filter_by_tenant(tmp_path):
    bundles = tmp_path / "bundles"
    policy_out = tmp_path / "policy"
    bundles.mkdir()

    _bundle(bundles, "run-a", "tenant-a")
    _bundle(bundles, "run-b", "tenant-b")

    loaded = load_bundles(str(bundles), tenant_id="tenant-a")
    assert [b.prefix for b in loaded] == ["run-a"]

    written = simulate_policies(
        str(bundles), "src.policies.builtin", str(policy_out), tenant_id="tenant-b"
    )
    assert len(written) == 1
    assert written[0].endswith("run-b_policy_simulation.json")

    report = build_compliance_report(str(bundles), tenant_id="tenant-a")
    assert report["total_runs"] == 1
    assert report["runs"][0]["prefix"] == "run-a"


def test_tenant_default_filter_includes_legacy_missing_tenant(tmp_path):
    bundles = tmp_path / "bundles"
    bundles.mkdir()

    _bundle(bundles, "run-acme", "acme")
    _bundle(bundles, "run-default", "default")
    _bundle(bundles, "run-legacy", None)

    default_loaded = load_bundles(str(bundles), tenant_id="default")
    assert [b.prefix for b in default_loaded] == ["run-default", "run-legacy"]
    assert [b.tenant_id for b in default_loaded] == ["default", None]
    assert [b.effective_tenant_id for b in default_loaded] == ["default", "default"]

    acme_loaded = load_bundles(str(bundles), tenant_id="acme")
    assert [b.prefix for b in acme_loaded] == ["run-acme"]


def test_nested_duplicate_prefixes_preserve_directory_context(tmp_path):
    bundles = tmp_path / "bundles"
    out = tmp_path / "policy"
    (bundles / "tenant-a").mkdir(parents=True)
    (bundles / "tenant-b").mkdir(parents=True)

    _bundle(bundles / "tenant-a", "run-1", "tenant-a")
    _bundle(bundles / "tenant-b", "run-1", "tenant-b")

    loaded = load_bundles(str(bundles))
    assert [b.bundle_key for b in loaded] == ["tenant-a/run-1", "tenant-b/run-1"]

    written = simulate_policies(str(bundles), "src.policies.builtin", str(out))
    basenames = sorted(Path(p).name for p in written)
    assert basenames == [
        "tenant-a%2Frun-1_policy_simulation.json",
        "tenant-b%2Frun-1_policy_simulation.json",
    ]


def test_output_prefix_encoding_is_non_lossy_for_nested_and_flattened_names(tmp_path):
    bundles = tmp_path / "bundles"
    out = tmp_path / "policy"
    bundles.mkdir(parents=True)
    (bundles / "tenant-a").mkdir(parents=True)

    _bundle(bundles, "tenant-a__run-1", "tenant-flat")
    _bundle(bundles / "tenant-a", "run-1", "tenant-nested")

    written = simulate_policies(str(bundles), "src.policies.builtin", str(out))
    basenames = sorted(Path(p).name for p in written)
    assert basenames == [
        "tenant-a%2Frun-1_policy_simulation.json",
        "tenant-a__run-1_policy_simulation.json",
    ]


def test_output_prefix_normalizes_windows_separator():
    bundle = BundleView(
        prefix="run-1",
        bundle_key=r"tenant-a\run-1",
        governance=GovernanceSummaryV1(
            contract_version="v1",
            status="HOLD",
            gate_code="NO_EVIDENCE_PERSISTED",
            duration_ms=0,
        ),
        replay=None,
        manifest=None,
        explainability=None,
        tenant_id=None,
        effective_tenant_id="default",
        capsule_id=None,
    )
    assert output_prefix(bundle) == "tenant-a%2Frun-1"
