"""
Epistemic Approval Gate

v2.1 H1: Triggered when epistemic status transitions.
"""

import logging
import uuid
from typing import Any, Dict

from src.epistemic.status import EpistemicStatus, requires_hitl_approval
from src.hitl.base import HITLGate, HITLPendingItem

logger = logging.getLogger(__name__)


class EpistemicApprovalGate(HITLGate):
    """
    H1 — Epistemic Promotion Gate (after Step 9).
    
    Triggered when epistemic_status transitions:
        - SPECULATIVE → SUPPORTED
        - SUPPORTED → PROVEN
        - UNRESOLVED → REFUTED
        - Confidence crosses threshold (>0.7)
    
    Human sees:
        - Claim content
        - Evidence summary
        - CodeAct outputs
        - Bayesian delta
        - Any contradictions
    
    Human actions:
        ✅ Approve - Accept the transition
        ⚠️ Downgrade - Lower to previous status
        ❌ Reject - Reject the claim entirely
        🧪 Request more evidence
    """

    def __init__(self, confidence_threshold: float = 0.7):
        self.confidence_threshold = confidence_threshold

    def should_trigger(self, context: Dict[str, Any]) -> bool:
        """Check if this gate should trigger."""
        current = context.get("current_status")
        proposed = context.get("proposed_status")
        confidence = context.get("confidence", 0.0)

        # Check status transition
        if current and proposed:
            try:
                current_enum = EpistemicStatus(current)
                proposed_enum = EpistemicStatus(proposed)
                if requires_hitl_approval(current_enum, proposed_enum):
                    return True
            except ValueError:
                pass

        # Check confidence threshold crossing
        if confidence >= self.confidence_threshold:
            prev_confidence = context.get("previous_confidence", 0.0)
            if prev_confidence < self.confidence_threshold:
                return True

        return False

    def create_pending_item(self, context: Dict[str, Any]) -> HITLPendingItem:
        """Create a pending item for human review."""
        claim_id = context.get("claim_id", "unknown")

        return HITLPendingItem(
            item_id=f"epistemic_{uuid.uuid4().hex[:8]}",
            item_type="epistemic_transition",
            claim_id=claim_id,
            current_status=context.get("current_status", "speculative"),
            proposed_status=context.get("proposed_status", "supported"),
            evidence_summary=self._build_evidence_summary(context),
            confidence=context.get("confidence", 0.0),
        )

    def _build_evidence_summary(self, context: Dict[str, Any]) -> str:
        """Build a summary of evidence for human review."""
        parts = []

        # Evidence count
        evidence = context.get("evidence", [])
        parts.append(f"Evidence items: {len(evidence)}")

        # Confidence
        parts.append(f"Confidence: {context.get('confidence', 0):.0%}")

        # Contradictions
        contradictions = context.get("contradictions", [])
        if contradictions:
            parts.append(f"⚠️ {len(contradictions)} contradiction(s) detected")

        # CodeAct results
        codeact_success = sum(
            1 for e in evidence if e.get("success", False)
        )
        parts.append(f"Successful experiments: {codeact_success}/{len(evidence)}")

        return " | ".join(parts)


# Global instance
epistemic_gate = EpistemicApprovalGate()
