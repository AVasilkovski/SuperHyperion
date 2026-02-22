"""
LangGraph State Definition

Defines the state schema for the SuperHyperion agent workflow.
v2.1: Adds EpistemicMode, Evidence, and ScientificUncertainty for
      the 13-step scientific reasoning architecture.
"""

import operator
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, TypedDict


class NodeType(str, Enum):
    """Types of nodes in the workflow."""

    # Speculative lane
    CLARIFY = "clarify"
    DECOMPOSE = "decompose"
    SPECULATE = "speculate"
    PROPOSE_TESTS = "propose_tests"
    # Grounded lane
    GROUND = "ground"
    VALIDATE = "validate"  # CodeAct - BELIEF GATEKEEPER
    BENCHMARK = "benchmark"
    UNCERTAINTY = "uncertainty"
    CRITIQUE = "critique"
    META_CRITIC = "meta_critic"
    # Shared
    INTEGRATE = "integrate"
    STEWARD = "steward"
    # Legacy (kept for compatibility)
    RETRIEVE = "retrieve"
    PLAN = "plan"
    CODEACT = "codeact_execute"
    REFLECT = "reflect"
    DEBATE = "debate"
    SYNTHESIZE = "synthesize"


# =============================================================================
# v2.1 Epistemic Types
# =============================================================================

# EpistemicMode: determines which lane the agent is operating in
EpistemicMode = Literal["grounded", "speculative"]


@dataclass
class ScientificUncertainty:
    """
    Scientific uncertainty (NOT rhetorical disagreement).

    Components:
        variance: Statistical variance of results
        sensitivity: Sensitivity to assumptions
        sample_size: Number of observations/experiments
        model_fit_error: Residual error from model fitting
        confidence_interval: (lower, upper) bounds
    """

    variance: float = 0.0
    sensitivity: float = 0.0
    sample_size: int = 0
    model_fit_error: float = 0.0
    confidence_interval: tuple = (0.0, 1.0)

    def total(self) -> float:
        """Calculate total scientific uncertainty."""
        if self.sample_size == 0:
            return 1.0  # Maximum uncertainty
        return (self.variance * self.sensitivity) / (self.sample_size**0.5) + self.model_fit_error


@dataclass
class Evidence:
    """
    v2.2: Links belief updates to template execution.

    INVARIANT: No belief update is legal without an Evidence object
    that references a successful template execution.
    """

    hypothesis_id: str
    claim_id: Optional[str] = None
    template_id: str = "codeact_v1"
    template_qid: Optional[str] = "codeact_v1@1.0.0"  # Phase 14.5: Qualified template ID
    scope_lock_id: Optional[str] = None  # Phase 14.5: Scope lock ID
    test_description: str = ""
    execution_id: str = ""
    codeact_execution_id: Optional[int] = None  # v2.1: traceability to CodeAct executor
    result: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)

    # v2.2 Phase 13 Fields
    estimate: float = 0.0
    ci_95: Tuple[float, float] = (0.0, 0.0)
    variance: float = 0.0
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    sensitivity: Dict[str, Any] = field(default_factory=dict)
    supports_claim: bool = False
    is_fragile: bool = False
    feynman: Dict[str, Any] = field(default_factory=dict)

    uncertainty: Optional[ScientificUncertainty] = None
    assumptions: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    success: bool = False

    def authorizes_update(self) -> bool:
        """Check if this evidence authorizes a belief update."""
        if not self.success:
            return False
        if not self.execution_id:
            return False
        if any("CRITICAL" in w for w in self.warnings):
            return False
        return True


