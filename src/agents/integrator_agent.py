"""
Integrator Agent

v2.1 Step 12: Synthesizes dual outputs (grounded + speculative).
The final synthesis agent before ontology updates.

Phase 16.5: Adds ledger primacy verification (_verify_evidence_primacy)
to prove cited evidence IDs actually exist in TypeDB and match
session/scope/claim before synthesis is allowed.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from src.agents.base_agent import AgentContext, BaseAgent

logger = logging.getLogger(__name__)

# Maximum evidence IDs per OR-disjunction query before chunking.
_OR_DISJUNCTION_THRESHOLD = 50


class IntegratorAgent(BaseAgent):
    """
    Step 12: Synthesizes final answer with dual outputs.

    Produces:
        A. Grounded Answer - what is currently justified
        B. Speculative Alternatives - hypotheses worth exploring

    This is the final synthesis before ontology updates.

    Phase 16.5: Also performs ledger primacy verification before synthesis.
    """

    def __init__(self):
        super().__init__(name="IntegratorAgent")

    async def run(self, context: AgentContext) -> AgentContext:
        """Synthesize dual outputs from grounded and speculative lanes."""
        session_id = context.graph_context.get("session_id")
        governance = context.graph_context.get("governance", {})
        evidence_ids = governance.get("persisted_evidence_ids", [])
        expected_scope = context.graph_context.get("expected_scope_lock_id")
        
        # Determine expected claims for primacy check
        expected_claims = set()
        for claim in context.graph_context.get("atomic_claims", []):
            if claim.get("claim_id"):
                expected_claims.add(claim.get("claim_id"))

        # Phase 16.5: Ledger Primacy Verification
        if evidence_ids and session_id:
            passed, hold_code, details = self._verify_evidence_primacy(
                session_id=session_id,
                evidence_ids=evidence_ids,
                expected_scope_lock_id=expected_scope,
                expected_claim_ids=expected_claims
            )
            
            if not passed:
                logger.warning(f"Integrator: Primacy verification FAILED ({hold_code}): {details}")
                context.response = f"HOLD: {details.get('hold_reason', 'Evidence primacy failure')}"
                if "grounded_response" not in context.graph_context:
                    context.graph_context["grounded_response"] = {"status": "HOLD", "reason": hold_code}
                else:
                    context.graph_context["grounded_response"]["status"] = "HOLD"
                return context

        # Synthesize grounded answer
        grounded_answer = self._synthesize_grounded(context)

        # Synthesize speculative alternatives
        speculative_alternatives = self._synthesize_speculative(context)

        # Store in context
        context.graph_context["grounded_response"] = grounded_answer
        context.graph_context["speculative_alternatives"] = speculative_alternatives

        # Also set the final response
        context.response = self._format_final_response(
            grounded_answer,
            speculative_alternatives,
            context
        )

        logger.info("Synthesized dual outputs")

        return context

    # =========================================================================
    # Phase 16.5: Ledger Primacy Verification
    # =========================================================================

    def _verify_evidence_primacy(
        self,
        session_id: str,
        evidence_ids: List[str],
        expected_scope_lock_id: Optional[str] = None,
        expected_claim_ids: Optional[Set[str]] = None,
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Verify evidence IDs against the TypeDB ledger (hard proof).

        Checks:
          1. Existence — all evidence_ids are persisted in ledger
          2. Session ownership — evidence belongs to this session (via session-has-evidence)
          3. Scope coherence — all evidence has matching scope-lock-id
          4. Claim alignment — evidence claim-ids are within expected set

        Uses OR-disjunction for TypeQL queries (TypeDB 3.x compatible).
        For large evidence sets (>50), chunks queries to avoid oversized TypeQL.

        Returns:
            (passed, hold_code, details) where:
            - passed: True if all checks pass
            - hold_code: machine-parsable code if failed, None if passed
            - details: dict with diagnostics (missing IDs, mismatched scopes, etc.)
        """
        if not evidence_ids:
            return False, "EVIDENCE_MISSING_FROM_LEDGER", {"reason": "No evidence IDs to verify"}

        if not session_id:
            return False, "EVIDENCE_MISSING_FROM_LEDGER", {"reason": "No session_id provided"}

<<<<<<< HEAD
        # Phase 16.5: Mock mode bypass (for showcase/CI without TypeDB)
        from src.db.typedb_client import typedb
        if getattr(typedb, "_mock_mode", False):
            logger.debug("Integrator: [MOCK] Skipping primacy check (ledger unavailable)")
            return True, None, {"mock": True}

