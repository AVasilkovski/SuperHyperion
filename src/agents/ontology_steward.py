import hashlib
import json
import logging
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from src.agents.base_agent import AgentContext, BaseAgent
from src.epistemology.evidence_roles import (
    EvidenceRole,
    FailureMode,
    clamp_probability,
    require_evidence_role,
    validate_evidence_role,
    validate_failure_mode,
)

# Phase 16.1: Import from governance module
from src.governance.fingerprinting import make_evidence_id, make_negative_evidence_id
from src.montecarlo.template_metadata import sha256_json_strict
from src.montecarlo.types import QID_RE
from src.montecarlo.versioned_registry import (  # Access explicit registry
    VERSIONED_REGISTRY,
    get_latest_template,
)

logger = logging.getLogger(__name__)
class OntologySteward(BaseAgent):
    """
    Step 13: Updates the hypergraph with vetted knowledge and full v2.2 audit trails.
    """

    def __init__(self, confidence_threshold: float = 0.7):
        super().__init__(name="OntologySteward")
        from src.db.capabilities import WriteCap
        self._write_cap = WriteCap._mint()
        self.confidence_threshold = confidence_threshold

    async def run(self, context: AgentContext) -> AgentContext:
        """Persist all v2.2 artifacts and execute approved writes."""
        session_id = context.graph_context.get("session_id", f"sess-{time.time_ns()}")
        user_query = context.graph_context.get("user_query", "unknown")

        # 1. Persist Session
        try:
             self.insert_to_graph(q_insert_session(session_id, user_query, "running"), cap=self._write_cap)
        except Exception as e:
             logger.debug(f"Session insert skipped (session_id={session_id}): {e}")

        # 2. Persist Traces
        traces = context.graph_context.get("traces", [])
        for trace in traces:
            self.insert_to_graph(q_insert_trace(session_id, trace), cap=self._write_cap)

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
            self.insert_to_graph(q_insert_retrieval_assessment(session_id, ra), cap=self._write_cap)

        # 2b. Persist Meta-Critique (Phase 12)
        mc = context.graph_context.get("meta_critique", {})
        if mc:
            self.insert_to_graph(q_insert_meta_critique(session_id, mc), cap=self._write_cap)

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
                        ), cap=self._write_cap)
                        # Optional: Link to proposition if exists (best effort)
                        try:
                            self.insert_to_graph(q_insert_speculative_hypothesis_targets_proposition(
                                session_id, claim_id, i
                            ), cap=self._write_cap)
                        except Exception:
                            pass # Target proposition might not exist yet
                    except Exception as e:
                        logger.error(f"Speculative hypothesis insert failed: {e}")

        # 3. Persist Template Executions + Validation Evidence
        executions = context.graph_context.get("template_executions", [])
        for exec_rec in executions:
            # Handle both dict and object
            ex_data = exec_rec.model_dump() if hasattr(exec_rec, "model_dump") else exec_rec
            self.insert_to_graph(q_insert_execution(session_id, ex_data), cap=self._write_cap)

            # Persist validation-evidence for successful executions (optional Phase 12.1)
            # SKIPPING here - we now persist the full 'Evidence' objects below
            pass

        # 3b. Persist Full Evidence Objects (Phase 13)
        evidence_list = context.graph_context.get("evidence", [])
        _intent_id = context.graph_context.get("intent_id")
        print(f"DEBUG_STEWARD: Found {len(evidence_list)} evidence items. intent_id={_intent_id}")
        # Phase 16.4: Accumulators for governance outputs
        persisted_evidence_ids = []
        proposal_error = None
        latest_intent_id = None
        latest_proposal_id = None

        for ev in evidence_list:
            ev_data = ev.model_dump() if hasattr(ev, "model_dump") else (
                asdict(ev) if hasattr(ev, "__dataclass_fields__") else (
                    ev.__dict__ if hasattr(ev, "__dict__") else ev
                )
            )
            try:
                evidence_id = self._seal_evidence_dict_before_mint(session_id, ev_data, channel="positive")
                ev_data["evidence_id"] = evidence_id  # Phase 16.4 B2: expose for downstream citation
                self.insert_to_graph(q_insert_validation_evidence(session_id, ev_data, evidence_id=evidence_id, intent_id=_intent_id), cap=self._write_cap)
                persisted_evidence_ids.append(evidence_id)
            except Exception as e:
                logger.error(f"Evidence insert failed (id={ev_data.get('execution_id')}): {e}")
                raise

        # 3c. Persist Negative Evidence Objects (Phase 16.1)
        negative_evidence_list = context.graph_context.get("negative_evidence", [])
        for neg_ev in negative_evidence_list:
            neg_ev_data = neg_ev.model_dump() if hasattr(neg_ev, "model_dump") else (
                asdict(neg_ev) if hasattr(neg_ev, "__dataclass_fields__") else neg_ev
            )
            evidence_role = neg_ev_data.get("evidence_role") or neg_ev_data.get("evidence-role") or "refute"
            try:
                evidence_id = self._seal_evidence_dict_before_mint(
                    session_id, neg_ev_data, channel="negative"
                )
                neg_ev_data["evidence_id"] = evidence_id  # Phase 16.4 B2
                self.insert_to_graph(
                    q_insert_negative_evidence(
                        session_id,
                        neg_ev_data,
                        evidence_id=evidence_id,
                        evidence_role=evidence_role,
                    ),
                    cap=self._write_cap,
                )
                persisted_evidence_ids.append(evidence_id)
            except Exception as e:
                logger.error(
                    "Negative evidence insert failed: "
                    f"claim_id={neg_ev_data.get('claim_id') or neg_ev_data.get('claim-id') or neg_ev_data.get('proposition_id')}, "
                    f"execution_id={neg_ev_data.get('execution_id') or neg_ev_data.get('execution-id')}, "
                    f"template_qid={neg_ev_data.get('template_qid') or neg_ev_data.get('template-qid')}, "
                    f"role={evidence_role}. error={e}"
                )
                raise

        # 3d. Theory Change Operator (Phase 16.2) — proposal-only
        try:
            self._generate_and_stage_proposals(session_id)
        except Exception as e:
            logger.error(f"Phase 16.2 proposal generation failed (session={session_id}): {e}")
            proposal_error = str(e)  # Phase 16.4 B3: capture for governance gate

        # 4. Persist Epistemic Proposals
        proposals = context.graph_context.get("epistemic_update_proposal", [])
        for prop in proposals:
            self.insert_to_graph(q_insert_proposal(session_id, prop), cap=self._write_cap)

        # 5. Persist Write Intents (Staged)
        intents = context.graph_context.get("write_intents", [])
        for intent in intents:
             status = "staged"
             approved_list = context.graph_context.get("approved_write_intents", [])
             is_approved = any(a.get("intent_id") == intent.get("intent_id") for a in approved_list)
             if is_approved:
                 status = "approved"

             self.insert_to_graph(q_insert_write_intent(session_id, intent, status), cap=self._write_cap)

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
            ), cap=self._write_cap)

            if success:
                committed.append(intent)
            else:
                failed.append(intent)

        # 7. Finalize Session (ended-at + run-status transition)
        final_status = "failed" if failed else "complete"

        # Delete old ended-at first for idempotency
        if hasattr(self, 'db'):
            self.db.query_delete(q_delete_session_ended_at(session_id), cap=self._write_cap)
        else:
            from src.db.typedb_client import typedb
            typedb.query_delete(q_delete_session_ended_at(session_id), cap=self._write_cap)

        self.insert_to_graph(q_set_session_ended_at(session_id), cap=self._write_cap)

        if hasattr(self, 'db'):
            self.db.query_delete(q_delete_session_run_status(session_id), cap=self._write_cap)
            self.db.query_insert(q_insert_session_run_status(session_id, final_status), cap=self._write_cap)
        else:
            # Fallback for compilation context
            from src.db.typedb_client import typedb
            typedb.query_delete(q_delete_session_run_status(session_id), cap=self._write_cap)
            typedb.query_insert(q_insert_session_run_status(session_id, final_status), cap=self._write_cap)

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

        # Phase 16.4 B3: Expose stable governance outputs
        context.graph_context["persisted_all_evidence_ids"] = persisted_evidence_ids
        
        # P1 Bug Fix: Derive governance IDs from staged proposal intents if context is missing them
        # In v2.1, _generate_and_stage_proposals stages directly via service
        from src.hitl.intent_service import write_intent_service
        staged_proposals = write_intent_service.list_staged(intent_type="stage_epistemic_proposal")
        
        if not intents and staged_proposals:
             # Use the staged proposals as 'latest' for governance summary
             # P1 Bug Fix: handle dict return from service
             first_prop = staged_proposals[-1]
             latest_intent_id = first_prop.get("intent_id")
             latest_proposal_id = first_prop.get("payload", {}).get("proposal_id")
        else:
             latest_intent_id = intents[-1].get("intent_id") if intents else None
             latest_proposal_id = proposals[-1].get("proposal_id") if proposals else None

        context.graph_context["latest_staged_intent_id"] = latest_intent_id
        context.graph_context["latest_staged_proposal_id"] = latest_proposal_id
        context.graph_context["proposal_generation_error"] = proposal_error

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
                    self.db.query_delete(delete_q, cap=self._write_cap)
                    self.db.query_insert(insert_q, cap=self._write_cap)
                else:
                    # Fallback to global typedb instance if self.db not set (legacy)
                    from src.db.typedb_client import typedb
                    typedb.query_delete(delete_q, cap=self._write_cap)
                    typedb.query_insert(insert_q, cap=self._write_cap)

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

                from src.montecarlo.template_store import TypeDBTemplateStore
                store = TypeDBTemplateStore(driver)

            # 3. Ensure metadata exists (Lazy Sync)
            # This handles first-run bootstrap without explicit "init" step
            meta = store.get_metadata(template_id, version_str)
            if not meta:
                from src.montecarlo.template_metadata import (
                    TemplateMetadata,
                    TemplateStatus,
                    compute_code_hash,
                )

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



    def _seal_operator_before_mint(
        self,
        template_qid: str,
        evidence_id: str,
        claim_id: str,
        scope_lock_id: str,
    ) -> None:
        """
        Constitutional Seal Operator (Phase 14.5) — test-driven.

         Checks:
         - template_qid is qualified and matches QID_RE
         - metadata exists and is not corrupt
         - spec hash parity vs VERSIONED_REGISTRY.get_spec(qid)
         - code hash parity vs compute_code_hash_strict(VERSIONED_REGISTRY.get(qid))
         - freezes template on success (idempotent store call)
         """

        if not scope_lock_id:
            raise ValueError("Seal failed: missing scope_lock_id")
        if not claim_id:
            raise ValueError("Seal failed: missing claim_id")
        if not template_qid:
            raise ValueError("Seal failed: missing template_qid")

        qid = template_qid.strip()

        # QID format: must be fully qualified
        if (not qid) or ("@" not in qid) or (not QID_RE.match(qid)):
            raise ValueError("Invalid template_qid format for seal")

        template_id, version = qid.split("@", 1)
        template_id, version = template_id.strip(), version.strip()
        if not template_id or not version:
            raise ValueError("Invalid template_qid format for seal")
        store = getattr(self, "template_store", None)
        if store is None:
            raise ValueError("Seal failed: template_store not configured")

        # Fetch metadata
        meta = store.get_metadata(template_id, version)
        if meta is None:
            raise ValueError(f"Seal failed: missing metadata for {qid}")

        # Corrupt metadata (tests expect this exact phrase)
        if not getattr(meta, "spec_hash", None) or not getattr(meta, "code_hash", None):
            raise ValueError("Corrupt metadata")

        # --- Spec hash parity ---
        from src.montecarlo.versioned_registry import VERSIONED_REGISTRY

        spec = VERSIONED_REGISTRY.get_spec(qid)
        actual_spec_hash = spec.spec_hash()
        expected_spec_hash = meta.spec_hash
        if actual_spec_hash != expected_spec_hash:
            raise ValueError("Spec hash mismatch")

        # --- Code hash parity ---
        template_instance = VERSIONED_REGISTRY.get(qid)
        if template_instance is None:
        # tests match "Seal failed: Template instance .* not found"
            raise ValueError(f"Seal failed: Template instance {qid} not found")

        from src.montecarlo.template_metadata import compute_code_hash_strict

        actual_code_hash = compute_code_hash_strict(template_instance)
        expected_code_hash = meta.code_hash
        if actual_code_hash != expected_code_hash:
            raise ValueError("Code hash mismatch")
        # Freeze (tests assert called once)
        store.freeze(
            template_id=template_id,
            version=version,
            evidence_id=evidence_id,
            claim_id=claim_id,
            scope_lock_id=scope_lock_id,
            actor="system",
        )


    def _seal_evidence_dict_before_mint(
        self,
        session_id: str,
        ev: Dict[str, Any],
        *,
        channel: str = "positive",
    ) -> str:
        raw_exec = ev.get("execution_id") or ev.get("execution-id") or ev.get("codeact_execution_id")
        exec_id = str(raw_exec).strip() if raw_exec is not None else ""
        claim_id = (
            ev.get("claim_id")
            or ev.get("claim-id")
            or ev.get("proposition_id")
            or ev.get("hypothesis_id")
            or ""
        ).strip()
        template_qid = (ev.get("template_qid") or ev.get("template-qid") or "codeact-v1@1.0").strip()
        scope_lock_id = (ev.get("scope_lock_id") or ev.get("scope-lock-id") or "").strip()

        if channel == "negative":
            evidence_id = make_negative_evidence_id(session_id, claim_id, exec_id, template_qid)
        elif channel == "positive":
            evidence_id = make_evidence_id(session_id, claim_id, exec_id, template_qid)
        else:
            raise ValueError(f"Invalid evidence channel: {channel!r}")

        self._seal_operator_before_mint(template_qid, evidence_id, claim_id, scope_lock_id)
        return evidence_id

    # =========================================================================
    # Phase 16.2: Theory Change Proposal Helpers
    # =========================================================================

    def _fetch_session_evidence(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Fetch all evidence for a session from TypeDB in 2 queries (base + negative).
        
        Returns list of dicts with keys:
        - eid, cid, slid, conf, role (from DB variables)
        - fm, rs (for negative-evidence only)
        """
        # Query A: Base Evidence fields for ALL evidence
        query_base = f'''
        match
            $s isa run-session, has session-id "{escape(session_id)}";
            (session: $s, evidence: $e) isa session-has-evidence;
            {{
                $e isa! validation-evidence;
            }} or {{
                $e isa! negative-evidence;
            }};
            $e has entity-id $eid,
                has claim-id $cid,
                has scope-lock-id $slid,
                has confidence-score $conf;
            (evidence: $e, proposition: $p) isa evidence-for-proposition,
                has evidence-role $role;
            $p isa proposition, has entity-id $pid;
        get $eid, $cid, $slid, $conf, $role, $pid;
        '''

        try:
            base_rows = self._read_query(query_base)
        except Exception as e:
            logger.warning(f"Evidence fetch (base) failed (session={session_id}): {e}")
            return []

        # Query B: Negative Evidence specific fields (Bulk fetch)
        # We fetch only negative-evidence nodes that have these fields
        query_neg = f'''
        match
            $s isa run-session, has session-id "{escape(session_id)}";
            (session: $s, evidence: $e) isa session-has-evidence;
            $e isa negative-evidence, 
                has entity-id $eid,
                has failure-mode $fm,
                has refutation-strength $rs;
        get $eid, $fm, $rs;
        '''

        neg_map = {}
        try:
            neg_rows = self._read_query(query_neg)
            for r in neg_rows:
                if "eid" in r:
                    neg_map[r["eid"]] = r
        except Exception as e:
            logger.warning(f"Evidence fetch (negative) failed (session={session_id}): {e}")
            # Non-fatal: just implies no negative fields available

        # Merge negative fields into base rows
        enriched = []
        for row in base_rows:
            eid = row.get("eid")
            if eid and eid in neg_map:
                row["fm"] = neg_map[eid].get("fm")
                row["rs"] = neg_map[eid].get("rs")
            enriched.append(row)

        return enriched

    def _to_operator_tuples(
        self, ev_rows: List[Dict[str, Any]]
    ) -> List[tuple]:
        """
        Convert evidence rows to (ev_dict, EvidenceRole, channel) tuples.
        
        Channel inference: presence of fm/rs/failure-mode ⟹ negative
        """

        out = []
        for r in ev_rows:
            # Role from DB variable or legacy keys
            role_raw = r.get("role") or r.get("evidence-role") or r.get("evidence_role")
            try:
                role = validate_evidence_role(role_raw)
            except (ValueError, TypeError):
                logger.debug(f"Skipping evidence with invalid role: {role_raw}")
                continue
            if role is None:
                logger.debug(f"Skipping evidence with invalid role: {role_raw}")
                continue

            # Channel from subtype markers (fm/rs presence ⟹ negative)
            is_negative = bool(
                r.get("fm") or r.get("rs")
                or r.get("failure-mode") or r.get("failure_mode")
                or r.get("refutation-strength") or r.get("refutation_strength")
            )
            channel = "negative" if is_negative else "validation"

            out.append((r, role, channel))
        return out

    def _derive_scope_lock_id(self, evidence_list: List[Dict[str, Any]]) -> Optional[str]:
        """
        Derive scope-lock from evidence using deterministic rule.
        
        Rule: max confidence, tie-break on evidence entity-id ascending.
        """
        from src.epistemology.theory_change_operator import (
            get_confidence_value,
            get_evidence_entity_id,
        )

        def _extract_slid(ev):
            val = (
                ev.get("slid")
                or ev.get("scope_lock_id")
                or ev.get("scope-lock-id")
            )
            return str(val).strip() if val else ""

        scored = []
        for ev in evidence_list:
            slid = _extract_slid(ev)
            if not slid:
                continue
            evid = get_evidence_entity_id(ev)
            conf = get_confidence_value(ev)
            scored.append((conf, evid, slid))

        if not scored:
            return None

        # Sort: max confidence first, then lexicographic by evid (deterministic)
        scored.sort(key=lambda t: (-t[0], t[1]))
        return scored[0][2]

    def _generate_and_stage_proposals(self, session_id: str) -> None:
        """
        Fetch session evidence, generate proposals, and stage intents.
        
        Phase 16.3: Non-circular proposal generation with deterministic IDs.
        """
        from src.epistemology.theory_change_operator import (
            TheoryAction,
            compute_theory_change_action,
            generate_proposal,
            get_claim_id,
            get_evidence_entity_id,
        )
        from src.governance.fingerprinting import make_policy_hash, make_proposal_id
        from src.hitl.intent_service import write_intent_service

        # 1. Fetch evidence
        session_evidence = self._fetch_session_evidence(session_id)
        if not session_evidence:
            logger.debug(f"No evidence to process for session {session_id}")
            return

        # 2. Group by claim
        by_claim: Dict[str, List[Dict[str, Any]]] = {}
        for ev in session_evidence:
            cid = get_claim_id(ev)
            if not cid:
                continue
            by_claim.setdefault(cid, []).append(ev)

        # 3. Compute policy hash once per batch
        policy_hash = make_policy_hash()

        # 4. Generate and stage proposals (non-circular)
        staged_count = 0
        for claim_id, ev_list in by_claim.items():
            tuples = self._to_operator_tuples(ev_list)
            if not tuples:
                continue

            # Step 1: Compute action FIRST (no proposal yet)
            action, metadata = compute_theory_change_action(claim_id, tuples)

            # Skip HOLD actions (insufficient evidence)
            if action == TheoryAction.HOLD:
                logger.debug(f"Skipping HOLD proposal for claim {claim_id}")
                continue

            # Step 2: Evidence fingerprint (includes role+channel)
            evidence_fps = sorted(
                f"{get_evidence_entity_id(ev)}:{role.value}:{channel}"
                for ev, role, channel in tuples
            )

            # Filter missing IDs → HOLD (fail safe)
            if any(fp.startswith("unknown:") or ":unknown:" in fp for fp in evidence_fps):
                logger.warning(f"Skipping proposal for {claim_id} due to missing evidence IDs")
                continue

            # Step 3: Deterministic proposal_id
            proposal_id = make_proposal_id(
                session_id, claim_id, action.value, evidence_fps, policy_hash
            )

            # Step 4: Build proposal (no recompute)
            proposal = generate_proposal(
                claim_id, tuples,
                proposal_id=proposal_id,
                precomputed=(action, metadata),
            )

            # Derive scope-lock deterministically
            scope_lock_id = self._derive_scope_lock_id(ev_list)

            # Stage proposal intent
            try:
                write_intent_service.stage(
                    intent_type="stage_epistemic_proposal",
                    payload=proposal.to_intent_payload(),
                    lane="grounded",
                    scope_lock_id=scope_lock_id,
                    impact_score=proposal.conflict_score,
                    proposal_id=proposal_id,
                )
                staged_count += 1
            except Exception as e:
                logger.error(f"Failed to stage proposal for claim {claim_id}: {e}")

        logger.info(f"Phase 16.3: Staged {staged_count} proposal(s) for session {session_id}")

    def _read_query(self, query: str) -> List[Dict]:
        """Alias for query_graph (used by evidence fetcher)."""
        return self.query_graph(query)

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

def q_insert_validation_evidence(session_id: str, ev: dict, evidence_id: Optional[str] = None, intent_id: Optional[str] = None) -> str:
    # ------------------------------------------------------------------
    # Constitutional Gate (Phase 14.5)
    # ------------------------------------------------------------------
    raw_exec = ev.get("execution_id") or ev.get("execution-id") or ev.get("codeact_execution_id")
    exec_id = str(raw_exec).strip() if raw_exec is not None else ""

    # 1. Extract IDs first (needed for error messages)
    claim_id = (ev.get("claim_id") or ev.get("claim-id") or ev.get("proposition_id") or ev.get("hypothesis_id") or "").strip()
    template_qid = (ev.get("template_qid") or ev.get("template-qid") or "").strip()
    template_id = (ev.get("template_id") or ev.get("template-id") or "").strip()
    scope_lock_id = (ev.get("scope_lock_id") or ev.get("scope-lock-id") or "").strip()

    # 2. Claim ID is REQUIRED (must check before other guards)
    if not claim_id:
        raise ValueError(f"CRITICAL: Validation evidence missing claim_id! (exec_id={exec_id})")

    # 2b. Seal parity invariants (function-boundary safety)
    if not scope_lock_id:
        raise ValueError(f"CRITICAL: Validation evidence missing scope_lock_id! (exec_id={exec_id})")
    if not template_qid:
        raise ValueError(f"CRITICAL: Validation evidence missing template_qid! (exec_id={exec_id})")

    # ------------------------------------------------------------------
    # 3. Speculative Guard (Phase 11) - Must run before success-only
    # ------------------------------------------------------------------
    spec_keys = {"epistemic_status", "epistemic-status"}
    spec_context_keys = {"speculative_context", "speculative-context"}

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
            for k in spec_keys:
                if obj.get(k) == "speculative":
                    return True
            if any(k in obj for k in spec_context_keys):
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

    # 5. Policy Check: We now allow failed evidence for auditability (Phase 16.5).
    # The success value is correctly captured in the TypeQL 'has success' attribute.
    pass

    # 6. Derive template_id from QID if missing
    if not template_id and template_qid and "@" in template_qid:
        template_id = template_qid.split("@", 1)[0]

    # ------------------------------------------------------------------
    # Build Query
    # ------------------------------------------------------------------
    conf_raw = ev.get("confidence_score", ev.get("confidence", 0.0)) or 0.0
    conf = clamp_probability(conf_raw, "confidence_score")

    # Prune excluded keys for JSON payload
    exclude = {
        "claim_id", "claim-id", "proposition_id",
        "execution_id", "template_id", "template_qid", "scope_lock_id",
        "success", "confidence_score", "confidence", "content", "json"
    }
    base_json = ev.get("json") if isinstance(ev.get("json"), dict) else {}
    extra_fields = {k: v for k, v in ev.items() if k not in exclude}
    payload = {**base_json, **extra_fields}

    if not evidence_id:
        evidence_id = make_evidence_id(session_id, claim_id, exec_id, template_qid)

    intent_clause = f',\n        has authorized-by-intent-id "{escape(intent_id)}"' if intent_id else ''

    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}";
    match $p isa proposition, has entity-id "{escape(claim_id)}";
    insert
    $v isa validation-evidence,
        has entity-id "{escape(evidence_id)}",
        has claim-id "{escape(claim_id)}",
        has execution-id "{escape(exec_id)}",
        has template-qid "{escape(template_qid)}",
        has template-id "{escape(template_id)}",
        has scope-lock-id "{escape(scope_lock_id)}",
        has success {str(success).lower()},
        has confidence-score {conf},
        has json "{escape(json.dumps(payload, sort_keys=True))}"{intent_clause},
        has created-at {iso_now()};
    (session: $s, evidence: $v) isa session-has-evidence;
    (evidence: $v, proposition: $p) isa evidence-for-proposition,
        has evidence-role "support";
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
# Note: make_evidence_id and make_negative_evidence_id are now imported from src.governance.fingerprinting


def q_insert_negative_evidence(
    session_id: str,
    ev: dict,
    evidence_id: Optional[str] = None,
    evidence_role: str = "refute",
) -> str:
    """
    Build TypeQL query to insert negative evidence (Phase 16.1).
    
    Negative evidence represents failed validations, refutations,
    or methodological failures. Uses the same fingerprint protocol
    as validation-evidence but with a different prefix (nev-).
    
    CRITICAL SEMANTICS:
    - success=true means "execution succeeded" (template ran validly)
    - evidence-role="refute" means "claim was refuted"
    - This preserves backward compatibility with success-only filters
    
    Phase 16.2 safeguards:
    - negative-evidence cannot have role=support (channel discipline)
    - replicate role IS allowed (represents replication failure/null effect)
    - numeric fields are clamped to [0,1] and checked for NaN/inf
    - role validation is strict (typos raise errors immediately)
    """
    # Extract required fields
    claim_id = (ev.get("claim_id") or ev.get("claim-id") or ev.get("proposition_id") or ev.get("hypothesis_id") or "").strip()
    raw_exec = ev.get("execution_id") or ev.get("execution-id") or ev.get("codeact_execution_id")
    exec_id = str(raw_exec).strip() if raw_exec is not None else ""
    template_qid = (ev.get("template_qid") or ev.get("template-qid") or "codeact-v1@1.0").strip()
    template_id = (ev.get("template_id") or ev.get("template-id") or "").strip()
    scope_lock_id = (ev.get("scope_lock_id") or ev.get("scope-lock-id") or "").strip()

    # Validate claim_id (same invariant as positive evidence)
    if not claim_id:
        raise ValueError(f"CRITICAL: Negative evidence missing claim_id! (exec_id={exec_id})")

    # Validate and normalize evidence role (Phase 16.2: strict mode)
    role_enum = require_evidence_role(evidence_role, default=EvidenceRole.REFUTE, strict=True)

    # Phase 16.2: Prevent channel misuse
    # SUPPORT is forbidden (use validation-evidence instead)
    # REFUTE, UNDERCUT, REPLICATE are allowed
    if role_enum == EvidenceRole.SUPPORT:
        raise ValueError(
            f"CRITICAL: negative-evidence cannot have role='support'. "
            f"Use validation-evidence for supporting evidence. (exec_id={exec_id})"
        )

    role_value = role_enum.value

    # Validate and normalize failure mode
    failure_mode_raw = ev.get("failure_mode") or ev.get("failure-mode")
    if role_enum == EvidenceRole.REPLICATE and not failure_mode_raw:
        logger.warning(
            f"replicate negative-evidence missing failure-mode; defaulting to null_effect "
            f"(exec_id={exec_id}, claim_id={claim_id})"
        )
    failure_mode_raw = failure_mode_raw or "null_effect"
    failure_mode_enum = validate_failure_mode(failure_mode_raw) or FailureMode.NULL_EFFECT
    failure_mode_value = failure_mode_enum.value

    # Phase 16.2: Clamp numeric fields to [0,1]
    refutation_strength_raw = float(ev.get("refutation_strength") or ev.get("refutation-strength") or 0.5)
    refutation_strength = clamp_probability(refutation_strength_raw, "refutation_strength")

    conf_raw = float(ev.get("confidence_score") or ev.get("confidence-score") or 0.5)
    conf = clamp_probability(conf_raw, "confidence_score")

    # Generate deterministic ID if not provided
    if not evidence_id:
        evidence_id = make_negative_evidence_id(session_id, claim_id, exec_id, template_qid)

    # Prune excluded keys for JSON payload (same as validation-evidence)
    exclude = {
        "claim_id", "claim-id", "proposition_id",
        "execution_id", "template_id", "template_qid", "scope_lock_id",
        "success", "confidence_score", "confidence", "failure_mode", "failure-mode",
        "refutation_strength", "refutation-strength", "json"
    }
    base_json = ev.get("json") if isinstance(ev.get("json"), dict) else {}
    extra_fields = {k: v for k, v in ev.items() if k not in exclude}
    payload = {**base_json, **extra_fields}

    return f'''
    match $s isa run-session, has session-id "{escape(session_id)}";
    match $p isa proposition, has entity-id "{escape(claim_id)}";
    insert
    $v isa negative-evidence,
        has entity-id "{escape(evidence_id)}",
        has claim-id "{escape(claim_id)}",
        has execution-id "{escape(exec_id)}",
        has template-qid "{escape(template_qid)}",
        has template-id "{escape(template_id)}",
        has scope-lock-id "{escape(scope_lock_id)}",
        has success true,
        has failure-mode "{escape(failure_mode_value)}",
        has refutation-strength {refutation_strength},
        has confidence-score {conf},
        has json "{escape(json.dumps(payload, sort_keys=True))}",
        has created-at {iso_now()};
    (session: $s, evidence: $v) isa session-has-evidence;
    (evidence: $v, proposition: $p) isa evidence-for-proposition,
        has evidence-role "{escape(role_value)}";

    '''


# Global instance
ontology_steward = OntologySteward()

