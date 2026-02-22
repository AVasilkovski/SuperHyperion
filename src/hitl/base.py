"""
HITL Base Classes

v2.1: Base classes for human-in-the-loop gates.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Literal, Optional

logger = logging.getLogger(__name__)


@dataclass
class HITLDecision:
    """A human decision on a pending item."""

    action: Literal["approve", "downgrade", "reject", "request_evidence"]
    rationale: str
    approver_id: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "rationale": self.rationale,
            "approver_id": self.approver_id,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class HITLPendingItem:
    """An item pending human decision."""

    item_id: str
    item_type: str  # "epistemic_transition", "high_impact_write", etc.
    claim_id: str
    current_status: str
    proposed_status: str
    evidence_summary: str
    confidence: float
    created_at: datetime = field(default_factory=datetime.now)
    decision: Optional[HITLDecision] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "item_type": self.item_type,
            "claim_id": self.claim_id,
            "current_status": self.current_status,
            "proposed_status": self.proposed_status,
            "evidence_summary": self.evidence_summary,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
            "decision": self.decision.to_dict() if self.decision else None,
        }


class HITLGate(ABC):
    """
    Base class for human-in-the-loop checkpoints.

    Global rule (non-negotiable):
        Any write that changes belief status, source reputation,
        or contradiction resolution requires a human checkpoint
        unless explicitly auto-approved by policy.
    """

    @abstractmethod
    def should_trigger(self, context: Dict[str, Any]) -> bool:
        """Determine if human review is needed."""
        pass

    @abstractmethod
    def create_pending_item(self, context: Dict[str, Any]) -> HITLPendingItem:
        """Create a pending item for human review."""
        pass

    async def await_decision(
        self,
        pending: HITLPendingItem,
        timeout_seconds: int = 86400,  # 24 hours default
    ) -> Optional[HITLDecision]:
        """
        Wait for human decision.

        In production, this would poll a database or wait for webhook.
        For now, returns None (decision pending).
        """
        logger.info(f"HITL gate triggered: {pending.item_id}")
        return None

    def process_decision(self, pending: HITLPendingItem, decision: HITLDecision) -> Dict[str, Any]:
        """Process a human decision."""
        pending.decision = decision

        result = {
            "item_id": pending.item_id,
            "approved": decision.action == "approve",
            "action": decision.action,
            "rationale": decision.rationale,
        }

        logger.info(f"HITL decision processed: {pending.item_id} -> {decision.action}")

        return result
