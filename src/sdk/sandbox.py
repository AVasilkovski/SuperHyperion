"""TRUST-1.0.2 Local policy sandbox simulation (bundle-only, read-only)."""

from __future__ import annotations

import importlib
import inspect
import json
import os
from typing import Callable, Dict, List

from src.sdk.bundles import BundleView, discover_bundle_paths, load_bundle_view

Decision = Dict[str, str]


def _discover_policies(module_name: str) -> list[Callable[[BundleView], Decision]]:
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


def simulate_policies(bundles_dir: str, policies_module: str, out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    policy_fns = _discover_policies(policies_module)
    bundle_paths = discover_bundle_paths(bundles_dir)
    written: list[str] = []

    for prefix in sorted(bundle_paths):
        bundle = load_bundle_view(bundle_paths[prefix], prefix)
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
            "prefix": prefix,
            "aggregate_decision": _aggregate(decisions),
            "decisions": decisions,
        }
        out_path = os.path.join(out_dir, f"{prefix}_policy_simulation.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(output, fh, indent=2, sort_keys=True)
        written.append(os.path.abspath(out_path))
    return written
