"""
LangGraph Workflow Definition

Defines the agent workflow graph with nodes and conditional edges.
Implements the CodeAct paradigm with Socratic debate triggering.
"""

import logging
from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.agents import execute_python
from src.config import config
from src.db import typedb
from src.graph.state import AgentState, NodeType, create_initial_state
from src.llm import ollama

logger = logging.getLogger(__name__)


# ============================================
# Node Functions
# ============================================

def retrieve_node(state: AgentState) -> AgentState:
    """
    Retrieve relevant context from the knowledge graph.
    """
    logger.info("Executing: Retrieve Node")
    state["current_node"] = NodeType.RETRIEVE.value

    _query = state["query"]  # Used for context, retrieval uses fixed TypeQL

    # Generate embedding for semantic search (if available)
    try:
        # Query TypeDB for relevant entities
        typeql = """
        match
            $c isa concept, has label $label;
        fetch
            $c: label, definition;
        limit 10;
        """
        entities = typedb.query_fetch(typeql)
        state["entities"] = entities
        state["graph_context"]["retrieved_entities"] = len(entities)

    except Exception as e:
        logger.warning(f"Graph retrieval failed: {e}")
        state["entities"] = []

    state["messages"].append({
        "role": "system",
        "content": f"Retrieved {len(state['entities'])} entities from knowledge graph."
    })

    return state


def plan_node(state: AgentState) -> AgentState:
    """
    Plan the approach to answer the query.
    Uses LLM to create a reasoning plan.
    """
    logger.info("Executing: Plan Node")
    state["current_node"] = NodeType.PLAN.value

    # Build context
    context = f"""
Query: {state['query']}

Retrieved Entities: {len(state['entities'])}
{state['entities'][:5] if state['entities'] else 'None'}

Previous Code Executions: {len(state['code_executions'])}
"""

    system_prompt = """You are a scientific reasoning agent. 
Your task is to plan how to verify or investigate the user's query.
Think step by step about what computations or graph queries are needed.
Output a clear, numbered plan."""

    plan = ollama.generate(
        prompt=f"Create a plan to address this:\n{context}",
        system=system_prompt,
        temperature=0.3,
    ).content

    state["plan"] = plan
    state["messages"].append({
        "role": "assistant",
        "content": f"**Plan:**\n{plan}"
    })

    return state


def codeact_execute_node(state: AgentState) -> AgentState:
    """
    Execute Python code to verify claims.
    This is the core CodeAct node.
    """
    logger.info("Executing: CodeAct Node")
    state["current_node"] = NodeType.CODEACT.value

    # Generate code based on plan
    code_prompt = f"""
Based on this plan:
{state['plan']}

Write Python code to execute the next step. You have access to:
- numpy (as np)
- pandas (as pd)
- statistics
- math

Output ONLY the Python code, no explanations.
"""

    system_prompt = """You are a CodeAct agent that thinks in Python.
Write executable Python code to solve problems.
NEVER use markdown code blocks - output raw Python only.
Focus on statistical analysis and data manipulation.
Print your results clearly."""

    code = ollama.generate(
        prompt=code_prompt,
        system=system_prompt,
        temperature=0.2,
    ).content

    # Clean up any markdown artifacts
    code = code.replace("```python", "").replace("```", "").strip()

    # Execute the code
    result = execute_python(code)

    state["code_executions"].append({
        "code": code,
        "result": result.get("output", ""),
        "success": result.get("success", False),
        "error": result.get("error"),
    })

    state["messages"].append({
        "role": "code",
        "content": code
    })
    state["messages"].append({
        "role": "result",
        "content": result.get("output", result.get("error", "No output"))
    })

    return state


def critique_node(state: AgentState) -> AgentState:
    """
    Critique the current reasoning and results.
    The Socratic Critic challenges assumptions.
    """
    logger.info("Executing: Critique Node")
    state["current_node"] = NodeType.CRITIQUE.value

    # Summarize what we've done
    executions_summary = "\n".join([
        f"Code {i+1}: {ex.get('result', 'no result')[:200]}"
        for i, ex in enumerate(state["code_executions"][-3:])
    ])

    critique_prompt = f"""
Query: {state['query']}
Plan: {state['plan']}
Results: {executions_summary}

As a Socratic critic, identify:
1. Assumptions that weren't validated
2. Alternative interpretations
3. Missing evidence
4. Potential contradictions

Rate the confidence (0-1) and calculate dialectical entropy.
"""

    system_prompt = """You are a Socratic Critic. Your job is to challenge reasoning.
Be constructively skeptical. Identify gaps and assumptions.
End with: ENTROPY_SCORE: [0.0-1.0]"""

    critique = ollama.generate(
        prompt=critique_prompt,
        system=system_prompt,
        temperature=0.4,
    ).content

    state["critique"] = critique

    # Extract entropy score
    try:
        import re
        match = re.search(r'ENTROPY_SCORE:\s*([\d.]+)', critique)
        if match:
            state["dialectical_entropy"] = float(match.group(1))
    except Exception:
        pass

    state["messages"].append({
        "role": "critique",
        "content": critique
    })

    return state


