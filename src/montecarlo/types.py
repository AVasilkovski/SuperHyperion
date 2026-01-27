
from pydantic import BaseModel, Field, model_validator
from typing import Dict, Any, Tuple, Optional, Literal, List
import hashlib
import json


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
    
    # GUARD MARKER: Always "speculative" - Steward will reject if this leaks
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
    """
    claim_id: str
    hypothesis: str

    template_id: Literal[
        "bootstrap_ci",
        "bayesian_update",
        "numeric_consistency",
        "sensitivity_suite",
        "effect_direction",
        "citation_check",
        "contradiction_detect",
        "threshold_check",
    ]

    params: Dict[str, Any] = Field(default_factory=dict)

    # Feynman hooks
    units: Optional[Dict[str, str]] = None          # e.g., {"estimate": "mg/dL"}
    assumptions: Optional[Dict[str, Any]] = None    # e.g., {"independence_assumed": True}
    analytic_sanity: Optional[Dict[str, Any]] = None # optional baseline formula / bounds

    model_config = {"extra": "forbid"}  # Reject unknown fields

    @model_validator(mode="before")
    @classmethod
    def reject_speculative_residue(cls, data: Any) -> Any:
        """
        Enforce no-residue invariant: speculative content must not leak into specs.
        
        This catches leakage BEFORE it reaches the Steward, failing fast.
        """
        def contains_speculative(obj: Any, path: str = "") -> Optional[str]:
            """Recursively check for speculative markers at any depth."""
            if isinstance(obj, dict):
                # Check for speculative status
                if obj.get("epistemic_status") == "speculative":
                    return f"{path} contains epistemic_status='speculative'"
                # Check for forbidden fields
                for field in SPECULATIVE_RESIDUE_FIELDS:
                    if field in obj:
                        return f"{path}.{field}" if path else field
                # Recurse into values
                for key, value in obj.items():
                    result = contains_speculative(value, f"{path}.{key}" if path else key)
                    if result:
                        return result
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    result = contains_speculative(item, f"{path}[{i}]")
                    if result:
                        return result
            return None
        
        if isinstance(data, dict):
            # Top-level forbidden field check
            for field in SPECULATIVE_RESIDUE_FIELDS:
                if field in data:
                    raise ValueError(
                        f"INVARIANT VIOLATION: ExperimentSpec cannot contain '{field}'. "
                        f"Speculative content must not leak into grounded artifacts."
                    )
            # Recursive check for nested speculative content
            violation = contains_speculative(data)
            if violation:
                raise ValueError(
                    f"INVARIANT VIOLATION: ExperimentSpec contains speculative content at '{violation}'. "
                    f"Speculative content must not leak into grounded artifacts."
                )
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

