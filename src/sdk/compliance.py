"""TRUST-1.0.3 Compliance reporting from exported bundles only."""

from __future__ import annotations

import csv
import json
import os
from statistics import mean
from typing import Any, Dict

from src.sdk.bundles import discover_bundle_paths, load_bundle_view


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


def build_compliance_report(bundles_dir: str) -> Dict[str, Any]:
    bundle_paths = discover_bundle_paths(bundles_dir)
    runs = []
    hold_codes: Dict[str, int] = {}
    replay_total = 0
    replay_pass = 0
    durations: list[int] = []
    counts = {"COMMIT": 0, "HOLD": 0, "ERROR": 0}

    for prefix in sorted(bundle_paths):
        bundle = load_bundle_view(bundle_paths[prefix], prefix)
        status = "COMMIT" if (bundle.governance.status == "STAGED" and bundle.manifest) else "HOLD"
        counts[status] += 1

        hold_code = bundle.governance.hold_code
        if hold_code is not None:
            hold_codes[hold_code] = hold_codes.get(hold_code, 0) + 1

        if bundle.replay is not None:
            replay_total += 1
            if bundle.replay.status == "PASS":
                replay_pass += 1

        durations.append(int(bundle.governance.duration_ms))

        runs.append(
            {
                "prefix": prefix,
                "status": status,
                "governance_status": bundle.governance.status,
                "hold_code": hold_code,
                "duration_ms": int(bundle.governance.duration_ms),
                "has_replay": bundle.replay is not None,
                "replay_status": bundle.replay.status if bundle.replay else None,
            }
        )

    total_runs = len(runs)
    rates = {
        "commit_rate": (counts["COMMIT"] / total_runs) if total_runs else 0.0,
        "hold_rate": (counts["HOLD"] / total_runs) if total_runs else 0.0,
        "error_rate": (counts["ERROR"] / total_runs) if total_runs else 0.0,
    }
    durations_sorted = sorted(durations)
    latency = {
        "avg_ms": float(mean(durations_sorted)) if durations_sorted else None,
        "p50_ms": _percentile(durations_sorted, 0.5),
        "p95_ms": _percentile(durations_sorted, 0.95),
    }
    report = {
        "contract_version": "v1",
        "total_runs": total_runs,
        "counts": counts,
        "rates": rates,
        "hold_codes": [{"hold_code": k, "count": hold_codes[k]} for k in sorted(hold_codes)],
        "replay": {
            "with_replay": replay_total,
            "pass_count": replay_pass,
            "pass_rate": (replay_pass / replay_total) if replay_total else None,
        },
        "latency": latency,
        "runs": runs,
    }
    return report


def write_compliance_outputs(bundles_dir: str, out_path: str, include_csv: bool = False) -> list[str]:
    report = build_compliance_report(bundles_dir)
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
                fieldnames=["prefix", "status", "governance_status", "hold_code", "duration_ms", "has_replay", "replay_status"],
            )
            writer.writeheader()
            for row in sorted(report["runs"], key=lambda r: r["prefix"]):
                writer.writerow(row)
        written.append(os.path.abspath(runs_csv))

        hold_csv = os.path.join(os.path.dirname(json_path), "hold_codes.csv")
        with open(hold_csv, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["hold_code", "count"])
            writer.writeheader()
            for row in report["hold_codes"]:
                writer.writerow(row)
        written.append(os.path.abspath(hold_csv))

    return written
