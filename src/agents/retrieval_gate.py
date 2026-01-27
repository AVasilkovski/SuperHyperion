"""
Retrieval Quality Gate (v2.2)

Gates retrieval quality before proceeding to speculation.
Routes back to ground if coverage/provenance insufficient.
"""

from typing import Dict, Any
import logging

from src.agents.base_agent import BaseAgent, AgentContext

logger = logging.getLogger(__name__)


class RetrievalQualityGate(BaseAgent):
    """
    v2.2: Gates retrieval quality before speculation.
    
    Computes:
        - coverage: How much of the claim is addressed by evidence
        - provenance: Are sources cited and trustworthy
        - conflict_density: Proportion of conflicting evidence
        
    Routes:
        - "speculate" if quality sufficient
        - "reground" if quality insufficient (loops back to ground)
    """
    
    # Thresholds
    COVERAGE_THRESHOLD = 0.70
    PROVENANCE_THRESHOLD = 0.85
    CONFLICT_DENSITY_MAX = 0.60
    MAX_REGROUND_ATTEMPTS = 3
    
    def __init__(self):
        super().__init__(name="RetrievalQualityGate")
    
    async def run(self, context: AgentContext) -> AgentContext:
        """Evaluate retrieval quality and set routing decision."""
        
        grounded_context = context.graph_context.get("grounded_context", {})
        evidence_bundle = grounded_context.get("evidence", [])
        claims = context.graph_context.get("atomic_claims", [])
        
        # Compute quality metrics
        coverage = self._compute_coverage(claims, evidence_bundle)
        provenance = self._compute_provenance(evidence_bundle)
        conflict_density = self._compute_conflict_density(evidence_bundle)
        
        # Store grade
        context.graph_context["retrieval_grade"] = {
            "coverage": coverage,
            "provenance": provenance,
            "conflict_density": conflict_density,
        }
        
        # Determine decision
        decision = self._decide(coverage, provenance, conflict_density)
        
        # Enforce loop cap
        attempts = context.graph_context.get("reground_attempts", 0)
        
        if decision == "reground":
            if attempts >= self.MAX_REGROUND_ATTEMPTS:
                logger.warning(f"Retrieval loop cap reached ({attempts}). Forcing speculation.")
                decision = "speculate"
                context.graph_context["retrieval_loop_capped"] = True
            else:
                attempts += 1
                
        context.graph_context["reground_attempts"] = attempts
        context.graph_context["retrieval_decision"] = decision
        
        # If reground, set refinement hints
        if decision == "reground":
            context.graph_context["retrieval_refinement"] = {
                "reason": self._get_refinement_reason(coverage, provenance, conflict_density),
                "suggested_action": "broaden_query" if coverage < self.COVERAGE_THRESHOLD else "filter_conflicts",
            }
        
        logger.info(
            f"Retrieval gate: coverage={coverage:.2f}, provenance={provenance:.2f}, "
            f"conflict={conflict_density:.2f} → {decision}"
        )
        
        return context
    
    def _compute_coverage(
        self,
        claims: list,
        evidence_bundle: list,
    ) -> float:
        """Compute what proportion of claims have evidence."""
        if not claims:
            return 1.0
        
        claim_ids = {c.get("claim_id", str(i)) for i, c in enumerate(claims)}
        covered_ids = set()
        
        for ev in evidence_bundle:
            claim_id = ev.get("claim_id") or ev.get("hypothesis_id")
            if claim_id in claim_ids:
                covered_ids.add(claim_id)
        
        return len(covered_ids) / len(claim_ids)
    
    def _compute_provenance(self, evidence_bundle: list) -> float:
        """Compute what proportion of evidence has proper citations."""
        if not evidence_bundle:
            return 1.0
        
        cited = sum(
            1 for ev in evidence_bundle
            if ev.get("source") or ev.get("source_id") or ev.get("citation")
        )
        
        return cited / len(evidence_bundle)
    
    def _compute_conflict_density(self, evidence_bundle: list) -> float:
        """Compute proportion of evidence that conflicts."""
        if len(evidence_bundle) < 2:
            return 0.0
        
        # Simple: count how many pieces support vs refute
        supporting = sum(1 for ev in evidence_bundle if ev.get("supports", True))
        refuting = len(evidence_bundle) - supporting
        
        minority = min(supporting, refuting)
        return minority / len(evidence_bundle)
    
    def _decide(
        self,
        coverage: float,
        provenance: float,
        conflict_density: float,
    ) -> str:
        """Decide whether to proceed or reground."""
        if coverage < self.COVERAGE_THRESHOLD:
            return "reground"
        if provenance < self.PROVENANCE_THRESHOLD:
            return "reground"
        if conflict_density > self.CONFLICT_DENSITY_MAX:
            return "reground"
        return "speculate"
    
    def _get_refinement_reason(
        self,
        coverage: float,
        provenance: float,
        conflict_density: float,
    ) -> str:
        """Get human-readable reason for reground."""
        reasons = []
        if coverage < self.COVERAGE_THRESHOLD:
            reasons.append(f"Low coverage ({coverage:.0%} < {self.COVERAGE_THRESHOLD:.0%})")
        if provenance < self.PROVENANCE_THRESHOLD:
            reasons.append(f"Poor provenance ({provenance:.0%} < {self.PROVENANCE_THRESHOLD:.0%})")
        if conflict_density > self.CONFLICT_DENSITY_MAX:
            reasons.append(f"High conflicts ({conflict_density:.0%} > {self.CONFLICT_DENSITY_MAX:.0%})")
        return "; ".join(reasons)


# Global instance
retrieval_gate = RetrievalQualityGate()


def route_retrieval_gate(state: Dict[str, Any]) -> str:
    """Router function for LangGraph conditional edge."""
    decision = state.get("graph_context", {}).get("retrieval_decision", "speculate")
    
    # Also check directly on state
    if "retrieval_decision" in state:
        decision = state["retrieval_decision"]
    
    return decision
