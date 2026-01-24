"""
Socratic Debate Agent

Orchestrates multi-agent debates when dialectical entropy is high.
Implements the v2.1 specification for conflict resolution.
"""

import asyncio
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging

from src.agents.base_agent import BaseAgent, AgentContext
from src.config import config

logger = logging.getLogger(__name__)


@dataclass
class Argument:
    """An argument in a Socratic debate."""
    agent_id: str
    position: str  # "thesis" or "antithesis"
    content: str
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.5
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DebateState:
    """State of a Socratic debate session."""
    proposition: str
    proposition_id: str
    arguments: List[Argument] = field(default_factory=list)
    dialectical_entropy: float = 1.0
    round_count: int = 0
    max_rounds: int = 5
    resolution: Optional[str] = None
    consensus_reached: bool = False


class SocraticDebateAgent(BaseAgent):
    """
    Agent that moderates Socratic debates between conflicting hypotheses.
    
    Implements v2.1 specification:
    - Instantiates debate when entropy > 0.4
    - Monitors argument quality via semantic distance
    - Detects logical fallacies
    - Guides toward evidence-based resolution
    """
    
    def __init__(self):
        super().__init__(name="SocraticDebateAgent")
        self._active_debates: Dict[str, DebateState] = {}
    
    async def run(self, context: AgentContext) -> AgentContext:
        """Check for high-entropy propositions and initiate debates."""
        # Find propositions needing debate
        high_entropy = self._find_high_entropy_propositions()
        
        for prop in high_entropy:
            if prop['id'] not in self._active_debates:
                await self.initiate_debate(prop['id'], prop['content'])
        
        # Continue active debates
        for debate_id in list(self._active_debates.keys()):
            debate = self._active_debates[debate_id]
            if not debate.consensus_reached:
                await self._conduct_round(debate)
        
        return context
    
    def _find_high_entropy_propositions(self) -> List[Dict]:
        """Query TypeDB for high entropy hypotheses."""
        try:
            return self.db.get_high_entropy_hypotheses(config.entropy_threshold)
        except Exception as e:
            logger.warning(f"Could not query hypotheses: {e}")
            return []
    
    async def initiate_debate(self, proposition_id: str, content: str) -> DebateState:
        """Start a new Socratic debate session."""
        logger.info(f"Initiating debate on: {content[:50]}...")
        
        debate = DebateState(
            proposition=content,
            proposition_id=proposition_id,
            dialectical_entropy=1.0,  # Start with max uncertainty
        )
        
        self._active_debates[proposition_id] = debate
        
        # Generate initial thesis and antithesis
        await self._generate_initial_positions(debate)
        
        return debate
    
    async def _generate_initial_positions(self, debate: DebateState):
        """Generate thesis and antithesis for the debate."""
        # Generate thesis (supporting argument)
        thesis_prompt = f"""
You are arguing IN FAVOR of the following proposition:
"{debate.proposition}"

Present a strong argument with evidence. Be specific and cite potential sources.
"""
        thesis_content = self.generate(thesis_prompt, temperature=0.5)
        
        debate.arguments.append(Argument(
            agent_id="thesis-agent",
            position="thesis",
            content=thesis_content,
            confidence=0.6,
        ))
        
        # Generate antithesis (opposing argument)
        antithesis_prompt = f"""
You are arguing AGAINST the following proposition:
"{debate.proposition}"

Present a strong counter-argument with evidence. Be specific and cite potential issues.
"""
        antithesis_content = self.generate(antithesis_prompt, temperature=0.5)
        
        debate.arguments.append(Argument(
            agent_id="antithesis-agent",
            position="antithesis",
            content=antithesis_content,
            confidence=0.6,
        ))
    
    async def _conduct_round(self, debate: DebateState):
        """Conduct one round of debate."""
        debate.round_count += 1
        logger.info(f"Debate round {debate.round_count} for: {debate.proposition[:30]}...")
        
        if debate.round_count > debate.max_rounds:
            await self._force_resolution(debate)
            return
        
        # Analyze current state
        thesis_args = [a for a in debate.arguments if a.position == "thesis"]
        antithesis_args = [a for a in debate.arguments if a.position == "antithesis"]
        
        # Calculate new entropy based on argument strengths
        debate.dialectical_entropy = self._calculate_debate_entropy(thesis_args, antithesis_args)
        
        # Check for convergence
        if debate.dialectical_entropy < 0.2:
            await self._resolve_debate(debate)
            return
        
        # Check for logical fallacies
        fallacies = self._detect_fallacies(debate.arguments[-2:])
        if fallacies:
            await self._intervene_as_moderator(debate, fallacies)
        
        # Generate rebuttals
        await self._generate_rebuttals(debate)
    
    def _calculate_debate_entropy(
        self, 
        thesis_args: List[Argument], 
        antithesis_args: List[Argument]
    ) -> float:
        """Calculate dialectical entropy from argument distribution."""
        if not thesis_args and not antithesis_args:
            return 1.0
        
        # Weight by recency and confidence
        thesis_weight = sum(a.confidence for a in thesis_args[-3:])
        antithesis_weight = sum(a.confidence for a in antithesis_args[-3:])
        
        total = thesis_weight + antithesis_weight
        if total == 0:
            return 1.0
        
        p = thesis_weight / total
        
        # Shannon entropy
        import math
        if p <= 0 or p >= 1:
            return 0.0
        
        entropy = -p * math.log2(p) - (1 - p) * math.log2(1 - p)
        return entropy
    
    def _detect_fallacies(self, recent_args: List[Argument]) -> List[str]:
        """Detect logical fallacies in recent arguments."""
        fallacies = []
        
        if len(recent_args) < 2:
            return fallacies
        
        # Check for circular reasoning (same content repeated)
        if recent_args[0].content[:100] == recent_args[1].content[:100]:
            fallacies.append("circular_reasoning")
        
        # Use LLM to detect more subtle fallacies
        detection_prompt = f"""
Analyze these two debate arguments for logical fallacies:

Argument 1: {recent_args[0].content[:500]}

Argument 2: {recent_args[1].content[:500]}

List any fallacies found (e.g., ad hominem, straw man, false dichotomy).
If none found, respond with "NONE".
"""
        result = self.generate(detection_prompt, temperature=0.2)
        
        if "NONE" not in result.upper():
            fallacies.append(result)
        
        return fallacies
    
    async def _intervene_as_moderator(self, debate: DebateState, fallacies: List[str]):
        """Moderator intervention to correct debate course."""
        logger.warning(f"Moderator intervention: {fallacies}")
        
        intervention_prompt = f"""
As a Socratic moderator, you've detected the following issues in the debate:
{fallacies}

The proposition being debated is: "{debate.proposition}"

Provide guidance to redirect the debate toward evidence-based argumentation.
Be constructive and specific.
"""
        guidance = self.generate(intervention_prompt, system="You are a fair debate moderator.")
        
        debate.arguments.append(Argument(
            agent_id="moderator",
            position="guidance",
            content=guidance,
            confidence=1.0,
        ))
    
    async def _generate_rebuttals(self, debate: DebateState):
        """Generate rebuttals from both sides."""
        last_thesis = next((a for a in reversed(debate.arguments) if a.position == "thesis"), None)
        last_antithesis = next((a for a in reversed(debate.arguments) if a.position == "antithesis"), None)
        
        if last_antithesis:
            # Thesis rebuts antithesis
            rebuttal_prompt = f"""
Respond to this counter-argument against the proposition "{debate.proposition}":

Counter-argument: {last_antithesis.content[:500]}

Provide a rebuttal with new evidence or reasoning.
"""
            rebuttal = self.generate(rebuttal_prompt, temperature=0.5)
            debate.arguments.append(Argument(
                agent_id="thesis-agent",
                position="thesis",
                content=rebuttal,
                confidence=0.5 + 0.1 * debate.round_count,
            ))
        
        if last_thesis:
            # Antithesis rebuts thesis
            rebuttal_prompt = f"""
Respond to this argument supporting the proposition "{debate.proposition}":

Argument: {last_thesis.content[:500]}

Provide a counter-argument with new evidence or reasoning.
"""
            rebuttal = self.generate(rebuttal_prompt, temperature=0.5)
            debate.arguments.append(Argument(
                agent_id="antithesis-agent",
                position="antithesis",
                content=rebuttal,
                confidence=0.5 + 0.1 * debate.round_count,
            ))
    
    async def _resolve_debate(self, debate: DebateState):
        """Resolve debate when entropy is low enough."""
        logger.info(f"Resolving debate with entropy {debate.dialectical_entropy:.3f}")
        
        # Determine winner
        thesis_weight = sum(a.confidence for a in debate.arguments if a.position == "thesis")
        antithesis_weight = sum(a.confidence for a in debate.arguments if a.position == "antithesis")
        
        if thesis_weight > antithesis_weight:
            debate.resolution = "verified"
        else:
            debate.resolution = "refuted"
        
        debate.consensus_reached = True
        
        # Update belief in TypeDB
        try:
            query = f"""
            match
                $h isa hypothesis,
                    has entity-id "{debate.proposition_id}";
            delete
                $h has belief-state $old;
            insert
                $h has belief-state "{debate.resolution}";
            """
            self.db.query_delete(query)
        except Exception as e:
            logger.error(f"Failed to update belief state: {e}")
        
        logger.info(f"Debate resolved: {debate.resolution}")
    
    async def _force_resolution(self, debate: DebateState):
        """Force resolution after max rounds."""
        logger.warning(f"Forcing resolution after {debate.max_rounds} rounds")
        
        # Synthesize from all arguments
        synthesis_prompt = f"""
Synthesize a final conclusion for this debate:

Proposition: "{debate.proposition}"

Arguments for: {[a.content[:200] for a in debate.arguments if a.position == "thesis"][-2:]}

Arguments against: {[a.content[:200] for a in debate.arguments if a.position == "antithesis"][-2:]}

Provide a balanced conclusion with confidence level (0-1).
"""
        synthesis = self.generate(synthesis_prompt)
        
        debate.resolution = "debated"  # Inconclusive
        debate.consensus_reached = True
        
        debate.arguments.append(Argument(
            agent_id="synthesizer",
            position="synthesis",
            content=synthesis,
            confidence=0.5,
        ))
    
    def get_active_debates(self) -> Dict[str, DebateState]:
        """Get all active debate sessions."""
        return {k: v for k, v in self._active_debates.items() if not v.consensus_reached}
    
    def get_debate_summary(self, proposition_id: str) -> Optional[Dict]:
        """Get summary of a specific debate."""
        debate = self._active_debates.get(proposition_id)
        if not debate:
            return None
        
        return {
            "proposition": debate.proposition,
            "rounds": debate.round_count,
            "entropy": debate.dialectical_entropy,
            "resolution": debate.resolution,
            "consensus": debate.consensus_reached,
            "argument_count": len(debate.arguments),
        }


# Global instance
socratic_agent = SocraticDebateAgent()
