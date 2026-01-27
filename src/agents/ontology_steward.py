from typing import Dict, Any, Optional
import time
import json
import hashlib
import logging
from dataclasses import asdict

from src.agents.base_agent import BaseAgent, AgentContext
from src.epistemic.status import EpistemicStatus

logger = logging.getLogger(__name__)
class OntologySteward(BaseAgent):
    """
    Step 13: Updates the hypergraph with vetted knowledge and full v2.2 audit trails.
    """
    
    def __init__(self, confidence_threshold: float = 0.7):
        super().__init__(name="OntologySteward")
        self.confidence_threshold = confidence_threshold
    
    async def run(self, context: AgentContext) -> AgentContext:
        """Persist all v2.2 artifacts and execute approved writes."""
        session_id = context.graph_context.get("session_id", f"sess-{time.time_ns()}")
        user_query = context.graph_context.get("user_query", "unknown")
        
        # 1. Persist Session
        try:
             self.insert_to_graph(q_insert_session(session_id, user_query, "running"))
        except Exception as e:
             logger.debug(f"Session insert skipped (session_id={session_id}): {e}") 
        
        # 2. Persist Traces
        traces = context.graph_context.get("traces", [])
        for trace in traces:
            self.insert_to_graph(q_insert_trace(session_id, trace))
            
        # 2a. Persist Retrieval Assessment (Phase 12) — guarded
        ra = context.graph_context.get("retrieval_assessment")
        metrics = context.graph_context.get("retrieval_grade") or {}
        reground_attempts = int(context.graph_context.get("reground_attempts", 0) or 0)

        should_persist_ra = bool(ra) or bool(metrics) or reground_attempts > 0

        if should_persist_ra:
            if not ra:
                ra = {
                    "metrics": {
                        "coverage": metrics.get("coverage", 0.0),
                        "provenance": metrics.get("provenance_score", 0.0),
                        "conflict": metrics.get("conflict_density", 0.0),
                    },
                    "reground_attempts": reground_attempts,
                    "retrieval_decision": context.graph_context.get("retrieval_decision", "speculate"),
                    "retrieval_refinement": context.graph_context.get("retrieval_refinement"),
                    "grade": metrics.get("grade", "unknown"),
                    "reasoning": metrics.get("reasoning", ""),
                    "refinement_count": metrics.get("refinement_count", 0),
                }
            self.insert_to_graph(q_insert_retrieval_assessment(session_id, ra))

        # 2b. Persist Meta-Critique (Phase 12)
        mc = context.graph_context.get("meta_critique", {})
        if mc:
            self.insert_to_graph(q_insert_meta_critique(session_id, mc))

        # 2c. Persist Speculative Hypotheses (Phase 11)
        spec_ctx = context.graph_context.get("speculative_context") or {}
        if spec_ctx:
            for claim_id, blob in spec_ctx.items():
                alts = blob.get("alternatives") or []
                for i, alt in enumerate(alts):
                    try:
                        self.insert_to_graph(q_insert_speculative_hypothesis(
                            session_id=session_id,
                            claim_id=claim_id,
                            alt_index=i,
                            alt=alt,
                            full_claim_blob=blob,
                        ))
                        # Optional: Link to proposition if exists (best effort)
                        try:
                            self.insert_to_graph(q_insert_speculative_hypothesis_targets_proposition(
                                session_id, claim_id, i
                            ))
                        except Exception:
                            pass # Target proposition might not exist yet
                    except Exception as e:
                        logger.error(f"Speculative hypothesis insert failed: {e}")

        # 3. Persist Template Executions + Validation Evidence
        executions = context.graph_context.get("template_executions", [])
        for exec_rec in executions:
            # Handle both dict and object
            ex_data = exec_rec.model_dump() if hasattr(exec_rec, "model_dump") else exec_rec
            self.insert_to_graph(q_insert_execution(session_id, ex_data))
            
            # Persist validation-evidence for successful executions (optional Phase 12.1)
            # SKIPPING here - we now persist the full 'Evidence' objects below
            pass

        # 3b. Persist Full Evidence Objects (Phase 13)
        evidence_list = context.graph_context.get("evidence", [])
        for ev in evidence_list:
             # handle dict vs object
             ev_data = ev.model_dump() if hasattr(ev, "model_dump") else (asdict(ev) if hasattr(ev, "__dataclass_fields__") else ev)
             
             try:
                 self.insert_to_graph(q_insert_validation_evidence(session_id, ev_data))
             except Exception as e:
                 logger.error(f"Evidence insert failed (id={ev_data.get('execution_id')}): {e}")
        # 4. Persist Epistemic Proposals
        proposals = context.graph_context.get("epistemic_update_proposal", [])
        for prop in proposals:
            self.insert_to_graph(q_insert_proposal(session_id, prop))
            
        # 5. Persist Write Intents (Staged)
        intents = context.graph_context.get("write_intents", [])
        for intent in intents:
             status = "staged"
             approved_list = context.graph_context.get("approved_write_intents", [])
             is_approved = any(a.get("intent_id") == intent.get("intent_id") for a in approved_list)
             if is_approved:
                 status = "approved"
             
             self.insert_to_graph(q_insert_write_intent(session_id, intent, status))

        # 6. Execute Approved Intents & Log Status Events
        approved_intents = context.graph_context.get("approved_write_intents", [])
        committed = []
        failed = []
        
        for intent in approved_intents:
            success, err_msg = self._execute_intent(intent)
            
            # Log status event
            final_status = "executed" if success else "failed"
            payload = {"intent_type": intent.get("intent_type", "unknown")}
            if err_msg:
                payload["error"] = err_msg
                
            self.insert_to_graph(q_insert_intent_status_event(
                intent.get("intent_id"), 
                final_status, 
                payload
            ))
            
            if success:
                committed.append(intent)
            else:
                failed.append(intent)
        
        # 7. Finalize Session (ended-at + run-status transition)
        final_status = "failed" if failed else "complete"
        
        # Delete old ended-at first for idempotency
        if hasattr(self, 'db'):
            self.db.query_delete(q_delete_session_ended_at(session_id))
        else:
            from src.db.typedb_client import typedb
            typedb.query_delete(q_delete_session_ended_at(session_id))

        self.insert_to_graph(q_set_session_ended_at(session_id))

        if hasattr(self, 'db'):
            self.db.query_delete(q_delete_session_run_status(session_id))
            self.db.query_insert(q_insert_session_run_status(session_id, final_status))
        else:
            # Fallback for compilation context
            from src.db.typedb_client import typedb
            typedb.query_delete(q_delete_session_run_status(session_id))
            typedb.query_insert(q_insert_session_run_status(session_id, final_status))

        # Summary logging
        logger.info(
            f"Steward Report: "
            f"{len(executions)} execs, "
            f"{len(proposals)} proposals, "
            f"{len(committed)} writes committed"
        )
        
        # Update context for final output
        context.graph_context["committed_intents"] = committed
        context.graph_context["failed_intents"] = failed
        
        return context

    def _execute_intent(self, intent: Dict) -> tuple[bool, Optional[str]]:
        """
        Execute a write intent using separate delete/insert queries.
        Returns (success, error_message).
        """
        intent_type = intent.get("intent_type")
        payload = intent.get("payload", {})
        
        try:
            if intent_type == "update_epistemic_status":
                claim_id = payload.get("claim_id")
                new_status = payload.get("status")
                
                # Separate queries for valid TypeQL
                delete_q = f'''
                match $c isa proposition, has entity-id "{escape(claim_id)}", has epistemic-status $old;
                delete $c has epistemic-status $old;
                '''
                
                insert_q = f'''
                match $c isa proposition, has entity-id "{escape(claim_id)}";
                insert $c has epistemic-status "{escape(new_status)}";
                '''
                
                # Use base agent's DB connection directly
                if hasattr(self, 'db'):
                    self.db.query_delete(delete_q)
                    self.db.query_insert(insert_q)
                else:
                    # Fallback to global typedb instance if self.db not set (legacy)
                    from src.db.typedb_client import typedb
                    typedb.query_delete(delete_q)
                    typedb.query_insert(insert_q)
                    
                return True, None
                
            elif intent_type == "create_claim":
                # Implementation for creating new claims
                pass
                
            return True, None
        except Exception as e:
            logger.error(f"Failed to execute intent {intent}: {e}")
            return False, str(e)

