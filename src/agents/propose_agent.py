"""
Propose Agent (v2.2)

ValidatorAgent.B: Produces epistemic status proposals with cap enforcement.
Consumes verification artifacts and meta_critique to enforce caps.

DOES NOT write to TypeDB (that's steward_node).
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import logging

from src.agents.base_agent import BaseAgent, AgentContext

logger = logging.getLogger(__name__)


# Status ranking for cap enforcement
STATUS_RANK = {
    "SPECULATIVE": 0,
    "UNRESOLVED": 1,
    "SUPPORTED": 2,
    "PROVEN": 3,
}


@dataclass
class WriteIntent:
    """Staged write intent (executed only by OntologySteward)."""
    intent_id: str
    intent_type: str  # "create_claim" | "update_status" | "link_hypothesis" | "supports" | "refutes"
    lane: str       # "grounded" | "speculative"
    payload: Dict[str, Any]
    impact_score: Optional[float] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    requires_hitl: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "intent_type": self.intent_type,
            "lane": self.lane,
            "payload": self.payload,
            "impact_score": self.impact_score,
            "provenance": self.provenance,
            "requires_hitl": self.requires_hitl,
        }


@dataclass
class EpistemicUpdateProposal:
    """
    Proposal for epistemic status update.
    
    Contains both the raw proposal and the capped version.
    """
    claim_id: str
    current_status: str
    proposed_status: str
    max_allowed_status: str
    final_proposed_status: str
    confidence: float
    confidence_interval: tuple
    rationale: str
    cap_reasons: List[str]
    requires_hitl: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "current_status": self.current_status,
            "proposed_status": self.proposed_status,
            "max_allowed_status": self.max_allowed_status,
            "final_proposed_status": self.final_proposed_status,
            "confidence": self.confidence,
            "confidence_interval": self.confidence_interval,
            "rationale": self.rationale,
            "cap_reasons": self.cap_reasons,
            "requires_hitl": self.requires_hitl,
        }


class ProposeAgent(BaseAgent):
    """
    v2.2 Step: Produces epistemic status proposals with cap enforcement.
    
    Responsibilities:
        - Read verification_report, fragility_report, contradictions, meta_critique
        - Compute proposed status changes
        - ENFORCE CAPS based on fragility/meta_critique/contradictions
        - Generate staged write_intents
        
    Does NOT:
        - Execute writes
        - Bypass HITL gates
    """
    
    def __init__(self):
        super().__init__(name="ProposeAgent")
    
    async def run(self, context: AgentContext) -> AgentContext:
        """Generate epistemic update proposals with cap enforcement."""
        
        # Read artifacts from verify and meta_critic
        evidence = context.graph_context.get("evidence", [])
        verification_report = context.graph_context.get("verification_report", {})
        fragility_report = context.graph_context.get("fragility_report", {})
        contradictions = context.graph_context.get("contradictions", {})
        meta_critique = context.graph_context.get("meta_critique", {})
        
        proposals = []
        write_intents = []
        
        for ev in evidence:
            claim_id = ev.get("claim_id", "unknown")
            
            # Compute raw proposal from evidence
            raw_proposal = self._compute_raw_proposal(ev, verification_report)
            
            # Apply caps based on fragility, meta_critique, contradictions
            max_status, cap_reasons = self._compute_max_allowed_status(
                claim_id=claim_id,
                fragility_report=fragility_report,
                meta_critique=meta_critique,
                contradictions=contradictions,
            )
            
            # Final status is min(proposed, max_allowed)
            final_status = self._min_status(raw_proposal["proposed_status"], max_status)
            
            # Check if HITL required
            requires_hitl = self._check_requires_hitl(
                current_status="SPECULATIVE",
                final_status=final_status,
                meta_critique=meta_critique,
                fragility_report=fragility_report,
            )
            
            proposal = EpistemicUpdateProposal(
                claim_id=claim_id,
                current_status="SPECULATIVE",  # Would come from TypeDB
                proposed_status=raw_proposal["proposed_status"],
                max_allowed_status=max_status,
                final_proposed_status=final_status,
                confidence=raw_proposal["confidence"],
                confidence_interval=raw_proposal["confidence_interval"],
                rationale=raw_proposal["rationale"],
                cap_reasons=cap_reasons,
                requires_hitl=requires_hitl,
            )
            proposals.append(proposal)
            
            # Create staged write intent
            intent = WriteIntent(
                intent_id=f"intent-{claim_id}-{len(write_intents)}",
                intent_type="update_epistemic_status",  # Aligned with registry
                lane="grounded",
                payload={
                    "claim_id": claim_id,
                    "new_status": final_status,
                    "confidence": raw_proposal["confidence"],
                    "evidence_ids": [ev.get("execution_id")],
                },
                impact_score=self._compute_impact_score(claim_id, final_status),
                provenance={
                    "evidence_id": ev.get("execution_id"),
                    "template_id": ev.get("template_id"),
                },
                requires_hitl=requires_hitl,
            )
            write_intents.append(intent)
        
        # Store results
        context.graph_context["epistemic_update_proposal"] = [p.to_dict() for p in proposals]
        context.graph_context["write_intents"] = [w.to_dict() for w in write_intents]
        
        logger.info(f"Proposed {len(proposals)} status updates, {sum(1 for p in proposals if p.requires_hitl)} require HITL")
        
        return context
    
    def _compute_raw_proposal(
        self,
        evidence: Dict[str, Any],
        verification_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compute raw status proposal from evidence."""
        
        # Default to SPECULATIVE
        proposed_status = "SPECULATIVE"
        confidence = 0.0
        
        if evidence.get("success"):
            metrics = evidence.get("metrics", {})
            
            # Check if evidence supports claim
            consistent = metrics.get("consistent", metrics.get("passes", 0))
            if isinstance(consistent, bool):
                consistent = 1.0 if consistent else 0.0
            
            if consistent > 0.5:
                proposed_status = "SUPPORTED"
                confidence = min(0.95, consistent)
                
                # Check if can upgrade to PROVEN (multiple lines of evidence, low variance)
                variance = metrics.get("variance", 1.0)
                if variance < 0.05 and confidence > 0.9:
                    proposed_status = "PROVEN"
            else:
                # Evidence refutes claim
                proposed_status = "REFUTED" if consistent < 0.2 else "UNRESOLVED"
                confidence = 1.0 - consistent
        
        # Get CI from metrics
        ci_low = metrics.get("ci_low", confidence - 0.1)
        ci_high = metrics.get("ci_high", confidence + 0.1)
        
        return {
            "proposed_status": proposed_status,
            "confidence": confidence,
            "confidence_interval": (ci_low, ci_high),
            "rationale": f"Based on template {evidence.get('template_id')} execution",
        }
    
    def _compute_max_allowed_status(
        self,
        claim_id: str,
        fragility_report: Dict[str, Any],
        meta_critique: Dict[str, Any],
        contradictions: Dict[str, Any],
    ) -> tuple:
        """
        Compute maximum allowed status based on caps.
        
        CRITICAL: This enforces fragility/meta_critique caps.
        """
        max_status = "PROVEN"
        cap_reasons = []
        
        # 1) Fragility cap
        fragile_claims = fragility_report.get("fragile_claims", [])
        if claim_id in fragile_claims or fragility_report.get("fragile", False):
            max_status = self._min_status(max_status, "SUPPORTED")
            cap_reasons.append("Fragile: sensitivity analysis shows conclusion may flip under perturbation")
        
        # 2) MetaCritic cap
        severity = meta_critique.get("severity", "low")
        if severity in ("high", "critical"):
            max_status = self._min_status(max_status, "SUPPORTED")
            cap_reasons.append(f"MetaCritic severity={severity}: systemic concerns detected")
        
        # 3) Contradiction cap
        if contradictions.get("unresolved_count", 0) > 0:
            max_status = self._min_status(max_status, "UNRESOLVED")
            cap_reasons.append(f"Unresolved contradictions: {contradictions.get('unresolved_count')}")
        
        return max_status, cap_reasons
    
    def _min_status(self, status_a: str, status_b: str) -> str:
        """Return the lower-ranked status."""
        rank_a = STATUS_RANK.get(status_a, 0)
        rank_b = STATUS_RANK.get(status_b, 0)
        
        if rank_a <= rank_b:
            return status_a
        return status_b
    
    def _check_requires_hitl(
        self,
        current_status: str,
        final_status: str,
        meta_critique: Dict[str, Any],
        fragility_report: Dict[str, Any],
    ) -> bool:
        """Determine if HITL approval is required."""
        
        # Always require HITL for promotion to PROVEN
        if final_status == "PROVEN":
            return True
        
        # Require HITL if severity is critical
        if meta_critique.get("severity") == "critical":
            return True
        
        # Require HITL if high confidence but fragile
        if fragility_report.get("fragile") and final_status == "SUPPORTED":
            return True
        
        # Require HITL for any upgrade transition
        current_rank = STATUS_RANK.get(current_status, 0)
        final_rank = STATUS_RANK.get(final_status, 0)
        if final_rank > current_rank:
            return True
        
        return False
    
    def _compute_impact_score(self, claim_id: str, status: str) -> float:
        """Compute impact score for write intent."""
        # Simplified: higher status = higher impact
        base_impact = {
            "SPECULATIVE": 0.1,
            "UNRESOLVED": 0.3,
            "SUPPORTED": 0.5,
            "PROVEN": 0.9,
            "REFUTED": 0.7,
        }.get(status, 0.5)
        
        return base_impact


# Global instance
propose_agent = ProposeAgent()