=======
>>>>>>> origin/main
        # Deduplicate input while preserving diagnostics
        input_set = set(evidence_ids)

        # Fetch evidence rows from ledger in chunks
        all_rows: List[Dict[str, Any]] = []
        id_list = sorted(input_set)

        for chunk_start in range(0, len(id_list), _OR_DISJUNCTION_THRESHOLD):
            chunk = id_list[chunk_start : chunk_start + _OR_DISJUNCTION_THRESHOLD]
            rows = self._fetch_evidence_by_ids(session_id, chunk)
            all_rows.extend(rows)

        # Build result set from returned rows
        returned_ids: Set[str] = set()
        returned_scopes: Dict[str, str] = {}  # evidence_id → scope
        returned_claims: Dict[str, str] = {}  # evidence_id → claim

        for row in all_rows:
            eid = row.get("id") or row.get("eid")
            if eid:
                returned_ids.add(eid)
                scope = row.get("scope") or row.get("slid")
                claim = row.get("claim") or row.get("cid")
                if scope:
                    returned_scopes[eid] = str(scope)
                if claim:
                    returned_claims[eid] = str(claim)

        # ── Check 1: Completeness ──
        missing = input_set - returned_ids
        if missing:
            return False, "EVIDENCE_MISSING_FROM_LEDGER", {
                "hold_reason": f"{len(missing)} evidence ID(s) not found in ledger for session {session_id}",
                "missing": sorted(missing),
                "expected_count": len(input_set),
                "returned_count": len(returned_ids),
            }

        # ── Check 2: Session ownership ──
        # Already enforced by the match clause (session-has-evidence join).
        # If an ID is in `missing`, it failed session ownership.

        # ── Check 3: Scope coherence ──
        if expected_scope_lock_id:
            mismatched_scopes = {
                eid: scope
                for eid, scope in returned_scopes.items()
                if scope != expected_scope_lock_id
            }
            if mismatched_scopes:
                return False, "EVIDENCE_SCOPE_MISMATCH", {
                    "hold_reason": f"{len(mismatched_scopes)} evidence ID(s) have wrong scope-lock-id",
                    "expected_scope": expected_scope_lock_id,
                    "mismatched": mismatched_scopes,
                }

        # ── Check 4: Claim alignment ──
        if expected_claim_ids:
            mismatched_claims = {
                eid: claim
                for eid, claim in returned_claims.items()
                if claim not in expected_claim_ids
            }
            if mismatched_claims:
                return False, "EVIDENCE_CLAIM_MISMATCH", {
                    "hold_reason": f"{len(mismatched_claims)} evidence ID(s) cite unexpected claims",
                    "expected_claims": sorted(expected_claim_ids),
                    "mismatched": mismatched_claims,
                }

        # All checks passed
        return True, None, {
            "verified_count": len(returned_ids),
            "session_id": session_id,
        }

    def _fetch_evidence_by_ids(
        self,
        session_id: str,
        evidence_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Fetch evidence rows from TypeDB using OR-disjunction.

        Returns list of dicts with keys: id, claim, scope.
        """
        if not evidence_ids:
            return []

        # Escape function (same as ontology_steward)
        def _esc(s: str) -> str:
            return (str(s) or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")

        # Build OR-disjunction clauses
        or_clauses = " or ".join(
            f'{{ $id == "{_esc(eid)}"; }}'
            for eid in evidence_ids
        )

        query = f'''
        match
            $s isa run-session, has session-id "{_esc(session_id)}";
            (session: $s, evidence: $ev) isa session-has-evidence;
            $ev isa evidence,
                has entity-id $id,
                has claim-id $claim,
                has scope-lock-id $scope;
            {or_clauses};
        get $id, $claim, $scope;
        '''

        try:
            return self.query_graph(query)
        except Exception as e:
            logger.error(f"Primacy TypeQL query failed (session={session_id}): {e}")
            return []

    # =========================================================================
    # Synthesis methods
    # =========================================================================

    def _synthesize_grounded(self, context: AgentContext) -> Dict[str, Any]:
        """Synthesize the grounded answer from evidence."""
        claims = context.graph_context.get("atomic_claims", [])
        evidence = context.graph_context.get("evidence", [])
        uncertainty = context.graph_context.get("uncertainty", {})
        classifications = context.graph_context.get("classifications", [])
        governance = context.graph_context.get("governance", {})

        grounded_claims = []

        for claim in claims:
            claim_id = claim.get("claim_id", "unknown")

            # Phase 16.4 C1: Match evidence by claim_id OR hypothesis_id
            claim_evidence = [
                e for e in evidence
                if (e.get("claim_id") == claim_id or e.get("hypothesis_id") == claim_id)
                and e.get("success", False)
            ]

            # Get uncertainty
            claim_uncertainty = uncertainty.get(claim_id, {})

            # Get classification
            claim_class = next(
                (c for c in classifications if c.get("claim_id") == claim_id),
                {}
            )

            # Only include claims with evidence
            if claim_evidence:
                # Phase 16.4 C1: Per-claim evidence IDs (minted by steward B2)
                claim_evidence_ids = [
                    e.get("evidence_id") for e in claim_evidence
                    if e.get("evidence_id")
                ]
                grounded_claims.append({
                    "claim_id": claim_id,
                    "content": claim.get("content", ""),
                    "status": claim_class.get("status", "speculative"),
                    "confidence": 1.0 - claim_uncertainty.get("total", 0.5),
                    "evidence_count": len(claim_evidence),
                    "evidence_ids": claim_evidence_ids,
                })

        return {
            "claims": grounded_claims,
            "summary": self._generate_grounded_summary(grounded_claims),
            "confidence_level": self._compute_overall_confidence(grounded_claims),
            "known_limits": self._identify_limits(context),
            # Phase 16.4 C1: Top-level governance citations
            "governance": {
                "cited_intent_id": governance.get("intent_id"),
                "cited_proposal_id": governance.get("proposal_id"),
                "persisted_evidence_ids": governance.get("persisted_evidence_ids", []),
            },
        }

    def _synthesize_speculative(self, context: AgentContext) -> List[Dict[str, Any]]:
        """Synthesize speculative alternatives."""
        speculative = context.graph_context.get("speculative_context", {})

        alternatives = []

        for claim_id, spec in speculative.items():
            for alt in spec.get("alternatives", []):
                alternatives.append({
                    "related_claim": claim_id,
                    "hypothesis": alt.get("hypothesis", ""),
                    "mechanism": alt.get("mechanism", ""),
                    "testable_prediction": alt.get("testable_prediction", ""),
                    "why_explore": "Alternative mechanism worth testing",
                    "why_might_be_wrong": "Speculative - no evidence yet",
                })

        return alternatives

    def _generate_grounded_summary(self, claims: List[Dict]) -> str:
        """Generate a summary of grounded findings."""
        if not claims:
            return "No claims have sufficient evidence for grounded conclusions."

        proven = [c for c in claims if c.get("status") == "proven"]
        supported = [c for c in claims if c.get("status") == "supported"]

        parts = []

        if proven:
            parts.append(f"{len(proven)} claim(s) are PROVEN with high confidence.")
        if supported:
            parts.append(f"{len(supported)} claim(s) are SUPPORTED pending replication.")

        return " ".join(parts) if parts else "Findings are preliminary."

    def _compute_overall_confidence(self, claims: List[Dict]) -> float:
        """Compute overall confidence level."""
        if not claims:
            return 0.0

        confidences = [c.get("confidence", 0.5) for c in claims]
        return sum(confidences) / len(confidences)

    def _identify_limits(self, context: AgentContext) -> List[str]:
        """Identify known limits of the analysis."""
        limits = []

        meta = context.graph_context.get("meta_critique", {})

        for issue in meta.get("issues", []):
            if issue.get("severity") in ("high", "critical"):
                limits.append(issue.get("description", "Unknown limitation"))

        unknowns = context.graph_context.get("flagged_unknowns", [])
        if unknowns:
            limits.append(f"{len(unknowns)} claims lack evidence")

        return limits

    def _format_final_response(
        self,
        grounded: Dict,
        speculative: List[Dict],
        context: AgentContext
    ) -> str:
        """Format the final dual-output response."""
        parts = []

        # Grounded section
        parts.append("## GROUNDED ANSWER")
        parts.append(grounded.get("summary", ""))
        parts.append(f"Overall confidence: {grounded.get('confidence_level', 0):.0%}")

        if grounded.get("known_limits"):
            parts.append("\n**Known Limits:**")
            for limit in grounded["known_limits"]:
                parts.append(f"- {limit}")

        # Speculative section
        if speculative:
            parts.append("\n## SPECULATIVE ALTERNATIVES")
            parts.append("*These are hypotheses worth exploring, not conclusions.*")

            for alt in speculative[:3]:  # Limit to top 3
                parts.append(f"\n- **{alt.get('hypothesis', 'Unknown')}**")
                parts.append(f"  Mechanism: {alt.get('mechanism', 'Unknown')}")

        return "\n".join(parts)


# Global instance
integrator_agent = IntegratorAgent()
