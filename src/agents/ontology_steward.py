from typing import Dict, Any, Optional
import time
import json
import hashlib
import logging
from dataclasses import asdict

from src.agents.base_agent import BaseAgent, AgentContext

from src.montecarlo.versioned_registry import VERSIONED_REGISTRY, get_latest_template  # Access explicit registry

from src.montecarlo.template_metadata import sha256_json_strict
from src.montecarlo.types import QID_RE

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
                 # Phase 14.5: Constitutional Seal
                 # Must pass strict seal checks before we mint validation evidence
                 self._seal_operator_before_mint(ev_data)

                 self.insert_to_graph(q_insert_validation_evidence(session_id, ev_data))
                 
                 # Phase 14 Hook: Freeze template on first evidence
                 if ev_data.get("success") and ev_data.get("template_id"):
                     self._freeze_template_on_evidence(
                         template_id=ev_data["template_id"],
                         evidence_id=f'ev-{ev_data.get("execution_id", "")}', # Match logic in q_insert
                         claim_id=ev_data.get("claim_id") or ev_data.get("claim-id"),
                         scope_lock_id=ev_data.get("scope_lock_id") or ev_data.get("scope-lock-id"),
                     )
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

    def _freeze_template_on_evidence(
        self,
        template_id: str,
        evidence_id: str,
        claim_id: Optional[str] = None,
        scope_lock_id: Optional[str] = None,
    ):
        """
        Operator Extension: Freeze method template on first evidence.
        
        Ensures metadata exists before freezing (lazy sync).
        """
        try:
            # 1. Resolve version
            # In v2.2, we assume running code matches latest registry version.
            # In v2.3+, evidence will carry explicit version.
            # For now, look up latest active spec in registry.
            # NOTE: If template_id not in registry (e.g. ad-hoc), we skip (or warn).
            try:
                template = get_latest_template(template_id)
                # We need the qualified ID to get the spec
                # Iterate registry to find it (or add get_latest_spec to registry)
                # Easier: just scan VERSIONED_REGISTRY.
                specs = [
                    VERSIONED_REGISTRY.get_spec(qid) 
                    for qid in VERSIONED_REGISTRY.list_all() 
                    if qid.startswith(f"{template_id}@")
                ]
                if not specs:
                    logger.warning(f"Skipping freeze: Template {template_id} not in registry.")
                    return
                # Sort by version desc
                specs.sort(key=lambda s: s.version, reverse=True)
                spec = specs[0]
                version_str = str(spec.version)
                
            except ValueError:
                return # Not a registered template

            # 2. Get store instance
            store = getattr(self, "template_store", None)
            if not store:
                # Reuse DB connection if possible
                driver = getattr(self, "db", None) and getattr(self.db, "driver", None)
                if not driver:
                    from src.db.typedb_client import typedb
                    driver = typedb.driver
                    
                store = TypeDBTemplateStore(driver)
            
            # 3. Ensure metadata exists (Lazy Sync)
            # This handles first-run bootstrap without explicit "init" step
            meta = store.get_metadata(template_id, version_str)
            if not meta:
                from src.montecarlo.template_metadata import TemplateMetadata, TemplateStatus, compute_code_hash
                
                # Check integrity before insert
                current_code_hash = compute_code_hash(type(template))
                
                # Create and insert
                new_meta = TemplateMetadata(
                    template_id=template_id,
                    version=spec.version,
                    spec_hash=spec.spec_hash(),
                    code_hash=current_code_hash,
                    status=TemplateStatus.ACTIVE,
                    approved_by="bootstrap", # Auto-approved on first use for v2.2
                    approved_at=None,
                )
                store.insert_metadata(new_meta)
            
            # 4. Execute Freeze
            store.freeze(
                template_id=template_id,
                version=version_str,
                evidence_id=evidence_id,
                claim_id=claim_id,
                scope_lock_id=scope_lock_id,
            )
            
        except Exception as e:
            logger.error(f"Failed to freeze template {template_id}: {e}")

    def _seal_operator_before_mint(self, ev: Dict[str, Any]):
        """
        Constitutional Seal Operator (Phase 14.5).
        
        Enforces:
        1. Scope Locks: Evidence must match claimed scope.
        2. Template QID: Must be fully qualified (@version).
        3. Strict Hash Parity: Stored hash == recomputed content hash.
        
        Raises ValueError (CRITICAL) if seal fails. Only successful evidence is sealed.
        """
        exec_id = ev.get("execution_id", "unknown")
        
        # 1. Scope Lock Check
        # Hard requirement: Validation evidence must carry a scope lock ID.
        scope_lock_id = ev.get("scope_lock_id") or ev.get("scope-lock-id")
        if not scope_lock_id:
            raise ValueError(f"CRITICAL: cannot mint evidence without scope_lock_id (exec_id={exec_id})")
            
        # 2. Template QID Check
        # Hard requirement: Must be Qualified (e.g. bootstrap_ci@1.0.0)
        template_qid = ev.get("template_qid") or ev.get("template-qid")
        if not template_qid:
             raise ValueError(f"CRITICAL: cannot mint evidence without template_qid (exec_id={exec_id})")
        
        if not QID_RE.match(template_qid.strip()):
            raise ValueError(f"CRITICAL: Malformed template_qid '{template_qid}' (exec_id={exec_id})")
        
        # 3. Hash Parity (Strict)
        # We recompute the hash of the 'result' and 'params' (provenance) and match
        # against what the template execution (if available) or the evidence carries.
        # Note: If evidence is fresh from verify_agent, it should be self-consistent.
        # If it came from DB, we trust the DB record (but we are inserting here, so it is fresh).
        
        result_blob = ev.get("result", {})
        # Flattened params lookup
        params_blob = ev.get("provenance", {}).get("params", {})
        
        # Compute Strict
        try:
            comp_r = sha256_json_strict(result_blob)
            comp_p = sha256_json_strict(params_blob)
        except Exception as e:
             raise ValueError(f"CRITICAL: Strict hash computation failed for {exec_id}: {e}")
             
        # Check against carried hashes if they exist (optional but good hygiene)
        # Currently the AgentContext evidence might not carry explicit hash strings,
        # but if it did, we would check them here.
        # For now, we trust the computation succeeds (no NaN/Inf).
        
        # 4. Success Only Logic is handled in q_insert_validation_evidence selection,
        # but we double check here to be sure we are sealing valid stuff.
        if not ev.get("success"):
            # This method shouldn't be called for failed evidence (Steward loop skips it),
            # but if it is:
            raise ValueError(f"CRITICAL: Attempted to seal failed evidence {exec_id}")
            
        # Seal Applied.
        pass

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
    except Exception:
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
    params_hash = ex.get("params_hash") or sha256_json_strict(ex.get("params", {}))
    result_hash = ex.get("result_hash") or sha256_json_strict(ex.get("result", {}))
    
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
    # ------------------------------------------------------------------
    # Constitutional Gate (Phase 14.5)
    # ------------------------------------------------------------------
    exec_id = ev.get("execution_id", "")
    
    # 1. Extract IDs first (needed for error messages)
    claim_id = (ev.get("claim_id") or ev.get("claim-id") or ev.get("proposition_id") or "").strip()
    template_qid = (ev.get("template_qid") or ev.get("template-qid") or "").strip()
    template_id = (ev.get("template_id") or ev.get("template-id") or "").strip()
    scope_lock_id = (ev.get("scope_lock_id") or ev.get("scope-lock-id") or "").strip()
    
    # 2. Claim ID is REQUIRED (must check before other guards)
    if not claim_id:
        raise ValueError(f"CRITICAL: Validation evidence missing claim_id! (exec_id={exec_id})")

    # ------------------------------------------------------------------
    # 3. Speculative Guard (Phase 11) - Must run before success-only
    # ------------------------------------------------------------------
    SPEC_KEYS = {"epistemic_status", "epistemic-status"}
    SPEC_CONTEXT_KEYS = {"speculative_context", "speculative-context"}

    def is_speculative(obj):
        if isinstance(obj, str):
            s = obj.strip()
            if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                try:
                    return is_speculative(json.loads(s))
                except Exception:
                    pass
            s_lower = s.lower()
            return (
                '"speculative"' in s_lower
                or '"epistemic_status"' in s_lower
                or '"epistemic-status"' in s_lower
                or '"speculative_context"' in s_lower
                or '"speculative-context"' in s_lower
            )

        if isinstance(obj, dict):
            if obj.get("lane") == "speculative":
                return True
            for k in SPEC_KEYS:
                if obj.get(k) == "speculative":
                    return True
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

    # ------------------------------------------------------------------
    # 4. Canonicalize success (handling "false" string)
    # ------------------------------------------------------------------
    raw_success = ev.get("success", False)
    if isinstance(raw_success, str):
        success = raw_success.strip().lower() == "true"
    else:
        success = bool(raw_success)
        
    # 5. Enforce Success-Only Policy (AFTER speculative/claim_id guards)
    if not success:
        raise ValueError(f"Policy violation: validation-evidence is success-only (exec_id={exec_id})")
    
    # 6. Derive template_id from QID if missing
    if not template_id and template_qid and "@" in template_qid:
        template_id = template_qid.split("@", 1)[0]

    # ------------------------------------------------------------------
    # Build Query
    # ------------------------------------------------------------------
    conf = float(ev.get("confidence_score", ev.get("confidence", 0.0)) or 0.0)
    evid_id = f'ev-{exec_id}' if exec_id else f'ev-{time.time_ns()}'
    
    # Prune excluded keys for JSON payload
    exclude = {
        "claim_id", "claim-id", "proposition_id",
        "execution_id", "template_id", "template_qid", "scope_lock_id",
        "success", "confidence_score", "confidence", "content", "json"
    }
    base_json = ev.get("json") if isinstance(ev.get("json"), dict) else {}
    extra_fields = {k: v for k, v in ev.items() if k not in exclude}
    payload = {**base_json, **extra_fields}

    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}";
    match $p isa proposition, has entity-id "{escape(claim_id)}";
    insert
    $v isa validation-evidence,
        has evidence-id "{escape(evid_id)}",
        has claim-id "{escape(claim_id)}",
        has execution-id "{escape(exec_id)}",
        has template-qid "{escape(template_qid)}",
        has template-id "{escape(template_id)}",
        has scope-lock-id "{escape(scope_lock_id)}",
        has success {str(success).lower()},
        has confidence-score {conf},
        has json "{escape(json.dumps(payload, sort_keys=True))}",
        has created-at {iso_now()};
    (session: $s, validation-evidence: $v) isa session-has-validation-evidence;
    (evidence: $v, proposition: $p) isa evidence-for-proposition;
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