# ============================================================================
# TypeQL Builders (v2.2 Schema)
# ============================================================================

def escape(s: str) -> str:
    return (str(s) or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")

def iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")

def sha256_json(data: Any) -> str:
    """Compute stable hash of JSON-serializable data."""
    try:
        s = json.dumps(data, sort_keys=True)
        return hashlib.sha256(s.encode()).hexdigest()
    except:
        return "hash-error"

def q_insert_session(session_id: str, user_query: str, status: str) -> str:
    uq = escape(user_query)
    # Check if exists first? TypeDB insert is additive. 
    # If session-id is @key, duplicates will fail. 
    # For now, we assume this is the start or we catch the error.
    return f'''
    insert $s isa run-session,
      has session-id "{escape(session_id)}",
      has user-query "{uq}",
      has started-at {iso_now()},
      has run-status "{escape(status)}";
    '''

def q_set_session_ended_at(session_id: str) -> str:
    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}";
    insert $s has ended-at {iso_now()};
    '''

def q_delete_session_ended_at(session_id: str) -> str:
    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}", has ended-at $t;
    delete $s has ended-at $t;
    '''

def q_delete_session_run_status(session_id: str) -> str:
    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}", has run-status $old;
    delete $s has run-status $old;
    '''

def q_insert_session_run_status(session_id: str, status: str) -> str:
    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}";
    insert $s has run-status "{escape(status)}";
    '''

