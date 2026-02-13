
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# Constitutional Constants
QID_RE = re.compile(r"^[a-z0-9_]+@\d+\.\d+\.\d+$")

# Legacy Compatibility Shim (Time-boxed)
# MAPS TO PINNED VERSIONS ONLY. NO "LATEST".
LEGACY_TEMPLATE_TO_QID = {
    "bootstrap_ci": "bootstrap_ci@1.0.0",
    "bayesian_update": "bayesian_update@1.0.0",
    "numeric_consistency": "numeric_consistency@1.0.0",
    "sensitivity_suite": "sensitivity_suite@1.0.0",
    "effect_direction": "effect_direction@1.0.0",
    "citation_check": "citation_check@1.0.0",
    "contradiction_detect": "contradiction_detect@1.0.0",
    "threshold_check": "threshold_check@1.0.0",
}


# =============================================================================
# Speculative → Grounded Bridge Types
# =============================================================================

class PriorSuggestion(BaseModel):
    """
    A single prior suggestion derived from an analogy.
    
    Tight typing prevents garbage from sneaking in.
    """
    domain: str
    parallel: str
    suggested_prior_range: Optional[Tuple[float, float]] = None


class ExperimentHints(BaseModel):
    """
    Design hints derived from speculative outputs.
    
    INVARIANTS:
    - This is a CONTEXT-ONLY object. It MUST NOT be persisted to TypeDB.
    - It MUST NOT be embedded in Evidence payloads.
    - The Steward guard will reject any payload containing epistemic_status="speculative".
    
    This is the formal bridge between the speculative lane (hypothesis generation)
    and the grounded lane (experiment design). It converts "ideas about the world"
    into "constraints for tests about the world".
    """
    claim_id: str

    # From alternatives: mechanisms to discriminate
    candidate_mechanisms: List[str] = Field(default_factory=list)

    # From alternatives: predictions that would distinguish hypotheses
    discriminative_predictions: List[str] = Field(default_factory=list)

    # From edge_cases: axes to probe in sensitivity analysis
    sensitivity_axes: List[str] = Field(default_factory=list)

    # From analogies: prior suggestions (tightly typed, not Dict[str, Any])
    prior_suggestions: List[PriorSuggestion] = Field(default_factory=list)

    # Direct falsification criteria
    falsification_criteria: List[str] = Field(default_factory=list)

    # SENTINEL MARKER: Structural boundary for speculative lane
    # This single field is the primary enforcement mechanism
    lane: Literal["speculative"] = "speculative"

    # Legacy guard marker (kept for backward compatibility)
    epistemic_status: Literal["speculative"] = "speculative"

    def digest(self) -> str:
        """
        Compute a stable hash of the hints for audit trail logging.
        
        This allows reproducibility ("same hints → same digest") without
        persisting raw speculative content in grounded artifacts.
        """
        # Serialize deterministically
        data = {
            "claim_id": self.claim_id,
            "candidate_mechanisms": sorted(self.candidate_mechanisms),
            "discriminative_predictions": sorted(self.discriminative_predictions),
            "sensitivity_axes": sorted(self.sensitivity_axes),
            "prior_suggestions": sorted(
                [f"{p.domain}:{p.parallel}" for p in self.prior_suggestions]
            ),
            "falsification_criteria": sorted(self.falsification_criteria),
        }
        s = json.dumps(data, sort_keys=True)
        return hashlib.sha256(s.encode()).hexdigest()[:16]


# =============================================================================
# Grounded Lane Types
# =============================================================================

# Fields that indicate speculative residue - must NEVER appear in ExperimentSpec
SPECULATIVE_RESIDUE_FIELDS = {
    "lane",  # Primary sentinel marker
    "experiment_hints",
    "speculative_context",
    "epistemic_status",
    "alternatives",
    "analogies",
    "edge_cases",
}


