"""Built-in read-only policies (no DSL)."""

from __future__ import annotations

from src.sdk.bundles import BundleView


def require_replay_pass(bundle: BundleView) -> dict:
    policy_id = "require_replay_pass"
    if bundle.manifest is None:
        return {
            "policy_id": policy_id,
            "decision": "ALLOW",
            "code": "NO_CAPSULE",
            "reason": "No capsule manifest present.",
        }
    if bundle.replay is None or bundle.replay.status != "PASS":
        return {
            "policy_id": policy_id,
            "decision": "DENY",
            "code": "REPLAY_NOT_PASS",
            "reason": "Capsule present but replay verdict is missing or non-PASS.",
        }
    return {
        "policy_id": policy_id,
        "decision": "ALLOW",
        "code": "PASS",
        "reason": "Replay verdict is PASS.",
    }


def deny_unsafe_bypass(bundle: BundleView) -> dict:
    policy_id = "deny_unsafe_bypass"
    gate_code = bundle.governance.gate_code or ""
    code = "ALLOW"
    decision = "ALLOW"
    reason = "No unsafe bypass indicators found."
    if "BYPASS" in gate_code.upper() or "UNSAFE" in gate_code.upper():
        decision = "DENY"
        code = "UNSAFE_BYPASS"
        reason = f"Unsafe governance bypass indicator detected in gate_code={gate_code}."
    return {
        "policy_id": policy_id,
        "decision": decision,
        "code": code,
        "reason": reason,
    }


def hold_on_missing_capsule_when_commit(bundle: BundleView) -> dict:
    policy_id = "hold_on_missing_capsule_when_commit"
    if bundle.governance.status == "STAGED" and bundle.manifest is None:
        return {
            "policy_id": policy_id,
            "decision": "HOLD",
            "code": "COMMIT_MISSING_CAPSULE",
            "reason": "Governance indicates commit path but capsule manifest is missing.",
        }
    return {
        "policy_id": policy_id,
        "decision": "ALLOW",
        "code": "PASS",
        "reason": "Capsule presence is coherent with governance status.",
    }