# =============================================================================
# Original v1 Types (kept for compatibility)
# =============================================================================


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

    v2.1: Extended with epistemic mode, evidence chain, and scientific uncertainty.
    """

    # =========================================================================
    # v2.1 Epistemic Fields (CRITICAL)
    # =========================================================================

    # Which lane: "grounded" (can update beliefs) or "speculative" (cannot)
    epistemic_mode: EpistemicMode

    # Evidence chain: REQUIRED for belief updates
    # INVARIANT: No belief update without Evidence.authorizes_update() == True
    evidence: List[Dict[str, Any]]

    # Atomic claims decomposed from hypothesis
    atomic_claims: List[Dict[str, Any]]

    # Context from grounded lane (TypeDB)
    grounded_context: Dict[str, Any]

    # Context from speculative lane (Vector DB)
    speculative_context: Dict[str, Any]

    # Scientific uncertainty (replaces dialectical_entropy)
    scientific_uncertainty: Dict[str, float]

    # Dual outputs from Integrator
    grounded_response: Optional[str]
    speculative_alternatives: List[Dict[str, Any]]

    # HITL pending decisions
    pending_hitl_decisions: List[Dict[str, Any]]
    approved_transitions: List[Dict[str, Any]]

    # =========================================================================
    # v2.2 Monte Carlo & Hardening Fields
    # =========================================================================

    # Monotonic step counter for tracing
    step_index: int
    traces: List[Dict[str, Any]]

    # Retrieval Loop Control
    reground_attempts: int
    retrieval_grade: Dict[str, float]
    retrieval_decision: str
    retrieval_refinement: Optional[Dict[str, Any]]

    # Monte Carlo Artifacts
    template_executions: List[Dict[str, Any]]
    verification_report: Dict[str, Any]
    fragility_report: Dict[str, Any]
    contradictions: Dict[str, Any]

    # Epistemic Decision artifacts
    meta_critique: Dict[str, Any]
    epistemic_update_proposal: List[Dict[str, Any]]

    # Staged Writes (Executor only)
    write_intents: List[Dict[str, Any]]
    approved_write_intents: List[Dict[str, Any]]

    # Phase 16.4: Governance summary (required for fail-closed integrate)
    governance: Optional[Dict[str, Any]]

    # Phase 16.6: Run Capsule (reproducibility artifact)
    run_capsule: Optional[Dict[str, Any]]
    session_id: Optional[str]
    tenant_id: Optional[str]

    # =========================================================================
    # Original v1 Fields (kept for compatibility)
    # =========================================================================

    # Conversation history
    messages: Annotated[List[Dict[str, str]], operator.add]

    # Current user query
    query: str

    # Retrieved context from knowledge graph (legacy)
    graph_context: Dict[str, Any]

    # Entities retrieved from TypeDB
    entities: List[Dict[str, Any]]

    # Hypotheses being evaluated
    hypotheses: List[Dict[str, Any]]

    # Code execution history
    code_executions: List[Dict[str, Any]]

    # Current plan/reasoning
    plan: str

    # Dialectical entropy score (DEPRECATED: use scientific_uncertainty)
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


def create_initial_state(
    query: str,
    session_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> AgentState:
    """Create initial state for a new query."""
    import uuid

    sid = session_id or f"sess-{uuid.uuid4().hex[:8]}"
    tid = tenant_id or "default"
    return AgentState(
        # v2.1 Epistemic Fields
        epistemic_mode="speculative",  # Start in speculative lane
        evidence=[],
        atomic_claims=[],
        grounded_context={},
        speculative_context={},
        scientific_uncertainty={
            "variance": 0.0,
            "sensitivity": 0.0,
            "sample_size": 0,
            "model_fit_error": 0.0,
        },
        grounded_response=None,
        speculative_alternatives=[],
        pending_hitl_decisions=[],
        approved_transitions=[],
        # v2.2 Fields
        step_index=0,
        traces=[],
        reground_attempts=0,
        retrieval_grade={"coverage": 0.0, "provenance": 0.0, "conflict_density": 0.0},
        retrieval_decision="speculate",
        retrieval_refinement=None,
        template_executions=[],
        verification_report={},
        fragility_report={},
        contradictions={},
        meta_critique={},
        epistemic_update_proposal=[],
        write_intents=[],
        approved_write_intents=[],
        governance=None,  # Phase 16.4: set by governance_gate_node
        run_capsule=None,
        session_id=sid,
        tenant_id=tid,
        # Original v1 Fields
        messages=[{"role": "user", "content": query}],
        query=query,
        graph_context={"session_id": sid, "tenant_id": tid},
        entities=[],
        hypotheses=[],
        code_executions=[],
        plan="",
        dialectical_entropy=0.0,
        in_debate=False,
        critique=None,
        response=None,
        current_node=NodeType.CLARIFY.value,  # v2.1: Start with clarify
        error=None,
        iteration=0,
    )


def add_message(state: AgentState, role: str, content: str) -> AgentState:
    """Add a message to the state."""
    state["messages"].append({"role": role, "content": content})
    return state


def add_code_execution(
    state: AgentState, code: str, result: str, success: bool, execution_id: int
) -> AgentState:
    """Add a code execution record to the state."""
    state["code_executions"].append(
        {
            "code": code,
            "result": result,
            "success": success,
            "execution_id": execution_id,
        }
    )
    return state
