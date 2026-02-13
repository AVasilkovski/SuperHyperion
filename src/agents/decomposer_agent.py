"""
Decomposer Agent

v2.1 Step 3: Splits clarified hypothesis H′ into atomic claims C1...Cn.
Each claim should be independently verifiable.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict

from src.agents.base_agent import AgentContext, BaseAgent

logger = logging.getLogger(__name__)


DECOMPOSER_SYSTEM_PROMPT = """You are a scientific claim decomposer.

Your task is to split a hypothesis into atomic, independently verifiable claims.

Each claim should have:
1. A unique identifier
2. Subject (what entity)
3. Relation (what relationship)
4. Object (target entity)
5. Conditions (when this applies)

Output JSON format:
{
    "hypothesis": "...",
    "atomic_claims": [
        {
            "claim_id": "C1",
            "content": "...",
            "subject": "...",
            "relation": "...",
            "object": "...",
            "conditions": {...}
        }
    ]
}

Be specific. Break complex claims into simpler parts.
"""


@dataclass
class AtomicClaim:
    """An atomic, independently verifiable claim."""
    claim_id: str
    content: str
    subject: str
    relation: str
    object: str
    conditions: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "content": self.content,
            "subject": self.subject,
            "relation": self.relation,
            "object": self.object,
            "conditions": self.conditions,
        }


class DecomposerAgent(BaseAgent):
    """
    Step 3: Decomposes hypothesis into atomic claims.
    
    Input: Clarified hypothesis H′
    Output: List of atomic claims C1...Cn
    
    Example:
        H′: "Protein X inhibits pathway Y under condition Z"
        C1: "Protein X affects pathway Y"
        C2: "The effect direction is inhibition"
        C3: "Condition Z is required"
    """

    def __init__(self):
        super().__init__(name="Decomposer")

    async def run(self, context: AgentContext) -> AgentContext:
        """Decompose hypothesis into atomic claims."""
        hypothesis = context.current_hypothesis or context.graph_context.get(
            "clarified_hypothesis", {}
        ).get("clarified_hypothesis", "")

        if not hypothesis:
            logger.warning("No hypothesis to decompose")
            return context

        # Use LLM to decompose
        response = self.generate(
            prompt=f"Decompose this hypothesis into atomic claims:\n\n{hypothesis}",
            system=DECOMPOSER_SYSTEM_PROMPT,
            temperature=0.3,
        )

        # Parse response
        claims = []
        try:
            parsed = json.loads(response)
            for claim_data in parsed.get("atomic_claims", []):
                claim = AtomicClaim(
                    claim_id=claim_data.get("claim_id", f"C{len(claims)+1}"),
                    content=claim_data.get("content", ""),
                    subject=claim_data.get("subject", ""),
                    relation=claim_data.get("relation", ""),
                    object=claim_data.get("object", ""),
                    conditions=claim_data.get("conditions", {}),
                )
                claims.append(claim)
        except json.JSONDecodeError:
            # Fallback: create single claim from hypothesis
            claims = [AtomicClaim(
                claim_id="C1",
                content=hypothesis,
                subject="",
                relation="",
                object="",
                conditions={},
            )]

        # Store in context (uses v2.1 atomic_claims field)
        context.graph_context["atomic_claims"] = [c.to_dict() for c in claims]

        logger.info(f"Decomposed into {len(claims)} atomic claims")

        return context


# Global instance
decomposer_agent = DecomposerAgent()
