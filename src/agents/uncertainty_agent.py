"""
Uncertainty Agent

v2.1 Step 10: Assigns scientific uncertainty, flags unknowns, highlights risks.
Uses the scientific uncertainty formula, NOT rhetorical disagreement.
"""

import logging

from src.agents.base_agent import AgentContext, BaseAgent
from src.epistemic.uncertainty import (
    uncertainty_from_codeact_result,
)
from src.graph.state import ScientificUncertainty

logger = logging.getLogger(__name__)


class UncertaintyAgent(BaseAgent):
    """
    Step 10: Computes scientific uncertainty from evidence.
    
    This is NOT rhetorical entropy (LLM disagreement).
    This is empirical uncertainty from experiments:
        - Variance of results
        - Sensitivity to assumptions
        - Sample size
        - Model fit error
    """

    def __init__(self):
        super().__init__(name="UncertaintyAgent")

    async def run(self, context: AgentContext) -> AgentContext:
        """Compute uncertainty for all claims with evidence."""
        claims = context.graph_context.get("atomic_claims", [])
        evidence = context.graph_context.get("evidence", [])

        uncertainty_results = {}
        flagged_unknowns = []
        high_risk_items = []

        for claim in claims:
            claim_id = claim.get("claim_id", "unknown")

            # Get evidence for this claim
            claim_evidence = [
                e for e in evidence
                if e.get("hypothesis_id") == claim_id
            ]

            if not claim_evidence:
                uncertainty_results[claim_id] = {
                    "total": 1.0,  # Maximum uncertainty
                    "components": {
                        "variance": 1.0,
                        "sensitivity": 1.0,
                        "sample_size": 0,
                        "model_fit_error": 0.0,
                    },
                    "has_evidence": False,
                }
                flagged_unknowns.append(claim_id)
                continue

            # Compute uncertainty from evidence
            result_values = []
            for e in claim_evidence:
                result = e.get("result", {})
                if isinstance(result, dict) and "mean" in result:
                    result_values.append(result["mean"])

            if result_values:
                components = uncertainty_from_codeact_result(result_values)
                total = components.total()
            else:
                components = ScientificUncertainty(variance=0.5, sample_size=1)
                total = components.total()

            uncertainty_results[claim_id] = {
                "total": total,
                "components": {
                    "variance": components.variance,
                    "sensitivity": components.sensitivity,
                    "sample_size": components.sample_size,
                    "model_fit_error": components.model_fit_error,
                },
                "has_evidence": True,
            }

            # Flag high-risk items
            if total > 0.5:
                high_risk_items.append({
                    "claim_id": claim_id,
                    "uncertainty": total,
                    "reason": "High uncertainty - needs more experiments",
                })

        # Store in context
        context.graph_context["uncertainty"] = uncertainty_results
        context.graph_context["flagged_unknowns"] = flagged_unknowns
        context.graph_context["high_risk_items"] = high_risk_items

        logger.info(
            f"Computed uncertainty for {len(claims)} claims. "
            f"Unknowns: {len(flagged_unknowns)}, High-risk: {len(high_risk_items)}"
        )

        return context


# Global instance
uncertainty_agent = UncertaintyAgent()
