"""
Integrator Agent

v2.1 Step 12: Synthesizes dual outputs (grounded + speculative).
The final synthesis agent before ontology updates.
"""

import logging
from typing import Any, Dict, List

from src.agents.base_agent import AgentContext, BaseAgent

logger = logging.getLogger(__name__)


class IntegratorAgent(BaseAgent):
    """
    Step 12: Synthesizes final answer with dual outputs.
    
    Produces:
        A. Grounded Answer - what is currently justified
        B. Speculative Alternatives - hypotheses worth exploring
    
    This is the final synthesis before ontology updates.
    """

    def __init__(self):
        super().__init__(name="IntegratorAgent")

    async def run(self, context: AgentContext) -> AgentContext:
        """Synthesize dual outputs from grounded and speculative lanes."""

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
