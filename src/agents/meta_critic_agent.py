"""
Meta-Critic Agent

v2.1 Step 11: Detects systemic bias and failure modes in the reasoning process.
Operates at the meta-level, auditing the entire pipeline.
"""

import logging
from typing import Dict, List

from src.agents.base_agent import AgentContext, BaseAgent

logger = logging.getLogger(__name__)


class MetaCriticAgent(BaseAgent):
    """
    Step 11: Audits the entire reasoning process for systemic issues.

    Checks for:
        - Confirmation bias (only supporting evidence retrieved)
        - Mode collapse (all hypotheses converging prematurely)
        - Data sparsity (insufficient evidence for confidence)
        - Circular reasoning (evidence cites claim)
        - Source concentration (over-reliance on single source)
    """

    def __init__(self):
        super().__init__(name="MetaCriticAgent")

    async def run(self, context: AgentContext) -> AgentContext:
        """Audit the reasoning process for systemic issues."""
        issues = []

        # Check for confirmation bias
        bias_issues = self._check_confirmation_bias(context)
        issues.extend(bias_issues)

        # Check for mode collapse
        collapse_issues = self._check_mode_collapse(context)
        issues.extend(collapse_issues)

        # Check for data sparsity
        sparsity_issues = self._check_data_sparsity(context)
        issues.extend(sparsity_issues)

        # Check for circular reasoning
        circular_issues = self._check_circular_reasoning(context)
        issues.extend(circular_issues)

        # Check for source concentration
        concentration_issues = self._check_source_concentration(context)
        issues.extend(concentration_issues)

        # Store in context
        context.graph_context["meta_critique"] = {
            "issues": issues,
            "issue_count": len(issues),
            "severity": self._compute_severity(issues),
            "recommendations": self._generate_recommendations(issues),
        }

        logger.info(f"Meta-critique found {len(issues)} systemic issues")

        return context

    def _check_confirmation_bias(self, context: AgentContext) -> List[Dict]:
        """Check if only supporting evidence was retrieved."""
        issues = []

        grounded = context.graph_context.get("grounded_context", {})

        for claim_id, grounding in grounded.items():
            counterexamples = grounding.get("counterexamples", [])
            prior_evidence = grounding.get("prior_evidence", [])

            # If we have evidence but no counterexamples, flag potential bias
            if prior_evidence and not counterexamples:
                issues.append(
                    {
                        "type": "confirmation_bias",
                        "claim_id": claim_id,
                        "severity": "medium",
                        "description": "No counterexamples retrieved - possible confirmation bias",
                    }
                )

        return issues

    def _check_mode_collapse(self, context: AgentContext) -> List[Dict]:
        """Check if hypotheses are converging prematurely."""
        issues = []

        speculative = context.graph_context.get("speculative_context", {})

        for claim_id, spec in speculative.items():
            alternatives = spec.get("alternatives", [])

            # If few alternatives generated, flag mode collapse risk
            if len(alternatives) < 2:
                issues.append(
                    {
                        "type": "mode_collapse",
                        "claim_id": claim_id,
                        "severity": "low",
                        "description": f"Only {len(alternatives)} alternative(s) generated",
                    }
                )

        return issues

    def _check_data_sparsity(self, context: AgentContext) -> List[Dict]:
        """Check if confidence claims are backed by sufficient data."""
        issues = []

        uncertainty = context.graph_context.get("uncertainty", {})

        for claim_id, unc in uncertainty.items():
            sample_size = unc.get("components", {}).get("sample_size", 0)

            if sample_size < 5:
                issues.append(
                    {
                        "type": "data_sparsity",
                        "claim_id": claim_id,
                        "severity": "high",
                        "description": f"Only {sample_size} samples - insufficient for reliable inference",
                    }
                )

        return issues

    def _check_circular_reasoning(self, context: AgentContext) -> List[Dict]:
        """Check for circular reasoning patterns."""
        # In production, this would analyze the evidence chain
        return []

    def _check_source_concentration(self, context: AgentContext) -> List[Dict]:
        """Check for over-reliance on single sources."""
        # In production, this would analyze source diversity
        return []

    def _compute_severity(self, issues: List[Dict]) -> str:
        """Compute overall severity of issues."""
        if not issues:
            return "none"

        high_count = sum(1 for i in issues if i.get("severity") == "high")
        medium_count = sum(1 for i in issues if i.get("severity") == "medium")

        if high_count >= 2:
            return "critical"
        elif high_count >= 1 or medium_count >= 3:
            return "high"
        elif medium_count >= 1:
            return "medium"
        return "low"

    def _generate_recommendations(self, issues: List[Dict]) -> List[str]:
        """Generate recommendations based on issues found."""
        recommendations = []

        issue_types = set(i.get("type") for i in issues)

        if "confirmation_bias" in issue_types:
            recommendations.append("Search for disconfirming evidence")
        if "mode_collapse" in issue_types:
            recommendations.append("Generate more alternative hypotheses")
        if "data_sparsity" in issue_types:
            recommendations.append("Run additional experiments")

        return recommendations


# Global instance
meta_critic_agent = MetaCriticAgent()