def q_insert_trace(session_id: str, trace: dict) -> str:
    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}";
    insert
      $t isa trace-entry,
        has step-index {int(trace.get("step_index", 0))},
        has node-name "{escape(trace.get("node", "unknown"))}",
        has phase "{escape(trace.get("phase", "unknown"))}",
        has agent-id "{escape(trace.get("agent_id", "unknown"))}",
        has trace-summary "{escape(trace.get("summary", ""))}",
        has created-at {iso_now()};
      (session: $s, trace: $t) isa session-has-trace;
    '''

def q_insert_execution(session_id: str, ex: dict) -> str:
    params_hash = ex.get("params_hash") or sha256_json(ex.get("params", {}))
    result_hash = ex.get("result_hash") or sha256_json(ex.get("result", {}))
    
    payload = {
        "warnings": ex.get("warnings", []),
        "result_summary": str(ex.get("result", ""))[:200]
    }
    payload_json = json.dumps(payload, sort_keys=True)
    
    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}";
    insert
      $e isa template-execution,
        has execution-id "{escape(ex.get("execution_id"))}",
        has template-id "{escape(ex.get("template_id",""))}",
        has entity-id "{escape(ex.get("claim_id",""))}",
        has claim-id "{escape(ex.get("claim_id",""))}",
        has success {str(bool(ex.get("success", False))).lower()},
        has runtime-ms {int(ex.get("runtime_ms", 0))},
        has params-hash "{params_hash}",
        has result-hash "{result_hash}",
        has json "{escape(payload_json)}",
        has created-at {iso_now()};
      (session: $s, execution: $e) isa session-has-execution;
    '''

def q_insert_proposal(session_id: str, p: dict) -> str:
    # Also link to proposition via proposal-targets-proposition IF claim exists
    claim_id = p.get("claim_id")
    
    base_insert = f'''
    match $s isa run-session, has session-id "{escape(session_id)}";
    insert
      $p isa epistemic-proposal,
        has proposed-status "{escape(p.get("proposed_status",""))}",
        has max-allowed-status "{escape(p.get("max_allowed_status",""))}",
        has final-proposed-status "{escape(p.get("final_proposed_status",""))}",
        has confidence-score {float(p.get("confidence_score", 0.0))},
        has json "{escape(json.dumps(p, sort_keys=True))}",
        has cap-reasons "{escape(json.dumps(p.get("cap_reasons",[]), sort_keys=True))}",
        has requires-hitl {str(bool(p.get("requires_hitl", False))).lower()},
        has created-at {iso_now()};
      (session: $s, proposal: $p) isa session-has-epistemic-proposal;
    '''

    if not claim_id:
        return base_insert

    # claim_id exists: link to proposition (hard dependency)
    return f'''
    match
      $s isa run-session, has session-id "{escape(session_id)}";
      $prop isa proposition, has entity-id "{escape(claim_id)}";
    insert
      $p isa epistemic-proposal,
        has proposed-status "{escape(p.get("proposed_status",""))}",
        has max-allowed-status "{escape(p.get("max_allowed_status",""))}",
        has final-proposed-status "{escape(p.get("final_proposed_status",""))}",
        has confidence-score {float(p.get("confidence_score", 0.0))},
        has json "{escape(json.dumps(p, sort_keys=True))}",
        has cap-reasons "{escape(json.dumps(p.get("cap_reasons",[]), sort_keys=True))}",
        has requires-hitl {str(bool(p.get("requires_hitl", False))).lower()},
        has created-at {iso_now()};
      (session: $s, proposal: $p) isa session-has-epistemic-proposal;
      (proposal: $p, proposition: $prop) isa proposal-targets-proposition;
    '''

