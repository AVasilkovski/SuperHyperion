"""
TRUST-1.0 SDK — Audit Bundle Export

Writes deterministic, auditor-friendly JSON artifacts for a governed run.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from src.sdk.types import GovernedResultV1


def _json_dump(obj: dict, path: str) -> None:
    """Write *obj* as pretty JSON with stable key ordering."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, default=str)


def _file_prefix(result: "GovernedResultV1") -> str:
    """Derive a filesystem-safe prefix for bundle files."""
    if result.capsule_id:
        return result.capsule_id
    return f"tenant-{result.tenant_id}"


def _source_refs(prefix: str) -> dict[str, str]:
    """Build canonical cross-file references for audit bundle artifacts."""
    return {
        "governance_summary_file": f"{prefix}_governance_summary.json",
        "replay_verdict_file": f"{prefix}_replay_verify_verdict.json",
        "capsule_manifest_file": f"{prefix}_run_capsule_manifest.json",
    }


class AuditBundleExporter:
    """Enterprise-grade exporter for audit bundles."""

    @staticmethod
    def export(result: "GovernedResultV1", out_dir: str) -> List[str]:
        """
        Export audit-friendly JSON files for *result* into *out_dir*.

        Files written:
            <prefix>_governance_summary.json
            <prefix>_replay_verify_verdict.json   (if replay_verdict present)
            <prefix>_run_capsule_manifest.json     (if capsule_id present)

        Returns:
            List of absolute paths to the written files.
        """
        os.makedirs(out_dir, exist_ok=True)
        prefix = _file_prefix(result)
        source_refs = _source_refs(prefix)
        written: List[str] = []

        # 1. Governance summary
        if result.governance is not None:
            p = os.path.join(out_dir, f"{prefix}_governance_summary.json")
            governance_envelope = {
                **result.governance.model_dump(),
                "source_refs": source_refs,
            }
            _json_dump(governance_envelope, p)
            written.append(os.path.abspath(p))

        # 2. Replay verdict
        if result.replay_verdict is not None:
            p = os.path.join(out_dir, f"{prefix}_replay_verify_verdict.json")
            replay_envelope = {
                **result.replay_verdict.model_dump(),
                "source_refs": source_refs,
            }
            _json_dump(replay_envelope, p)
            written.append(os.path.abspath(p))

        # 3. Capsule manifest
        if result.capsule_id is not None:
            manifest = {
                "capsule_id": result.capsule_id,
                "tenant_id": result.tenant_id,
                "evidence_ids": result.evidence_ids,
                "mutation_ids": result.mutation_ids,
                "intent_id": result.intent_id,
                "proposal_id": result.proposal_id,
                "status": result.status,
                "source_refs": source_refs,
            }
            p = os.path.join(out_dir, f"{prefix}_run_capsule_manifest.json")
            _json_dump(manifest, p)
            written.append(os.path.abspath(p))

        return written
