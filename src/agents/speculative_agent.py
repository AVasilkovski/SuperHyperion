"""
Speculative Agent

v2.1 Step 5: Proposes alternative hypotheses and models.
Operates in SPECULATIVE lane - cannot update beliefs directly.
"""

from typing import Dict, Any, List
import logging
import json

from src.agents.base_agent import BaseAgent, AgentContext
from src.config import config
from src.montecarlo.types import ExperimentHints, PriorSuggestion

logger = logging.getLogger(__name__)


SPECULATIVE_SYSTEM_PROMPT = """You are a scientific hypothesis generator.

Your task is to generate alternative hypotheses and models for a given claim.
Be creative but scientifically grounded.

For each claim, propose:
1. Alternative mechanisms that could explain the same observation
2. Competing hypotheses from different theoretical frameworks
3. Edge cases where the claim might not hold
4. Analogies from other domains

Output JSON format:
{
    "claim_id": "...",
    "alternatives": [
        {
            "hypothesis": "...",
            "mechanism": "...",
            "theoretical_basis": "...",
            "testable_prediction": "..."
        }
    ],
    "analogies": [
        {"domain": "...", "parallel": "..."}
    ],
    "edge_cases": ["..."]
}

IMPORTANT: These are SPECULATIVE. They do not update beliefs.
They only inform what tests to run.
"""


class SpeculativeAgent(BaseAgent):
    """
    Step 5: Generates alternative hypotheses and models.
    
    Operates in SPECULATIVE lane:
        - Outputs are NEVER treated as truth
        - Outputs are NEVER stored as ground knowledge
        - Outputs are inputs to experiment design ONLY
    
    This is the creative, exploratory lane.
    """
    
    def __init__(self):
        super().__init__(name="SpeculativeAgent")
    
    async def run(self, context: AgentContext) -> AgentContext:
        """
        Generate speculative alternatives for all claims.
        """
        claims = context.graph_context.get("atomic_claims", [])
        
        if not claims:
            logger.warning("No claims to speculate on")
            return context
        
        speculative_results = {}
        
        for claim in claims:
            claim_id = claim.get("claim_id", "unknown")
            alternatives = await self._speculate_on_claim(claim)
            speculative_results[claim_id] = alternatives
        
        # Store in v2.1 speculative_context field
        context.graph_context["speculative_context"] = speculative_results
        
        # NEW: Extract typed experiment hints for the Brainstorm → MC Design bridge
        # These are CONTEXT-ONLY and will be consumed by VerifyAgent._design_experiment_spec
        experiment_hints = self._extract_experiment_hints(speculative_results)
        context.graph_context["experiment_hints"] = experiment_hints
        
        logger.info(f"Generated speculative alternatives for {len(claims)} claims")
        logger.info(f"Extracted experiment hints for {len(experiment_hints)} claims")
        
        return context
    
    def _extract_experiment_hints(
        self, spec_results: Dict[str, Dict]
    ) -> Dict[str, ExperimentHints]:
        """
        Extract design-relevant hints from speculative outputs.
        
        This is the formal bridge between the speculative lane and grounded lane.
        These hints are CONTEXT-ONLY and must never be persisted to TypeDB.
        
        The hints object always carries epistemic_status="speculative" so that
        the Steward guard will catch any accidental leakage into evidence payloads.
        """
        hints = {}
        for claim_id, blob in spec_results.items():
            # Extract candidate mechanisms from alternatives
            candidate_mechanisms = [
                alt.get("mechanism", "")
                for alt in blob.get("alternatives", [])
                if alt.get("mechanism")
            ]
            
            # Extract discriminative predictions (what would distinguish hypotheses)
            discriminative_predictions = [
                alt.get("testable_prediction", "")
                for alt in blob.get("alternatives", [])
                if alt.get("testable_prediction")
            ]
            
            # Edge cases become sensitivity axes
            sensitivity_axes = [
                str(ec) for ec in blob.get("edge_cases", [])
                if ec
            ]
            
            # Analogies become prior suggestions (tightly typed)
            prior_suggestions = [
                PriorSuggestion(
                    domain=str(a.get("domain", "")),
                    parallel=str(a.get("parallel", "")),
                )
                for a in blob.get("analogies", [])
                if a.get("domain") and a.get("parallel")
            ]
            
            # Falsification criteria from testable predictions
            falsification_criteria = discriminative_predictions.copy()
            
            hints[claim_id] = ExperimentHints(
                claim_id=claim_id,
                candidate_mechanisms=candidate_mechanisms,
                discriminative_predictions=discriminative_predictions,
                sensitivity_axes=sensitivity_axes,
                prior_suggestions=prior_suggestions,
                falsification_criteria=falsification_criteria,
                # epistemic_status="speculative" is the default
            )
            
            # Log the digest for audit trail (not the raw content)
            logger.debug(
                f"Extracted hints for {claim_id}: digest={hints[claim_id].digest()}"
            )
        
        return hints
    
    async def _speculate_on_claim(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate speculative alternatives for a single claim.
        """
        claim_content = claim.get("content", "")
        claim_id = claim.get("claim_id", "unknown")
        
        prompt = f"""
Claim ID: {claim_id}
Claim Content: {claim_content}
Subject: {claim.get('subject', '')}
Relation: {claim.get('relation', '')}
Object: {claim.get('object', '')}

Generate alternative hypotheses and models.
"""
        
        response = self.generate(
            prompt=prompt,
            system=SPECULATIVE_SYSTEM_PROMPT,
            temperature=0.7,  # Higher temperature for creativity
        )
        
        try:
            parsed = json.loads(response)
            return {
                "alternatives": parsed.get("alternatives", []),
                "analogies": parsed.get("analogies", []),
                "edge_cases": parsed.get("edge_cases", []),
                "epistemic_status": "speculative",  # Always tagged
            }
        except json.JSONDecodeError:
            return {
                "alternatives": [],
                "analogies": [],
                "edge_cases": [],
                "raw_speculation": response,
                "epistemic_status": "speculative",
            }


# Global instance
speculative_agent = SpeculativeAgent()

