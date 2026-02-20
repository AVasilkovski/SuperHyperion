"""TRUST-1.0.4 Policy conflict detection (bundle-only, deterministic)."""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from typing import Any, Callable, Dict, Optional

from src.graph.contracts import GovernanceSummaryV1
from src.sdk.bundles import BundleView, load_bundles
from src.sdk.sandbox import discover_policies

Decision = Dict[str, str]


def _policy_name(fn: Callable[[BundleView], Decision]) -> str:
    return str(getattr(fn, "policy_name", None) or fn.__name__)


def _derived_semantic_fingerprint(fn: Callable[[BundleView], Decision]) -> str:
    code = getattr(fn, "__code__", None)
    raw = f"{fn.__module__}:{fn.__name__}:{getattr(code, 'co_firstlineno', 0)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _sample_bundle() -> BundleView:
    return BundleView(
        prefix="sample",
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
        capsule_id=None,
    )


def _policy_metadata(fn: Callable[[BundleView], Decision]) -> dict[str, str]:
    fallback_id = fn.__name__
    policy_name = _policy_name(fn)
    code = "UNKNOWN"
    resolved_id = fallback_id
    try:
        sample = fn(_sample_bundle())
        resolved_id = str(sample.get("policy_id") or fallback_id)
        code = str(sample.get("code") or "UNKNOWN")
    except Exception:
        pass
    return {
        "policy_id": resolved_id,
        "fallback_id": fallback_id,
        "policy_name": policy_name,
        "code": code,
        "semantic": _derived_semantic_fingerprint(fn),
    }


def detect_static_conflicts(policies: list[Callable[[BundleView], Decision]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    seen_ids: dict[str, list[str]] = defaultdict(list)
    seen_names: dict[str, list[str]] = defaultdict(list)
    code_to_semantics: dict[str, set[str]] = defaultdict(set)
    code_to_ids: dict[str, set[str]] = defaultdict(set)

    meta = [_policy_metadata(fn) for fn in policies]
    for item in sorted(meta, key=lambda x: (x["policy_id"], x["fallback_id"])):
        seen_ids[item["policy_id"]].append(item["policy_name"])
        seen_names[item["policy_name"]].append(item["policy_id"])
        code_to_semantics[item["code"]].add(item["semantic"])
        code_to_ids[item["code"]].add(item["policy_id"])

    for pid in sorted(seen_ids):
        if len(seen_ids[pid]) > 1:
            conflicts.append(
                {
                    "type": "duplicate_policy_id",
                    "severity": "error",
                    "policy_id": pid,
                    "policy_names": sorted(seen_ids[pid]),
                }
            )

    for pname in sorted(seen_names):
        if len(seen_names[pname]) > 1:
            conflicts.append(
                {
                    "type": "duplicate_policy_name",
                    "severity": "warning",
                    "policy_name": pname,
                    "policy_ids": sorted(seen_names[pname]),
                }
            )

    for code in sorted(code_to_semantics):
        if len(code_to_semantics[code]) > 1:
            conflicts.append(
                {
                    "type": "duplicate_decision_code",
                    "severity": "error",
                    "code": code,
                    "policy_ids": sorted(code_to_ids[code]),
                }
            )

    conflicts.sort(key=lambda c: (c["type"], c.get("policy_id", ""), c.get("code", ""), c.get("policy_name", "")))
    return conflicts


def detect_dynamic_conflicts(simulation_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for item in sorted(simulation_results, key=lambda x: str(x.get("prefix", ""))):
        prefix = str(item.get("prefix", ""))
        decisions = item.get("decisions") or []
        decisions_set = {str(d.get("decision")) for d in decisions}

        if "ALLOW" in decisions_set and ("HOLD" in decisions_set or "DENY" in decisions_set):
            conflicts.append(
                {
                    "type": "contradictory_decisions",
                    "severity": "error",
                    "prefix": prefix,
                    "decisions": sorted(decisions_set),
                }
            )

        hold_codes = sorted({str(d.get("code")) for d in decisions if str(d.get("decision")) == "HOLD"})
        if len(hold_codes) > 1:
            conflicts.append(
                {
                    "type": "hold_code_divergence",
                    "severity": "warning",
                    "prefix": prefix,
                    "hold_codes": hold_codes,
                }
            )

    conflicts.sort(key=lambda c: (c["type"], c.get("prefix", "")))
    return conflicts


def run_policy_conflicts(
    bundles_dir: str,
    policies_module: str,
    out_dir: str,
    tenant_id: Optional[str] = None,
) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    policies = discover_policies(policies_module)
    bundles = load_bundles(bundles_dir, tenant_id=tenant_id)

    static_conflicts = detect_static_conflicts(policies)
    simulation_results: list[dict[str, Any]] = []

    for bundle in bundles:
        decisions = []
        for fn in sorted(policies, key=lambda f: _policy_metadata(f)["policy_id"]):
            res = fn(bundle)
            decisions.append(
                {
                    "policy_id": str(res["policy_id"]),
                    "decision": str(res["decision"]),
                    "code": str(res["code"]),
                    "reason": str(res["reason"]),
                }
            )
        decisions.sort(key=lambda d: d["policy_id"])
        simulation_results.append({"prefix": bundle.prefix, "tenant_id": bundle.tenant_id, "decisions": decisions})

    dynamic_conflicts = detect_dynamic_conflicts(simulation_results)

    summary = {
        "contract_version": "v1",
        "tenant_id": tenant_id,
        "static_conflicts": static_conflicts,
        "dynamic_conflicts": dynamic_conflicts,
        "run_count": len(simulation_results),
    }

    written: list[str] = []
    summary_path = os.path.join(out_dir, "policy_conflicts_summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
    written.append(os.path.abspath(summary_path))

    dynamic_by_prefix: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in dynamic_conflicts:
        dynamic_by_prefix[str(c.get("prefix", ""))].append(c)
    for prefix in sorted(dynamic_by_prefix):
        path = os.path.join(out_dir, f"{prefix}_policy_conflicts.json")
        payload = {
            "contract_version": "v1",
            "prefix": prefix,
            "conflicts": sorted(dynamic_by_prefix[prefix], key=lambda c: (c["type"], c.get("severity", ""))),
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        written.append(os.path.abspath(path))

    return written
