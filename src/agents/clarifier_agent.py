"""
Clarifier Agent

v2.1 Step 2: Refines user hypothesis H into precise H′.
Removes ambiguity, identifies variables, asks clarifying questions.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from src.agents.base_agent import AgentContext, BaseAgent

logger = logging.getLogger(__name__)


CLARIFIER_SYSTEM_PROMPT = """You are a scientific hypothesis clarifier.

Your task is to take a user's hypothesis and:
1. Identify ambiguous terms
2. Specify variables and conditions
3. Ask clarifying questions if needed
4. Output a precise, testable hypothesis H′

Output JSON format:
{
    "original_hypothesis": "...",
    "clarified_hypothesis": "...",
    "variables": [{"name": "...", "type": "...", "conditions": "..."}],
    "assumptions": ["..."],
    "clarifying_questions": ["..."],
    "is_testable": true/false
}
"""


@dataclass
class ClarifiedHypothesis:
    """Output of the clarification step."""

    original: str
    clarified: str
    variables: List[Dict[str, str]]
    assumptions: List[str]
    questions: List[str]
    is_testable: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_hypothesis": self.original,
            "clarified_hypothesis": self.clarified,
            "variables": self.variables,
            "assumptions": self.assumptions,
            "clarifying_questions": self.questions,
            "is_testable": self.is_testable,
        }


class ClarifierAgent(BaseAgent):
    """
    Step 2: Clarifies user hypothesis into testable form.

    Input: User's raw hypothesis H
    Output: Precise hypothesis H′ with identified variables

    Example:
        H: "Protein X inhibits pathway Y"
        H′: "Protein X inhibits pathway Y under condition Z (pH=7.4, temp=37°C)"
    """

    def __init__(self):
        super().__init__(name="Clarifier")

    async def run(self, context: AgentContext) -> AgentContext:
        """Clarify the user's hypothesis."""
        query = context.messages[-1].get("content", "") if context.messages else ""

        # Use LLM to clarify
        response = self.generate(
            prompt=f"Clarify this scientific hypothesis:\n\n{query}",
            system=CLARIFIER_SYSTEM_PROMPT,
            temperature=0.3,
        )

        # Parse response
        try:
            parsed = json.loads(response)
            clarified = ClarifiedHypothesis(
                original=query,
                clarified=parsed.get("clarified_hypothesis", query),
                variables=parsed.get("variables", []),
                assumptions=parsed.get("assumptions", []),
                questions=parsed.get("clarifying_questions", []),
                is_testable=parsed.get("is_testable", True),
            )
        except json.JSONDecodeError:
            # Fallback: use raw response as clarified hypothesis
            clarified = ClarifiedHypothesis(
                original=query,
                clarified=response,
                variables=[],
                assumptions=[],
                questions=[],
                is_testable=True,
            )

        # Store in context
        context.graph_context["clarified_hypothesis"] = clarified.to_dict()
        context.current_hypothesis = clarified.clarified

        logger.info(f"Clarified hypothesis: {clarified.clarified}")

        return context


# Global instance
clarifier_agent = ClarifierAgent()
