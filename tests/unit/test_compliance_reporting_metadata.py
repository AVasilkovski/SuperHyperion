from __future__ import annotations

import csv
import json

from src.sdk.compliance import build_compliance_report, write_compliance_outputs


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def test_compliance_metadata_and_sample_flags(tmp_path):
    bundles = tmp_path / "bundles"
    bundles.mkdir()

    _write(
        bundles / "run-a_governance_summary.json",
        {
            "contract_version": "v1",
            "status": "STAGED",
            "session_id": "s1",
            "persisted_evidence_ids": ["ev-1"],
            "intent_id": None,
            "proposal_id": None,
            "mutation_ids": [],
            "scope_lock_id": None,
            "hold_code": None,
            "hold_reason": None,
            "gate_code": "GOVERNANCE_STAGED",
            "failure_reason": None,
            "duration_ms": 10,
            "source_refs": {},
        },
    )
    _write(bundles / "run-a_run_capsule_manifest.json", {"capsule_id": "run-a", "tenant_id": "t1"})

    report = build_compliance_report(str(bundles), p95_min_sample_size=30)
    assert report["latency"]["governance_gate"]["percentile_method"] == "linear_interpolation"
    assert report["latency"]["governance_gate"]["sample_size"] == 1
    assert report["latency"]["governance_gate"]["insufficient_sample"] is True
    assert report["latency"]["governance_gate"]["p95_ms"] is None

    out = tmp_path / "out"
    write_compliance_outputs(str(bundles), str(out), include_csv=True)

    with open(out / "runs.csv", newline="", encoding="utf-8") as fh:
        headers = csv.DictReader(fh).fieldnames
    assert headers == [
        "prefix",
        "bundle_key",
        "tenant_id",
        "status",
        "governance_status",
        "hold_code",
        "duration_ms",
        "governance_gate_duration_ms",
        "replay_verification_duration_ms",
        "steward_write_duration_ms",
        "has_replay",
        "replay_status",
    ]
    assert (out / "compliance_metadata.json").exists()


def test_compliance_runs_include_unique_bundle_key_for_duplicate_prefixes(tmp_path):
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    (bundles / "tenant-a").mkdir(parents=True)

    _write(
        bundles / "tenant-a__run-1_governance_summary.json",
        {
            "contract_version": "v1",
            "status": "STAGED",
            "session_id": "s-flat",
            "persisted_evidence_ids": ["ev-1"],
            "intent_id": None,
            "proposal_id": None,
            "mutation_ids": [],
            "scope_lock_id": None,
            "hold_code": None,
            "hold_reason": None,
            "gate_code": "GOVERNANCE_STAGED",
            "failure_reason": None,
            "duration_ms": 10,
            "source_refs": {},
        },
    )
    _write(bundles / "tenant-a__run-1_run_capsule_manifest.json", {"capsule_id": "run-flat", "tenant_id": "t-flat"})

    _write(
        bundles / "tenant-a" / "run-1_governance_summary.json",
        {
            "contract_version": "v1",
            "status": "STAGED",
            "session_id": "s-nested",
            "persisted_evidence_ids": ["ev-2"],
            "intent_id": None,
            "proposal_id": None,
            "mutation_ids": [],
            "scope_lock_id": None,
            "hold_code": None,
            "hold_reason": None,
            "gate_code": "GOVERNANCE_STAGED",
            "failure_reason": None,
            "duration_ms": 12,
            "source_refs": {},
        },
    )
    _write(bundles / "tenant-a" / "run-1_run_capsule_manifest.json", {"capsule_id": "run-nested", "tenant_id": "t-nested"})

    report = build_compliance_report(str(bundles))
    keys = [row["bundle_key"] for row in report["runs"]]
    assert keys == ["tenant-a/run-1", "tenant-a__run-1"]
