"""
Belief Maintenance Agent

Runs background Bayesian updates on TypeDB hypothesis nodes.
Monitors for contradictions and triggers belief revision.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List

from src.agents.base_agent import AgentContext, BaseAgent
from src.config import config

logger = logging.getLogger(__name__)


@dataclass
class BeliefState:
    """Represents a hypothesis belief state."""

    hypothesis_id: str
    alpha: float  # Beta distribution alpha
    beta: float  # Beta distribution beta
    expected_value: float
    entropy: float
    belief_state: str  # "proposed", "verified", "refuted", "debated"


class BeliefMaintenanceAgent(BaseAgent):
    """
    Agent responsible for maintaining belief consistency in the knowledge graph.

    Functions:
    - Monitor hypothesis nodes for updates
    - Perform Bayesian belief updates when new evidence arrives
    - Detect contradictions and flag for Socratic debate
    - Update dialectical entropy scores
    """

    def __init__(self):
        super().__init__(name="BeliefMaintenanceAgent")
        self._running = False

    async def run(self, context: AgentContext) -> AgentContext:
        """Run belief maintenance cycle."""
        # Get all hypotheses that need updating
        hypotheses = self._get_pending_hypotheses()

        for hyp in hypotheses:
            # Calculate current belief state
            belief = self._calculate_belief(hyp)
            context.dialectical_entropy = max(context.dialectical_entropy, belief.entropy)

            # Check for contradictions
            contradictions = self._find_contradictions(hyp)
            if contradictions:
                logger.warning(f"Contradictions found for {hyp['id']}: {contradictions}")
                context.graph_context["contradictions"] = contradictions

            # Update belief state in graph
            self._update_belief_state(hyp["id"], belief)

        return context

    def _get_pending_hypotheses(self) -> List[Dict]:
        """Fetch hypotheses needing belief updates."""
        query = """
        match
            $h isa hypothesis,
                has beta_alpha $a,
                has beta_beta $b,
                has belief_state $state;
            $state != "verified";
            $state != "refuted";
        fetch
            $h: beta_alpha, beta_beta, belief_state;
        """
        try:
            return self.query_graph(query)
        except Exception as e:
            logger.error(f"Failed to fetch hypotheses: {e}")
            return []

    def _calculate_belief(self, hypothesis: Dict) -> BeliefState:
        """Calculate belief metrics for a hypothesis."""
        alpha = hypothesis.get("beta_alpha", 1.0)
        beta = hypothesis.get("beta_beta", 1.0)

        # Expected value of Beta distribution
        expected = alpha / (alpha + beta)

        # Calculate entropy (uncertainty)
        # Using approximation for Beta distribution entropy
        total = alpha + beta
        if total > 2:
            variance = (alpha * beta) / ((total**2) * (total + 1))
            # Normalize to 0-1 range
            entropy = min(1.0, 4 * variance)  # Max variance is 0.25 at alpha=beta=1
        else:
            entropy = 1.0  # High uncertainty for low sample size

        # Determine belief state
        if expected > 0.8 and entropy < 0.2:
            state = "verified"
        elif expected < 0.2 and entropy < 0.2:
            state = "refuted"
        elif entropy > config.entropy_threshold:
            state = "debated"
        else:
            state = "proposed"

        return BeliefState(
            hypothesis_id=hypothesis.get("id", "unknown"),
            alpha=alpha,
            beta=beta,
            expected_value=expected,
            entropy=entropy,
            belief_state=state,
        )

    def _find_contradictions(self, hypothesis: Dict) -> List[Dict]:
        """Find contradicting hypotheses in the graph."""
        # Query for hypotheses about the same causality with opposing beliefs
        query = """
        match
            $h1 isa hypothesis, has belief_state "verified";
            $h2 isa hypothesis, has belief_state "verified";
            $h1 (assertion: $c1);
            $h2 (assertion: $c2);
            $c1 isa causality (cause: $x, effect: $y);
            $c2 isa causality (cause: $x, effect: $z);
            not { $y is $z; };
            not { $h1 is $h2; };
        fetch
            $h1, $h2, $c1, $c2;
        """
        try:
            return self.query_graph(query)
        except Exception as e:
            logger.debug(f"Contradiction query failed (may be empty): {e}")
            return []

    def _update_belief_state(self, hypothesis_id: str, belief: BeliefState):
        """Update the belief state in TypeDB."""
        _query = f"""
        match
            $h isa hypothesis, has belief_state $old_state;
            $h has beta_alpha {belief.alpha};
        delete
            $h has $old_state;
        insert
            $h has belief_state "{belief.belief_state}";
        """
        try:
            # WriteCap: belief state updates must go through OntologySteward
            logger.info(
                f"Belief state update deferred to OntologySteward: "
                f"{hypothesis_id} → {belief.belief_state}"
            )
        except Exception as e:
            logger.error(f"Failed to update belief state: {e}")

    def update_belief(
        self, hypothesis_id: str, evidence_supports: bool, evidence_weight: float = 1.0
    ):
        """
        Update belief based on new evidence (Bayesian update).

        Args:
            hypothesis_id: ID of the hypothesis
            evidence_supports: True if evidence supports, False if refutes
            evidence_weight: Strength of the evidence (default 1.0)
        """
        # Fetch current belief
        query = """
        match
            $h isa hypothesis,
                has beta_alpha $a,
                has beta_beta $b;
        fetch
            $h: beta_alpha, beta_beta;
        limit 1;
        """

        try:
            results = self.query_graph(query)
            if not results:
                logger.warning(f"Hypothesis not found: {hypothesis_id}")
                return

            current = results[0]
            alpha = current.get("beta_alpha", 1.0)
            beta = current.get("beta_beta", 1.0)

            # Bayesian update
            if evidence_supports:
                new_alpha = alpha + evidence_weight
                new_beta = beta
            else:
                new_alpha = alpha
                new_beta = beta + evidence_weight

            # Update in graph
            _update_query = f"""
            match
                $h isa hypothesis,
                    has beta_alpha $old_a,
                    has beta_beta $old_b;
            delete
                $h has $old_a, has $old_b;
            insert
                $h has beta_alpha {new_alpha},
                   has beta_beta {new_beta};
            """
            # WriteCap: belief updates must go through OntologySteward
            logger.info(
                f"Belief update deferred to OntologySteward: {hypothesis_id} "
                f"α={alpha:.2f}→{new_alpha:.2f}, β={beta:.2f}→{new_beta:.2f}"
            )

        except Exception as e:
            logger.error(f"Failed to update belief: {e}")

    async def run_background(self, interval: int = 60):
        """Run belief maintenance in background loop."""
        self._running = True
        logger.info(f"Starting background belief maintenance (interval={interval}s)")

        while self._running:
            try:
                context = AgentContext()
                await self.run(context)

                if context.dialectical_entropy > config.entropy_threshold:
                    logger.warning(f"High entropy detected: {context.dialectical_entropy:.3f}")

            except Exception as e:
                logger.error(f"Belief maintenance error: {e}")

            await asyncio.sleep(interval)

    def stop_background(self):
        """Stop background maintenance."""
        self._running = False
        logger.info("Stopping background belief maintenance")


# Global instance
belief_agent = BeliefMaintenanceAgent()
