"""
Base Agent

Foundation class for all SuperHyperion agents with TypeDB and LLM connections.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.config import config
from src.db import TypeDBConnection, typedb
from src.llm import OllamaClient, ollama

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """Context passed between agent operations."""
    messages: List[Dict[str, str]] = field(default_factory=list)
    graph_context: Dict[str, Any] = field(default_factory=dict)
    code_results: List[Dict[str, Any]] = field(default_factory=list)
    dialectical_entropy: float = 0.0
    current_hypothesis: Optional[str] = None


class BaseAgent(ABC):
    """
    Base class for all SuperHyperion agents.
    
    Provides:
    - TypeDB connection for knowledge graph operations
    - Ollama client for LLM inference
    - Common agent lifecycle methods
    """

    def __init__(
        self,
        name: str,
        db: Optional[TypeDBConnection] = None,
        llm: Optional[OllamaClient] = None,
    ):
        self.name = name
        self.db = db or typedb
        self.llm = llm or ollama
        self._is_initialized = False
        logger.info(f"Agent created: {name}")

    def initialize(self):
        """Initialize agent connections."""
        if not self._is_initialized:
            self.db.connect()
            self._is_initialized = True
            logger.info(f"Agent initialized: {self.name}")

    def shutdown(self):
        """Clean up agent resources."""
        if self._is_initialized:
            self._is_initialized = False
            logger.info(f"Agent shutdown: {self.name}")

    @abstractmethod
    async def run(self, context: AgentContext) -> AgentContext:
        """
        Execute the agent's main logic.
        
        Args:
            context: Current agent context with messages and graph state
            
        Returns:
            Updated context after agent execution
        """
        pass

    def query_graph(self, query: str) -> List[Dict]:
        """Execute a TypeQL fetch query."""
        return self.db.query_fetch(query)

    def insert_to_graph(self, query: str, *, cap=None):
        """Execute a TypeQL insert query. Requires WriteCap."""
        self.db.query_insert(query, cap=cap)

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
    ) -> str:
        """Generate text using LLM."""
        response = self.llm.generate(
            prompt=prompt,
            system=system,
            temperature=temperature,
        )
        return response.content

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Chat completion with message history."""
        response = self.llm.chat(messages)
        return response.content

    def embed(self, text: str) -> List[float]:
        """Generate embedding for text."""
        return self.llm.embed(text)

    def calculate_entropy(self, probabilities: List[float]) -> float:
        """
        Calculate dialectical entropy from probability distribution.
        
        H(p) = -sum(p_i * log(p_i))
        """
        import math
        entropy = 0.0
        for p in probabilities:
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    def needs_debate(self, entropy: float) -> bool:
        """Check if entropy exceeds threshold for Socratic debate."""
        return entropy > config.entropy_threshold

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name})>"