def debate_node(state: AgentState) -> AgentState:
    """
    Socratic debate when entropy is high.
    Multiple perspectives argue the evidence.
    """
    logger.info("Executing: Debate Node (High Entropy)")
    state["current_node"] = NodeType.DEBATE.value
    state["in_debate"] = True

    debate_prompt = f"""
A debate is needed due to high uncertainty.

Query: {state['query']}
Current Position: {state['plan']}
Critique: {state['critique']}

Present two opposing arguments:
THESIS: [Argument supporting the current position]
ANTITHESIS: [Argument against the current position]
SYNTHESIS: [Reconciled understanding]
"""

    system_prompt = """You are facilitating a Socratic debate.
Present balanced thesis and antithesis, then synthesize.
Be rigorous and evidence-based."""

    debate = ollama.generate(
        prompt=debate_prompt,
        system=system_prompt,
        temperature=0.5,
    ).content

    state["messages"].append({
        "role": "debate",
        "content": debate
    })

    # Lower entropy after debate
    state["dialectical_entropy"] *= 0.5
    state["in_debate"] = False

    return state


def reflect_node(state: AgentState) -> AgentState:
    """
    Reflect on the process and update beliefs.
    """
    logger.info("Executing: Reflect Node")
    state["current_node"] = NodeType.REFLECT.value
    state["iteration"] += 1

    # Check if we need more iterations
    if state["iteration"] < 3 and state["dialectical_entropy"] > 0.3:
        # Will loop back through conditional edge
        pass

    return state


def synthesize_node(state: AgentState) -> AgentState:
    """
    Synthesize final response from all gathered evidence.
    """
    logger.info("Executing: Synthesize Node")
    state["current_node"] = NodeType.SYNTHESIZE.value

    # Gather all evidence
    messages_summary = "\n".join([
        f"[{m['role']}]: {m['content'][:300]}"
        for m in state["messages"][-10:]
    ])

    synth_prompt = f"""
Synthesize a final response to: {state['query']}

Evidence Collected:
{messages_summary}

Dialectical Entropy: {state['dialectical_entropy']:.3f}
Iterations: {state['iteration']}

Provide a clear, well-reasoned response with confidence assessment.
"""

    response = ollama.generate(
        prompt=synth_prompt,
        system="You are synthesizing scientific findings. Be clear and cite evidence.",
        temperature=0.3,
    ).content

    state["response"] = response
    state["messages"].append({
        "role": "assistant",
        "content": response
    })

    return state


# ============================================
# Conditional Edge Functions
# ============================================

def check_entropy(state: AgentState) -> Literal["debate", "synthesize", "reflect"]:
    """
    Check if entropy requires debate or if we can synthesize.
    """
    entropy = state["dialectical_entropy"]
    iteration = state["iteration"]

    if entropy > config.entropy_threshold:
        logger.info(f"High entropy ({entropy:.3f}) - routing to debate")
        return "debate"
    elif iteration >= 3 or entropy < 0.2:
        logger.info(f"Ready to synthesize (entropy={entropy:.3f}, iter={iteration})")
        return "synthesize"
    else:
        logger.info(f"Need more reflection (entropy={entropy:.3f}, iter={iteration})")
        return "reflect"


def should_continue_codeact(state: AgentState) -> Literal["critique", "codeact_execute"]:
    """
    Check if we need more code execution or can move to critique.
    """
    executions = len(state["code_executions"])

    if executions >= 3:
        return "critique"

    # Check if last execution was successful
    if state["code_executions"] and state["code_executions"][-1].get("success"):
        return "critique"

    return "codeact_execute"


# ============================================
# Graph Builder
# ============================================

def build_workflow() -> StateGraph:
    """
    Build the LangGraph workflow.
    
    Flow:
    Retrieve -> Plan -> CodeAct -> Critique -> [Debate if entropy > 0.4] -> Synthesize
    """
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("codeact_execute", codeact_execute_node)
    workflow.add_node("critique", critique_node)
    workflow.add_node("debate", debate_node)
    workflow.add_node("reflect", reflect_node)
    workflow.add_node("synthesize", synthesize_node)

    # Set entry point
    workflow.set_entry_point("retrieve")

    # Add edges
    workflow.add_edge("retrieve", "plan")
    workflow.add_edge("plan", "codeact_execute")
    workflow.add_conditional_edges(
        "codeact_execute",
        should_continue_codeact,
        {
            "critique": "critique",
            "codeact_execute": "codeact_execute",
        }
    )
    workflow.add_conditional_edges(
        "critique",
        check_entropy,
        {
            "debate": "debate",
            "synthesize": "synthesize",
            "reflect": "reflect",
        }
    )
    workflow.add_edge("debate", "reflect")
    workflow.add_edge("reflect", "plan")  # Loop back for more reasoning
    workflow.add_edge("synthesize", END)

    return workflow


# Create compiled workflow
memory = MemorySaver()
workflow = build_workflow()
app = workflow.compile(checkpointer=memory)


async def run_query(query: str, thread_id: str = "default") -> AgentState:
    """
    Run a query through the workflow.
    
    Args:
        query: User's question or claim to investigate
        thread_id: Thread ID for checkpointing
        
    Returns:
        Final agent state with response
    """
    initial_state = create_initial_state(query)
    config = {"configurable": {"thread_id": thread_id}}

    final_state = await app.ainvoke(initial_state, config)
    return final_state


if __name__ == "__main__":
    import asyncio

    async def test():
        result = await run_query("What is the relationship between sleep and memory?")
        print(f"\nResponse: {result['response']}")
        print(f"Entropy: {result['dialectical_entropy']:.3f}")
        print(f"Iterations: {result['iteration']}")

    asyncio.run(test())
