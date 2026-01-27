"""
Epistemic Classifier Agent

v2.1: Determines epistemic status based on evidence.
Single responsibility: classify claims, not update beliefs.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import logging

from src.agents.base_agent import BaseAgent, AgentContext
from src.epistemic.status import EpistemicStatus, requires_hitl_approval
from src.epistemic.uncertainty import uncertainty_from_codeact_result

logger = logging.getLogger(__name__)


@dataclass
class EpistemicClassification:
    """
    Output of epistemic classification.
    
    Contains:
        status: The determined epistemic status
        justification: Human-readable explanation
        confidence: Numeric confidence (from evidence)
        missing_evidence: What would strengthen the claim
    """
    status: EpistemicStatus
    justification: str
    confidence: float
    missing_evidence: List[str]
    requires_hitl: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "justification": self.justification,
            "confidence": self.confidence,
            "missing_evidence": self.missing_evidence,
            "requires_hitl": self.requires_hitl,
        }


class EpistemicClassifierAgent(BaseAgent):
    """
    Agent that determines epistemic status based on evidence.
    
    Decision rules:
        - No evidence → SPECULATIVE
        - One experiment → SUPPORTED  
        - Replication + low variance → PROVEN
        - Contradicted → REFUTED
        
    LLM assists; rules decide.
    """
    
    def __init__(self):
        super().__init__(name="EpistemicClassifier")
    
    async def run(self, context: AgentContext) -> AgentContext:
        """
        Classify all claims in context and attach epistemic status.
        """
        classifications = []
        
        for claim in context.graph_context.get("claims", []):
            classification = self.classify_claim(
                claim=claim,
                evidence=context.code_results,
                contradictions=context.graph_context.get("contradictions", [])
            )
            classifications.append(classification)
        
        context.graph_context["classifications"] = [
            c.to_dict() for c in classifications
        ]
        return context
    
    def classify_claim(
        self,
        claim: Dict[str, Any],
        evidence: List[Dict[str, Any]],
        contradictions: List[Dict[str, Any]],
        current_status: Optional[EpistemicStatus] = None,
    ) -> EpistemicClassification:
        """
        Classify a single claim based on evidence.
        
        Args:
            claim: The claim to classify
            evidence: List of CodeAct execution results
            contradictions: Known contradicting claims
            current_status: Current epistemic status (for HITL checks)
            
        Returns:
            EpistemicClassification with status and justification
        """
        claim_id = claim.get("claim_id") or claim.get("id", "unknown")
        
        # Gather evidence for this claim
        claim_evidence = [
            e for e in evidence 
            if e.get("hypothesis_id") == claim_id
        ]
        
        # Check for contradictions
        has_contradictions = any(
            c.get("claim_a_id") == claim_id or c.get("claim_b_id") == claim_id
            for c in contradictions
        )
        
        # Check if refuted
        refuted = any(
            e.get("refutes", False) for e in claim_evidence
        )
        
        # Compute variance from evidence
        result_values = [
            e.get("result", {}).get("value", 0.0) 
            for e in claim_evidence
            if isinstance(e.get("result"), dict)
        ]
        
        if result_values:
            n = len(result_values)
            mean = sum(result_values) / n
            variance = sum((x - mean) ** 2 for x in result_values) / max(n - 1, 1)
        else:
            n = 0
            variance = 1.0
        
        # Apply decision rules
        new_status = EpistemicStatus.from_evidence(
            has_evidence=len(claim_evidence) > 0,
            experiment_count=len(claim_evidence),
            variance=variance,
            has_contradiction=has_contradictions,
            refuted=refuted
        )
        
        # Build justification
        justification = self._build_justification(
            claim_id=claim_id,
            status=new_status,
            evidence_count=len(claim_evidence),
            variance=variance,
            has_contradictions=has_contradictions,
            refuted=refuted
        )
        
        # Identify missing evidence
        missing = self._identify_missing_evidence(
            status=new_status,
            evidence_count=len(claim_evidence),
            variance=variance
        )
        
        # Check if HITL required
        requires_hitl = False
        if current_status is not None:
            requires_hitl = requires_hitl_approval(current_status, new_status)
        
        return EpistemicClassification(
            status=new_status,
            justification=justification,
            confidence=1.0 - variance if variance <= 1.0 else 0.0,
            missing_evidence=missing,
            requires_hitl=requires_hitl
        )
    
    def _build_justification(
        self,
        claim_id: str,
        status: EpistemicStatus,
        evidence_count: int,
        variance: float,
        has_contradictions: bool,
        refuted: bool
    ) -> str:
        """Build human-readable justification for the classification."""
        if refuted:
            return f"Claim {claim_id} is REFUTED by counter-evidence."
        if has_contradictions:
            return f"Claim {claim_id} has unresolved contradictions."
        if evidence_count == 0:
            return f"Claim {claim_id} has no experimental evidence yet."
        if status == EpistemicStatus.PROVEN:
            return (
                f"Claim {claim_id} is PROVEN with {evidence_count} experiments "
                f"and low variance ({variance:.3f})."
            )
        if status == EpistemicStatus.SUPPORTED:
            return (
                f"Claim {claim_id} is SUPPORTED by {evidence_count} experiment(s). "
                f"Replication needed for PROVEN status."
            )
        return f"Claim {claim_id} status: {status.value}"
    
    def _identify_missing_evidence(
        self,
        status: EpistemicStatus,
        evidence_count: int,
        variance: float
    ) -> List[str]:
        """Identify what evidence is missing to strengthen the claim."""
        missing = []
        
        if status == EpistemicStatus.SPECULATIVE:
            missing.append("Initial experimental evidence required.")
        
        if status == EpistemicStatus.SUPPORTED:
            missing.append("Replication experiment needed.")
            if variance > 0.1:
                missing.append("Lower variance required (currently too high).")
        
        if status == EpistemicStatus.UNRESOLVED:
            missing.append("Contradiction resolution experiment needed.")
        
        return missing


# Global instance
epistemic_classifier = EpistemicClassifierAgent()