def q_insert_write_intent(session_id: str, intent: dict, status: str = "staged") -> str:
    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}";
    insert
      $i isa write-intent,
        has intent-id "{escape(intent.get("intent_id"))}",
        has intent-type "{escape(intent.get("intent_type",""))}",
        has intent-status "{escape(status)}",
        has impact-score {float(intent.get("impact_score", 0.0))},
        has json "{escape(json.dumps(intent, sort_keys=True))}",
        has created-at {iso_now()};
      (session: $s, write-intent: $i) isa session-has-write-intent;
    '''

def q_insert_intent_status_event(intent_id: str, status: str, payload: Optional[Dict] = None) -> str:
    payload = payload or {}
    return f'''
    match $i isa write-intent, has intent-id "{escape(intent_id)}";
    insert 
      $e isa intent-status-event,
        has intent-id "{escape(intent_id)}",
        has intent-status "{escape(status)}",
        has json "{escape(json.dumps(payload, sort_keys=True))}",
        has created-at {iso_now()};
      (write-intent: $i, intent-status-event: $e) isa intent-has-status-event;
    '''

def q_insert_retrieval_assessment(session_id: str, ra: dict) -> str:
    # normalize from either shape
    metrics = ra.get("metrics") or {}
    grade_blob = {
        "grade": ra.get("grade"),
        "reasoning": ra.get("reasoning"),
        "refinement_count": ra.get("refinement_count", 0),
    }

    # metrics names: coverage, provenance-score, conflict-density
    coverage = float(metrics.get("coverage", ra.get("coverage", 0.0)))
    prov = float(metrics.get("provenance", ra.get("provenance_score", ra.get("provenance-score", 0.0))))
    conf = float(metrics.get("conflict", ra.get("conflict_density", ra.get("conflict-density", 0.0))))

    reground_attempts = int(ra.get("reground_attempts", ra.get("reground-attempts", 0)))
    retrieval_decision = ra.get("retrieval_decision", ra.get("retrieval-decision", "speculate"))

    payload = {
        **grade_blob,
        "metrics": {"coverage": coverage, "provenance": prov, "conflict": conf},
        "retrieval_refinement": ra.get("retrieval_refinement"),
    }

    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}";
    insert
      $r isa retrieval-assessment,
        has coverage {coverage},
        has provenance-score {prov},
        has conflict-density {conf},
        has reground-attempts {reground_attempts},
        has retrieval-decision "{escape(retrieval_decision)}",
        has json "{escape(json.dumps(payload, sort_keys=True))}",
        has created-at {iso_now()};
      (session: $s, retrieval-assessment: $r) isa session-has-retrieval-assessment;
    '''

