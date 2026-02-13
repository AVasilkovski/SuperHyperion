"""
High-Impact Write Checkpoint

v2.1 H2: Triggered before high-impact ontology changes.
"""

import logging
import uuid
from typing import Any, Dict

from src.hitl.base import HITLGate, HITLPendingItem

logger = logging.getLogger(__name__)


class HighImpactWriteCheckpoint(HITLGate):
    """
    H2 — High-Impact Write Checkpoint (before Step 13).
    
    Triggered based on impact score:
        impact_score = graph_centrality * belief_confidence_delta * downstream_dependencies
    
    If impact_score > threshold, require human approval.
    """

    def __init__(
        self,
        impact_threshold: float = 0.5,
        centrality_weight: float = 1.0,
        delta_weight: float = 1.0,
        dependency_weight: float = 0.5
    ):
        self.impact_threshold = impact_threshold
        self.centrality_weight = centrality_weight
        self.delta_weight = delta_weight
        self.dependency_weight = dependency_weight

    def should_trigger(self, context: Dict[str, Any]) -> bool:
        """Check if this gate should trigger based on impact score."""
        impact_score = self.compute_impact_score(context)
        return impact_score > self.impact_threshold

    def compute_impact_score(self, context: Dict[str, Any]) -> float:
        """
        Compute impact score for the proposed write.
        
        impact = centrality * confidence_delta * log(1 + dependencies)
        """
        import math

        centrality = context.get("graph_centrality", 0.1)
        confidence_delta = abs(
            context.get("new_confidence", 0.0) -
            context.get("old_confidence", 0.0)
        )
        dependencies = context.get("downstream_dependency_count", 0)

        impact = (
            self.centrality_weight * centrality *
            self.delta_weight * confidence_delta *
            self.dependency_weight * math.log(1 + dependencies)
        )

        return impact

    def create_pending_item(self, context: Dict[str, Any]) -> HITLPendingItem:
        """Create a pending item for human review."""
        claim_id = context.get("claim_id", "unknown")
        impact_score = self.compute_impact_score(context)

        return HITLPendingItem(
            item_id=f"impact_{uuid.uuid4().hex[:8]}",
            item_type="high_impact_write",
            claim_id=claim_id,
            current_status=context.get("current_status", "unknown"),
            proposed_status=context.get("proposed_status", "unknown"),
            evidence_summary=self._build_impact_summary(context, impact_score),
            confidence=context.get("new_confidence", 0.0),
        )

    def _build_impact_summary(
        self,
        context: Dict[str, Any],
        impact_score: float
    ) -> str:
        """Build impact summary for human review."""
        parts = [
            f"Impact Score: {impact_score:.2f}",
            f"Centrality: {context.get('graph_centrality', 0):.2f}",
            f"Dependencies: {context.get('downstream_dependency_count', 0)}",
            f"Confidence Δ: {abs(context.get('new_confidence', 0) - context.get('old_confidence', 0)):.2f}",
        ]
        return " | ".join(parts)


# Global instance
impact_gate = HighImpactWriteCheckpoint()
