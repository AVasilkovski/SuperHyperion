#!/usr/bin/env python3
"""OPS-1.2 deterministic CI trust gates (COMMIT + HOLD)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.agents.base_agent import AgentContext
from src.agents.ontology_steward import OntologySteward
from src.graph.nodes.governance_gate import governance_gate_node
from src.graph.state import create_initial_state
from src.graph.workflow_v21 import integrate_node
from src.hitl.intent_service import IntentStatus, WriteIntent, write_intent_service
from src.hitl.intent_store import InMemoryIntentStore
from src.sdk.governed_run import _build_result
from src.verification.replay_verify import verify_capsule


def _reset_intent_service() -> None:
    """Reset global intent service to a fresh in-memory store for deterministic gates."""
    write_intent_service._store = InMemoryIntentStore()  # type: ignore[attr-defined]
    write_intent_service._intent_cache.clear()  # type: ignore[attr-defined]


def _seed_deterministic_intent(
    *,
    intent_id: str,
    proposal_id: str,
    evidence_ids: list[str],
    scope_lock_id: str,
) -> None:
    """Insert a deterministic staged intent record consumed by governance checks."""
    now = datetime.now()
    write_intent_service._store.insert_intent(  # type: ignore[attr-defined]
        intent_id=intent_id,
        intent_type="stage_epistemic_proposal",
        lane="grounded",
        payload={
            "claim_id": "ci-claim-1",
            "action": "REVISE",
            "evidence_ids": list(evidence_ids),
            "rationale": "deterministic ci gate",
            "conflict_score": 0.0,
        },
        impact_score=0.0,
        status=IntentStatus.STAGED.value,
        created_at=now,
        expires_at=now + timedelta(days=7),
        scope_lock_id=scope_lock_id,
        supersedes_intent_id=None,
        proposal_id=proposal_id,
    )
    write_intent_service._intent_cache[intent_id] = WriteIntent(  # type: ignore[attr-defined]
        intent_id=intent_id,
        intent_type="stage_epistemic_proposal",
        lane="grounded",
        payload={
            "claim_id": "ci-claim-1",
            "action": "REVISE",
            "evidence_ids": list(evidence_ids),
            "rationale": "deterministic ci gate",
            "conflict_score": 0.0,
        },
        impact_score=0.0,
        status=IntentStatus.STAGED,
        created_at=now,
        expires_at=now + timedelta(days=7),
        scope_lock_id=scope_lock_id,
        proposal_id=proposal_id,
    )


def _deterministic_evidence() -> list[dict[str, Any]]:
    return [
        {
            "claim_id": "ci-claim-1",
            "execution_id": "exec-ci-1",
            "template_qid": "codeact_v1@1.0.0",
            "template_id": "codeact_v1",
            "scope_lock_id": "scope-ci-1",
            "success": True,
            "confidence_score": 0.99,
            "content": "deterministic ci validation evidence",
        }
    ]




def _typedb_ready() -> tuple[bool, str]:
    """Return (ready, reason) for TypeDB-backed deterministic gate execution."""
    try:
        from src.db.typedb_client import TypeDBConnection

        db = TypeDBConnection()
        driver = db.connect()
        if db._mock_mode or driver is None:
            return False, "typedb_unavailable_or_mock_mode"

        _ = [d.name for d in driver.databases.all()]
        return True, "ok"
    except Exception as exc:
        return False, f"typedb_probe_failed:{exc}"


def _should_enforce_typedb() -> bool:
    """CI runs must fail closed if TypeDB is unreachable; local runs may skip."""
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


def _ensure_gate_prereqs(steward: OntologySteward, session_id: str, gate: str) -> None:
    """Insert deterministic seed entities required by steward evidence writes."""
    try:
        steward.insert_to_graph(
            f'insert $s isa run-session, has session-id "{session_id}";',
            cap=steward._write_cap,
        )
    except Exception:
        # Idempotent behavior for reruns in same database.
        pass

    if gate == "commit":
        try:
            steward.insert_to_graph(
                'insert $p isa proposition, has entity-id "ci-claim-1";',
                cap=steward._write_cap,
            )
        except Exception:
            # Idempotent behavior for reruns in same database.
            pass


async def _run_gate(gate: str, out_dir: str) -> tuple[bool, dict[str, Any]]:
    _reset_intent_service()

    state = create_initial_state(f"OPS-1.2 deterministic gate={gate}")
    state["tenant_id"] = "ci-tenant"
    state["graph_context"]["session_id"] = f"sess-ops12-{gate}"
    state["graph_context"]["atomic_claims"] = [{"claim_id": "ci-claim-1", "content": "CI claim"}]

    steward = OntologySteward()

    session_id = state["graph_context"]["session_id"]
    _ensure_gate_prereqs(steward, session_id, gate)

    ctx = AgentContext()
    ctx.graph_context = {
        "session_id": state["graph_context"]["session_id"],
        "user_query": f"OPS-1.2 deterministic gate={gate}",
        "evidence": _deterministic_evidence() if gate == "commit" else [],
        "tenant_id": state["tenant_id"],
    }

    ctx = await steward.run(ctx)
    state["graph_context"].update(ctx.graph_context)

    if gate == "commit":
        persisted_ids = sorted(state["graph_context"].get("persisted_all_evidence_ids", []))
        if not persisted_ids:
            return False, {"error": "No persisted evidence IDs from steward"}

        or_clauses = " or ".join(f'{{ $eid == "{eid}"; }}' for eid in persisted_ids)
        evidence_probe_query = f'''
        match
            $s isa run-session, has session-id "{state["graph_context"]["session_id"]}";
            (session: $s, evidence: $e) isa session-has-evidence;
            $e has entity-id $eid;
            {or_clauses};
        select $eid;
        '''
        ledger_rows = steward.query_graph(evidence_probe_query)
        ledger_ids = {str(r.get("eid")) for r in ledger_rows if r.get("eid")}
        missing_ids = [eid for eid in persisted_ids if eid not in ledger_ids]
        if missing_ids:
            return False, {
                "gate": gate,
                "error": "Persisted evidence IDs missing from ledger linkage",
                "session_id": state["graph_context"]["session_id"],
                "missing_evidence_ids": missing_ids,
                "persisted_evidence_ids": persisted_ids,
            }

        _seed_deterministic_intent(
            intent_id="intent-ci-1",
            proposal_id="prop-ci-1",
            evidence_ids=persisted_ids,
            scope_lock_id="scope-ci-1",
        )
        state["graph_context"]["latest_staged_intent_id"] = "intent-ci-1"
        state["graph_context"]["latest_staged_proposal_id"] = "prop-ci-1"
        state["graph_context"]["scope_lock_id"] = "scope-ci-1"

    state = await governance_gate_node(state)
    state = await integrate_node(state)

    result = _build_result(state, tenant_id=state["tenant_id"])
    files = result.export_audit_bundle(out_dir)

    if gate == "hold":
        gov = state.get("governance") or {}
        ok = (
            gov.get("status") == "HOLD"
            and gov.get("hold_code") == "NO_EVIDENCE_PERSISTED"
            and state.get("run_capsule") is None
        )
        return ok, {"gate": gate, "governance": gov, "files": files}

    gov = state.get("governance") or {}
    capsule = state.get("run_capsule") or {}
    if gov.get("status") != "STAGED" or not capsule.get("capsule_id"):
        return False, {"gate": gate, "governance": gov, "capsule": capsule, "files": files}

    verdict = verify_capsule(
        capsule["capsule_id"],
        {
            "session_id": capsule.get("session_id", ""),
            "query_hash": capsule.get("query_hash", ""),
            "tenant_id": capsule.get("tenant_id", ""),
            "scope_lock_id": capsule.get("scope_lock_id", ""),
            "intent_id": capsule.get("intent_id", ""),
            "proposal_id": capsule.get("proposal_id", ""),
            "evidence_ids": capsule.get("evidence_ids", []),
            "mutation_ids": capsule.get("mutation_ids", []),
            "capsule_hash": capsule.get("capsule_hash", ""),
            "_has_mutation_snapshot": True,
        },
        tenant_id=state.get("tenant_id"),
    )
    ok = verdict.status == "PASS"
    replay_details = {
        "reasons": getattr(verdict, "reasons", []),
        "details": getattr(verdict, "details", {}),
    }
    return ok, {
        "gate": gate,
        "governance": gov,
        "capsule_id": capsule.get("capsule_id"),
        "replay_status": verdict.status,
        "replay_verdict": replay_details,
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="OPS-1.2 deterministic CI trust gates")
    parser.add_argument("--gate", required=True, choices=["commit", "hold"])
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    db_ready, db_reason = _typedb_ready()
    if not db_ready:
        payload = {
            "gate": args.gate,
            "status": "SKIP",
            "reason": db_reason,
        }
        if args.json_output:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            print(payload)
        return 1 if _should_enforce_typedb() else 0

    ok, payload = asyncio.run(_run_gate(args.gate, args.out_dir))
    if args.json_output:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