def q_insert_meta_critique(session_id: str, mc: dict) -> str:
    payload = {
        "critique": mc.get("critique", ""),
        "severity": mc.get("severity", "low"),
        "cap_suggestion": mc.get("cap_suggestion"),
    }
    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}";
    insert
      $m isa meta-critique-report,
        has severity "{escape(payload["severity"])}",
        has json "{escape(json.dumps(payload, sort_keys=True))}",
        has created-at {iso_now()};
      (session: $s, meta-critique: $m) isa session-has-meta-critique;
    '''

def q_insert_validation_evidence(session_id: str, ev: dict) -> str:
    # IMPORTANT: do NOT fall back to ev["entity_id"] (that's typically evidence id, not claim id)
    claim_id = ev.get("claim_id") or ev.get("claim-id") or ev.get("proposition_id") or ""
    exec_id = ev.get("execution_id") or ""
    template_id = ev.get("template_id") or ""

    # --- INVARIANT GUARD (Phase 11) ---
    # Validation evidence MUST have a claim_id to be grounded
    if not claim_id:
        raise ValueError(f"CRITICAL: Validation evidence missing claim_id! (exec_id={exec_id})")

    # Speculative evidence must NEVER be persisted as validation-evidence.
    # Handles both snake_case and kebab-case to prevent key drift.
    SPEC_KEYS = {"epistemic_status", "epistemic-status"}
    SPEC_CONTEXT_KEYS = {"speculative_context", "speculative-context"}

    def is_speculative(obj):
        # --- Critical bypass closure: scan JSON strings too ---
        if isinstance(obj, str):
            s = obj.strip()
            # Try parse JSON-looking strings
            if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                try:
                    return is_speculative(json.loads(s))
                except Exception:
                    pass
            # Last-resort tripwire (case-insensitive)
            s_lower = s.lower()
            return (
                '"speculative"' in s_lower
                or '"epistemic_status"' in s_lower
                or '"epistemic-status"' in s_lower
                or '"speculative_context"' in s_lower
                or '"speculative-context"' in s_lower
            )

        if isinstance(obj, dict):
            # Check epistemic status keys
            for k in SPEC_KEYS:
                if obj.get(k) == "speculative":
                    return True

            # Check speculative context keys
            if any(k in obj for k in SPEC_CONTEXT_KEYS):
                return True

            return any(is_speculative(v) for v in obj.values())

        if isinstance(obj, list):
            return any(is_speculative(v) for v in obj)

        return False

    if is_speculative(ev):
        raise ValueError(
            f"CRITICAL: Attempted to persist speculative evidence as validation-evidence! (exec_id={exec_id})"
        )

    success = bool(ev.get("success", False))
    conf = float(ev.get("confidence_score", ev.get("confidence", 0.0)) or 0.0)

    evid_id = f'ev-{exec_id}' if exec_id else f'ev-{time.time_ns()}'

    # Base payload from existing json or empty dict
    # If ev["json"] is a *string*, keep it in payload; guard above already scanned it.
    base_json = ev.get("json") if isinstance(ev.get("json"), dict) else {}

    exclude = {
        "claim_id", "claim-id", "proposition_id",
        "execution_id", "template_id", "success",
        "confidence_score", "confidence", "content", "json"
    }
    extra_fields = {k: v for k, v in ev.items() if k not in exclude}

    payload = {**base_json, **extra_fields}

    logger.info(f"DEBUG: Evidence Payload Keys: {list(payload.keys())}")
    if "feynman" in payload:
        logger.info(f"DEBUG: Feynman: {payload['feynman']}")

    return f'''
    match
      $s isa run-session, has session-id "{escape(session_id)}";
      $p isa proposition, has entity-id "{escape(claim_id)}";
    insert
      $e isa validation-evidence,
        has entity-id "{escape(evid_id)}",
        has content "{escape(ev.get("content",""))}",
        has template-id "{escape(template_id)}",
        has execution-id "{escape(exec_id)}",
        has claim-id "{escape(claim_id)}",
        has success {str(success).lower()},
        has confidence-score {conf},
        has json "{escape(json.dumps(payload, sort_keys=True))}",
        has created-at {iso_now()};
      (session: $s, evidence: $e) isa session-has-evidence;
      (evidence: $e, proposition: $p) isa evidence-for-proposition;
    '''

def q_insert_speculative_hypothesis(
    session_id: str,
    claim_id: str,
    alt_index: int,
    alt: Dict[str, Any],
    full_claim_blob: Dict[str, Any],
    belief_state: str = "proposed",
) -> str:
    # entity-id deterministic + idempotent per session/claim/index
    hid = f"shyp-{session_id}-{claim_id}-{alt_index}"

    payload = {
        "claim_id": claim_id,
        "alternative_index": alt_index,
        "alternative": alt,
        "claim_speculation_bundle": full_claim_blob,  # includes analogies/edge_cases if you want
        "epistemic_status": "speculative",
    }

    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}";
    insert
      $h isa speculative-hypothesis,
        has entity-id "{escape(hid)}",
        has claim-id "{escape(claim_id)}",
        has content "{escape(str(alt.get("hypothesis","") or "speculative alternative"))}",
        has belief-state "{escape(belief_state)}",
        has epistemic-status "speculative",
        has confidence-score {float(alt.get("confidence", 0.0))},
        has json "{escape(json.dumps(payload, sort_keys=True))}",
        has created-at {iso_now()};
      (session: $s, hypothesis: $h) isa session-has-speculative-hypothesis;
    '''

def q_insert_speculative_hypothesis_targets_proposition(
    session_id: str,
    claim_id: str,
    alt_index: int,
) -> str:
    hid = f"shyp-{session_id}-{claim_id}-{alt_index}"
    return f'''
    match
      $h isa speculative-hypothesis, has entity-id "{escape(hid)}";
      $p isa proposition, has entity-id "{escape(claim_id)}";
    insert
      (hypothesis: $h, proposition: $p) isa speculative-hypothesis-targets-proposition;
    '''

# Global instance
ontology_steward = OntologySteward()