class ExperimentSpec(BaseModel):
    """
    LLM-generated specification for a Monte Carlo experiment.
    
    INVARIANT: No speculative residue allowed. This is a grounded artifact.
    INVARIANT: Must have scope_lock_id for grounded lineage.
    """
    claim_id: str
    scope_lock_id: str  # REQUIRED for grounded execution (Constitutional Invariant)
    hypothesis: str

    # Canonical Field: Qualified ID
    template_qid: str

    # Legacy Field: Optional, used for input convenience but normalized to qid
    template_id: Optional[str] = None

    params: Dict[str, Any] = Field(default_factory=dict)

    # Feynman hooks
    units: Optional[Dict[str, str]] = None          # e.g., {"estimate": "mg/dL"}
    assumptions: Optional[Dict[str, Any]] = None    # e.g., {"independence_assumed": True}
    analytic_sanity: Optional[Dict[str, Any]] = None # optional baseline formula / bounds

    model_config = {"extra": "forbid"}  # Reject unknown fields

    @model_validator(mode="before")
    @classmethod
    def validate_constitutional_invariants(cls, data: Any) -> Any:
        """
        Single Constitutional Gate for ExperimentSpec.
        
        ORDERING CRITICAL:
        1. Reject Speculative Residue (Fast Tripwire)
        2. Normalize & Canonicalize (Whitespace hygiene)
        3. Enforce Invariants (QID, Scope Lock)
        """
        if not isinstance(data, dict):
             return data

        # ---------------------------------------------------------
        # 1. Speculative Residue Check (Fail Fast)
        # ---------------------------------------------------------
        def contains_speculative(obj: Any, path: str = "") -> Optional[str]:
            if isinstance(obj, dict):
                if obj.get("epistemic_status") == "speculative":
                    return f"{path} contains epistemic_status='speculative'"
                for field in SPECULATIVE_RESIDUE_FIELDS:
                    if field in obj:
                        return f"{path}.{field}" if path else field
                for key, value in obj.items():
                    result = contains_speculative(value, f"{path}.{key}" if path else key)
                    if result: return result
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    result = contains_speculative(item, f"{path}[{i}]")
                    if result: return result
            return None

        # Top-level check
        for field in SPECULATIVE_RESIDUE_FIELDS:
            if field in data:
                raise ValueError(f"INVARIANT VIOLATION: ExperimentSpec cannot contain '{field}'.")

        # Recursive check
        violation = contains_speculative(data)
        if violation:
            raise ValueError(f"INVARIANT VIOLATION: Speculative content found at '{violation}'.")

        # ---------------------------------------------------------
        # 2. Hygiene & Normalization
        # ---------------------------------------------------------
        # Strip whitespace (Hygiene)
        qid = data.get("template_qid") or data.get("template-qid")
        tid = data.get("template_id") or data.get("template-id")
        sid = data.get("scope_lock_id") or data.get("scope-lock-id")

        if isinstance(qid, str): qid = qid.strip() or None
        if isinstance(tid, str): tid = tid.strip() or None
        if isinstance(sid, str): sid = sid.strip() or None

        # Normalize Legacy ID -> QID
        if not qid:
            if tid and tid in LEGACY_TEMPLATE_TO_QID:
                qid = LEGACY_TEMPLATE_TO_QID[tid]
                logger.warning(f"LEGACY_TEMPLATE_ID_USED: Mapped '{tid}' to '{qid}'. Update generator!")
            elif tid:
                 # If tid present but not in map, we let it pass to regex check below which will fail
                 pass

        # Write back normalized values
        if qid: data["template_qid"] = qid
        if sid: data["scope_lock_id"] = sid

        # ---------------------------------------------------------
        # 3. Constitutional Invariants
        # ---------------------------------------------------------

        # A. Template Identity
        if not qid:
             raise ValueError(f"Missing or invalid template_qid. Legacy id '{tid}' not in pinned map.")

        if not QID_RE.match(qid):
             raise ValueError(f"Invalid template_qid format: {qid} (expected name@X.Y.Z)")

        # B. Scope Lock
        if not sid:
            raise ValueError("Constitutional Error: scope_lock_id is REQUIRED for grounded execution.")

        return data


class MCResult(BaseModel):
    """
    Structured output from a CodeAct execution of a template.
    """
    estimate: float
    ci_95: Tuple[float, float]
    variance: float
    diagnostics: Dict[str, Any]          # ESS, convergence metrics, warnings
    sensitivity: Dict[str, Any]          # prior_widened, noise_model_change, stability flags
    supports_claim: bool
    is_fragile: bool
    notes: Optional[str] = None

