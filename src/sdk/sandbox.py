"""TRUST-1.0.2 Local policy sandbox simulation (bundle-only, read-only)."""

from __future__ import annotations

import importlib
import inspect
import json
import os
from typing import Callable, Dict, List, Optional

from src.sdk.bundles import BundleView, load_bundles, output_prefix

Decision = Dict[str, str]


def discover_policies(module_name: str) -> list[Callable[[BundleView], Decision]]:
    module = importlib.import_module(module_name)
    policies: list[Callable[[BundleView], Decision]] = []
    for name in dir(module):
        obj = getattr(module, name)
        if inspect.isfunction(obj) and obj.__module__ == module.__name__ and not name.startswith("_"):
            policies.append(obj)
    decorated = []
    for fn in policies:
        policy_id = fn.__name__
        decorated.append((policy_id, fn))
    decorated.sort(key=lambda x: x[0])
    return [fn for _, fn in decorated]


def _aggregate(decisions: List[Decision]) -> str:
    if any(d["decision"] == "DENY" for d in decisions):
        return "DENY"
    if any(d["decision"] == "HOLD" for d in decisions):
        return "HOLD"
    return "ALLOW"


def simulate_policies(
    bundles_dir: str,
    policies_module: str,
    out_dir: str,
    tenant_id: Optional[str] = None,
) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    policy_fns = discover_policies(policies_module)
    bundles = load_bundles(bundles_dir, tenant_id=tenant_id)
    written: list[str] = []

    for bundle in bundles:
        decisions = []
        for fn in policy_fns:
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
        output = {
            "contract_version": "v1",
            "prefix": bundle.prefix,
            "bundle_key": bundle.bundle_key,
            "tenant_id": bundle.tenant_id,
            "effective_tenant_id": bundle.effective_tenant_id,
            "aggregate_decision": _aggregate(decisions),
            "decisions": decisions,
        }
        out_path = os.path.join(out_dir, f"{output_prefix(bundle)}_policy_simulation.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(output, fh, indent=2, sort_keys=True)
        written.append(os.path.abspath(out_path))
    return written
