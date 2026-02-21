"""TRUST-1.0.3 Compliance reporting from exported bundles only."""

from __future__ import annotations

import csv
import json
import os
from statistics import mean
from typing import Any, Dict, Optional

from src.sdk.bundles import load_bundles


def _percentile(sorted_values: list[int], p: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    idx = (len(sorted_values) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return float(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac)


def _parse_stage_duration(details: dict[str, Any], key: str) -> Optional[int]:
    value = details.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def build_compliance_report(
    bundles_dir: str,
    tenant_id: Optional[str] = None,
    p95_min_sample_size: int = 30,
) -> Dict[str, Any]:
    bundles = load_bundles(bundles_dir, tenant_id=tenant_id)
    runs = []
    hold_codes: Dict[str, int] = {}
    replay_total = 0
    replay_pass = 0
    governance_durations: list[int] = []
    replay_durations: list[int] = []
    steward_write_durations: list[int] = []
    counts = {"COMMIT": 0, "HOLD": 0, "ERROR": 0}

    for bundle in bundles:
        status = "COMMIT" if (bundle.governance.status == "STAGED" and bundle.manifest) else "HOLD"
        counts[status] += 1

        hold_code = bundle.governance.hold_code
        if hold_code is not None:
            hold_codes[hold_code] = hold_codes.get(hold_code, 0) + 1

        replay_status = None
        replay_duration_ms = None
        if bundle.replay is not None:
            replay_total += 1
            replay_status = bundle.replay.status
            if bundle.replay.status == "PASS":
                replay_pass += 1
            replay_duration_ms = _parse_stage_duration(bundle.replay.details if isinstance(bundle.replay.details, dict) else {}, "duration_ms")
            if replay_duration_ms is not None:
                replay_durations.append(replay_duration_ms)

        governance_duration_ms = int(bundle.governance.duration_ms)
        governance_durations.append(governance_duration_ms)

        steward_duration_ms = None
        if bundle.manifest and isinstance(bundle.manifest, dict):
            steward_duration_ms = _parse_stage_duration(bundle.manifest, "steward_write_duration_ms")
            if steward_duration_ms is not None:
                steward_write_durations.append(steward_duration_ms)

        runs.append(
            {
                "prefix": bundle.prefix,
                "bundle_key": bundle.bundle_key,
                "tenant_id": bundle.tenant_id,
                "status": status,
                "governance_status": bundle.governance.status,
                "hold_code": hold_code,
                "duration_ms": governance_duration_ms,
                "governance_gate_duration_ms": governance_duration_ms,
                "replay_verification_duration_ms": replay_duration_ms,
                "steward_write_duration_ms": steward_duration_ms,
                "has_replay": bundle.replay is not None,
                "replay_status": replay_status,
            }
        )

    total_runs = len(runs)
    rates = {
        "commit_rate": (counts["COMMIT"] / total_runs) if total_runs else 0.0,
        "hold_rate": (counts["HOLD"] / total_runs) if total_runs else 0.0,
        "error_rate": (counts["ERROR"] / total_runs) if total_runs else 0.0,
    }

    def _latency_stats(values: list[int], method: str, threshold: int) -> dict[str, Any]:
        vals = sorted(values)
        n = len(vals)
        return {
            "percentile_method": method,
            "sample_size": n,
            "p95_min_sample_size": threshold,
            "insufficient_sample": n < threshold,
            "avg_ms": float(mean(vals)) if vals else None,
            "p50_ms": _percentile(vals, 0.5),
            "p95_ms": _percentile(vals, 0.95) if n >= threshold else None,
        }

    report = {
        "contract_version": "v1",
        "tenant_id": tenant_id,
        "total_runs": total_runs,
        "counts": counts,
        "rates": rates,
        "hold_codes": [{"hold_code": k, "count": hold_codes[k]} for k in sorted(hold_codes)],
        "replay": {
            "with_replay": replay_total,
            "pass_count": replay_pass,
            "pass_rate": (replay_pass / replay_total) if replay_total else None,
        },
        "latency": {
            "percentile_method": "linear_interpolation",
            "governance_gate": _latency_stats(governance_durations, "linear_interpolation", p95_min_sample_size),
            "replay_verification": _latency_stats(replay_durations, "linear_interpolation", p95_min_sample_size),
            "steward_write": _latency_stats(steward_write_durations, "linear_interpolation", p95_min_sample_size),
        },
        "runs": sorted(runs, key=lambda r: (str(r["bundle_key"]), str(r["prefix"]))),
    }
    return report


def write_compliance_outputs(
    bundles_dir: str,
    out_path: str,
    include_csv: bool = False,
    tenant_id: Optional[str] = None,
    p95_min_sample_size: int = 30,
) -> list[str]:
    report = build_compliance_report(bundles_dir, tenant_id=tenant_id, p95_min_sample_size=p95_min_sample_size)
    if out_path.endswith(".json"):
        json_path = out_path
        os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
    else:
        os.makedirs(out_path, exist_ok=True)
        json_path = os.path.join(out_path, "compliance_report.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    written = [os.path.abspath(json_path)]

    if include_csv:
        runs_csv = os.path.join(os.path.dirname(json_path), "runs.csv")
        with open(runs_csv, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
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
                ],
            )
            writer.writeheader()
            for row in report["runs"]:
                writer.writerow(row)
        written.append(os.path.abspath(runs_csv))

        hold_csv = os.path.join(os.path.dirname(json_path), "hold_codes.csv")
        with open(hold_csv, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["hold_code", "count"])
            writer.writeheader()
            for row in report["hold_codes"]:
                writer.writerow(row)
        written.append(os.path.abspath(hold_csv))

        metadata_path = os.path.join(os.path.dirname(json_path), "compliance_metadata.json")
        metadata = {
            "contract_version": "v1",
            "tenant_id": report["tenant_id"],
            "percentile_method": report["latency"]["percentile_method"],
            "governance_gate": report["latency"]["governance_gate"],
            "replay_verification": report["latency"]["replay_verification"],
            "steward_write": report["latency"]["steward_write"],
        }
        with open(metadata_path, "w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2, sort_keys=True)
        written.append(os.path.abspath(metadata_path))

    return written
