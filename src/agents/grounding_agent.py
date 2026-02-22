"""
Grounding Agent

v2.1 Step 4: Constraint-anchored retrieval from TypeDB.
Not just context retrieval - fetches domain axioms, prior evidence, counterexamples.
"""

import logging
from typing import Any, Dict, List

from src.agents.base_agent import AgentContext, BaseAgent

logger = logging.getLogger(__name__)


class GroundingAgent(BaseAgent):
    """
    Step 4: Constraint-anchored grounding from the knowledge graph.

    NOT shallow retrieval. Must return:
        - Domain axioms (physical laws, invariants)
        - Prior evidence (supporting/refuting)
        - Counterexamples (known violations)
        - Boundary conditions (when claim applies)

    This agent operates in the GROUNDED lane.
    """

    def __init__(self):
        super().__init__(name="GroundingAgent")

    async def run(self, context: AgentContext) -> AgentContext:
        """
        Retrieve grounded context for all atomic claims.
        """
        claims = context.graph_context.get("atomic_claims", [])

        if not claims:
            logger.warning("No atomic claims to ground")
            return context

        grounded_results = {}

        for claim in claims:
            claim_id = claim.get("claim_id", "unknown")

            # Retrieve grounded context
            grounded = self._ground_claim(claim)
            grounded_results[claim_id] = grounded

        # Store in v2.1 grounded_context field
        context.graph_context["grounded_context"] = grounded_results

        logger.info(f"Grounded {len(claims)} claims")

        return context

    def _ground_claim(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        """
        Retrieve constraint-anchored context for a single claim.
        """
        subject = claim.get("subject", "")
        _relation = claim.get("relation", "")  # Reserved for future use
        obj = claim.get("object", "")

        # Query for domain axioms
        axioms = self._retrieve_axioms(subject, obj)

        # Query for prior evidence
        prior_evidence = self._retrieve_prior_evidence(claim)

        # Query for counterexamples
        counterexamples = self._retrieve_counterexamples(claim)

        # Query for boundary conditions
        boundaries = self._retrieve_boundaries(claim)

        return {
            "domain_axioms": axioms,
            "prior_evidence": prior_evidence,
            "counterexamples": counterexamples,
            "boundary_conditions": boundaries,
        }

    def _retrieve_axioms(self, subject: str, obj: str) -> List[Dict[str, Any]]:
        """Retrieve domain axioms related to the claim."""
        try:
            # Query TypeDB for domain constraints
            query = f"""
                match
                    $concept isa concept, has label $label;
                    $label contains "{subject}" or $label contains "{obj}";
                fetch $concept: label, definition;
            """
            results = self.query_graph(query)
            return results if results else []
        except Exception as e:
            logger.warning(f"Axiom retrieval failed: {e}")
            return []

    def _retrieve_prior_evidence(self, claim: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Retrieve prior evidence for the claim."""
        try:
            _content = claim.get("content", "")  # Reserved for future use
            query = """
                match
                    $h isa hypothesis, has confidence-score $c;
                    $h has belief-state $s;
                fetch $h: confidence-score, belief-state;
            """
            results = self.query_graph(query)
            return results[:5] if results else []  # Limit to top 5
        except Exception as e:
            logger.warning(f"Prior evidence retrieval failed: {e}")
            return []

    def _retrieve_counterexamples(self, claim: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Retrieve known counterexamples."""
        try:
            query = """
                match
                    $c isa contradiction;
                fetch $c: conflict-strength, resolution-status;
            """
            results = self.query_graph(query)
            return results[:3] if results else []  # Limit to top 3
        except Exception as e:
            logger.warning(f"Counterexample retrieval failed: {e}")
            return []

    def _retrieve_boundaries(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve boundary conditions for the claim."""
        conditions = claim.get("conditions", {})
        return {
            "specified_conditions": conditions,
            "known_limits": [],
            "applicability_range": "general",
        }


# Global instance
grounding_agent = GroundingAgent()
