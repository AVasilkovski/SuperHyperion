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
