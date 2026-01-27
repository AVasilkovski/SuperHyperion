"""
HITL Audit Log

v2.1 H6: Immutable audit trail for all human decisions.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional
import json
import logging
from pathlib import Path

from src.hitl.base import HITLDecision

logger = logging.getLogger(__name__)


@dataclass
class HITLAuditEvent:
    """An immutable audit event."""
    event_id: str
    timestamp: datetime
    event_type: str  # "decision", "gate_triggered", "override"
    claim_id: str
    actor_id: str
    action: str
    details: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "claim_id": self.claim_id,
            "actor_id": self.actor_id,
            "action": self.action,
            "details": self.details,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class HITLAuditLog:
    """
    Immutable audit log for all HITL decisions.
    
    Properties:
        - Append-only (no modifications)
        - Timestamped
        - Actor-tracked
        - Queryable by claim_id
    """
    
    def __init__(self, log_path: Optional[Path] = None):
        self._events: List[HITLAuditEvent] = []
        self._event_counter = 0
        self.log_path = log_path
    
    def log_decision(
        self,
        claim_id: str,
        decision: HITLDecision,
        gate_type: str = "unknown"
    ) -> str:
        """Log a human decision."""
        self._event_counter += 1
        event_id = f"evt_{self._event_counter:06d}"
        
        event = HITLAuditEvent(
            event_id=event_id,
            timestamp=datetime.now(),
            event_type="decision",
            claim_id=claim_id,
            actor_id=decision.approver_id,
            action=decision.action,
            details={
                "rationale": decision.rationale,
                "gate_type": gate_type,
            },
        )
        
        self._append_event(event)
        return event_id
    
    def log_gate_triggered(
        self,
        claim_id: str,
        gate_type: str,
        trigger_reason: str
    ) -> str:
        """Log when a gate is triggered."""
        self._event_counter += 1
        event_id = f"evt_{self._event_counter:06d}"
        
        event = HITLAuditEvent(
            event_id=event_id,
            timestamp=datetime.now(),
            event_type="gate_triggered",
            claim_id=claim_id,
            actor_id="system",
            action="trigger",
            details={
                "gate_type": gate_type,
                "trigger_reason": trigger_reason,
            },
        )
        
        self._append_event(event)
        return event_id
    
    def _append_event(self, event: HITLAuditEvent) -> None:
        """Append event to log (immutable)."""
        self._events.append(event)
        
        # Persist to file if path configured
        if self.log_path:
            try:
                with open(self.log_path, "a") as f:
                    f.write(event.to_json() + "\n")
            except Exception as e:
                logger.error(f"Failed to persist audit event: {e}")
        
        logger.info(f"Audit event logged: {event.event_id}")
    
    def get_decision_history(self, claim_id: str) -> List[HITLAuditEvent]:
        """Get all audit events for a claim."""
        return [e for e in self._events if e.claim_id == claim_id]
    
    def get_all_events(self) -> List[HITLAuditEvent]:
        """Get all audit events."""
        return list(self._events)  # Return copy
    
    def get_decisions_by_actor(self, actor_id: str) -> List[HITLAuditEvent]:
        """Get all decisions made by a specific actor."""
        return [
            e for e in self._events 
            if e.actor_id == actor_id and e.event_type == "decision"
        ]
    
    def count_by_action(self) -> Dict[str, int]:
        """Count events by action type."""
        counts: Dict[str, int] = {}
        for event in self._events:
            action = event.action
            counts[action] = counts.get(action, 0) + 1
        return counts


# Global instance
audit_log = HITLAuditLog()
