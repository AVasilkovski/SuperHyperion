"""
LangGraph State Definition

Defines the state schema for the SuperHyperion agent workflow.
"""

from typing import TypedDict, List, Dict, Any, Optional, Annotated
from dataclasses import dataclass, field
from enum import Enum
import operator


class NodeType(str, Enum):
    """Types of nodes in the workflow."""
    RETRIEVE = "retrieve"
    PLAN = "plan"
    CODEACT = "codeact_execute"
    CRITIQUE = "critique"
    REFLECT = "reflect"
    DEBATE = "debate"
    SYNTHESIZE = "synthesize"


@dataclass
class Message:
    """A message in the agent conversation."""
    role: str  # "user", "assistant", "system", "code", "result"
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeExecution:
    """Record of a code execution."""
    code: str
    result: str
    success: bool
    execution_id: int


@dataclass
class GraphEntity:
    """An entity from the knowledge graph."""
    entity_type: str
    id: str
    attributes: Dict[str, Any]
    relations: List[Dict[str, Any]] = field(default_factory=list)


class AgentState(TypedDict):
    """
    State passed between LangGraph nodes.
    
    This is the central state object that flows through the workflow graph.
    Each node reads from and writes to this state.
    """
    # Conversation history
    messages: Annotated[List[Dict[str, str]], operator.add]
    
    # Current user query
    query: str
    
    # Retrieved context from knowledge graph
    graph_context: Dict[str, Any]
    
    # Entities retrieved from TypeDB
    entities: List[Dict[str, Any]]
    
    # Hypotheses being evaluated
    hypotheses: List[Dict[str, Any]]
    
    # Code execution history
    code_executions: List[Dict[str, Any]]
    
    # Current plan/reasoning
    plan: str
    
    # Dialectical entropy score (triggers debate if > 0.4)
    dialectical_entropy: float
    
    # Whether we're in debate mode
    in_debate: bool
    
    # Critique from Socratic agent
    critique: Optional[str]
    
    # Final synthesized response
    response: Optional[str]
    
    # Current node in workflow
    current_node: str
    
    # Error state
    error: Optional[str]
    
    # Iteration count (to prevent infinite loops)
    iteration: int


def create_initial_state(query: str) -> AgentState:
    """Create initial state for a new query."""
    return AgentState(
        messages=[{"role": "user", "content": query}],
        query=query,
        graph_context={},
        entities=[],
        hypotheses=[],
        code_executions=[],
        plan="",
        dialectical_entropy=0.0,
        in_debate=False,
        critique=None,
        response=None,
        current_node=NodeType.RETRIEVE.value,
        error=None,
        iteration=0,
    )


def add_message(state: AgentState, role: str, content: str) -> AgentState:
    """Add a message to the state."""
    state["messages"].append({"role": role, "content": content})
    return state


def add_code_execution(
    state: AgentState, 
    code: str, 
    result: str, 
    success: bool,
    execution_id: int
) -> AgentState:
    """Add a code execution record to the state."""
    state["code_executions"].append({
        "code": code,
        "result": result,
        "success": success,
        "execution_id": execution_id,
    })
    return state
