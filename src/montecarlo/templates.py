"""
Template Registry v2.2

Callable templates for safe Monte Carlo/statistical execution.
LLM selects template_id + params only. Templates are vetted Python callables.

CRITICAL: No exec(), no eval(), no dynamic imports.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Type, Optional, Literal
from dataclasses import dataclass
from pydantic import BaseModel, Field, ConfigDict
import numpy as np
import logging
import time
import hashlib
import json

logger = logging.getLogger(__name__)


# =============================================================================
# Template Parameter Models (Pydantic with bounds)
# =============================================================================

class BootstrapCIParams(BaseModel):
    """Bootstrap confidence interval parameters."""
    model_config = ConfigDict(extra="forbid")
    data: List[float] = Field(..., min_length=2, max_length=5000)
    n_bootstrap: int = Field(default=2000, ge=100, le=5000)
    confidence_level: float = Field(default=0.95, ge=0.80, le=0.99)
    seed: Optional[int] = Field(default=None, ge=0, le=2**31-1)


class BayesianUpdateParams(BaseModel):
    """Bayesian posterior estimation parameters."""
    model_config = ConfigDict(extra="forbid")
    observations: List[float] = Field(..., min_length=1, max_length=5000)
    prior_mean: float = Field(default=0.0, ge=-1e6, le=1e6)
    prior_std: float = Field(default=1.0, gt=0, le=1e6)
    likelihood_std: float = Field(default=1.0, gt=0, le=1e6)
    n_samples: int = Field(default=2000, ge=100, le=5000)
    seed: Optional[int] = Field(default=None, ge=0, le=2**31-1)


class ThresholdCheckParams(BaseModel):
    """Check if values exceed threshold."""
    model_config = ConfigDict(extra="forbid")
    values: List[float] = Field(..., min_length=1, max_length=5000)
    threshold: float
    direction: Literal["above", "below"] = "above"


class NumericConsistencyParams(BaseModel):
    """Check claimed value against observations."""
    model_config = ConfigDict(extra="forbid")
    claimed_value: float
    observed_values: List[float] = Field(..., min_length=1, max_length=5000)
    tolerance: float = Field(default=0.1, ge=0, le=1e6)


class SensitivitySuiteParams(BaseModel):
    """Sensitivity analysis parameters."""
    model_config = ConfigDict(extra="forbid")
    base_result: float
    base_ci_low: float
    base_ci_high: float
    prior_widening_factor: float = Field(default=2.0, ge=1.1, le=10.0)
    n_perturbations: int = Field(default=100, ge=10, le=1000)
    seed: Optional[int] = Field(default=None, ge=0, le=2**31-1)


class ContradictionDetectParams(BaseModel):
    """Detect contradictions in evidence."""
    model_config = ConfigDict(extra="forbid")
    evidence_items: List[Dict[str, Any]] = Field(..., max_length=100)
    claim_id: str


class CitationCheckParams(BaseModel):
    """Check citation presence."""
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    evidence_bundle: List[Dict[str, Any]] = Field(..., max_length=100)


class EffectDirectionParams(BaseModel):
    """Check effect direction."""
    model_config = ConfigDict(extra="forbid")
    observations: List[float] = Field(..., min_length=2, max_length=5000)
    expected_direction: Literal["positive", "negative", "zero"]


# =============================================================================
# Template Output Models
# =============================================================================

class BootstrapCIOutput(BaseModel):
    method: str = "bootstrap_ci"
    estimate: float
    ci_low: float
    ci_high: float
    variance: float
    n_samples: int
    seed: int


class BayesianUpdateOutput(BaseModel):
    method: str = "bayesian_update"
    posterior_mean: float
    posterior_std: float
    ci_low: float
    ci_high: float
    n_samples: int
    seed: int


class ThresholdCheckOutput(BaseModel):
    method: str = "threshold_check"
    passes: bool
    value: float
    threshold: float
    margin: float
    direction: str


class NumericConsistencyOutput(BaseModel):
    method: str = "numeric_consistency"
    consistent: bool
    claimed_value: float
    observed_mean: float
    deviation: float
    within_tolerance: bool


class SensitivitySuiteOutput(BaseModel):
    method: str = "sensitivity_suite"
    flip_rate: float
    stable: bool
    fragile: bool
    n_perturbations: int
    prior_widening_factor: float


class ContradictionDetectOutput(BaseModel):
    method: str = "contradiction_detect"
    contradictions: List[Dict[str, Any]]
    unresolved_count: int
    has_conflicts: bool


class CitationCheckOutput(BaseModel):
    method: str = "citation_check"
    has_citations: bool
    citation_count: int
    sources: List[str]


class EffectDirectionOutput(BaseModel):
    method: str = "effect_direction"
    matches: bool
    actual_direction: str
    confidence: float
    mean_value: float


# =============================================================================
# Base Template Class
# =============================================================================

def sha256_json(data: Any) -> str:
    """
    Stable hash of JSON-serializable data.
    separators removes whitespace differences; sort_keys enforces stable key order.
    """
    try:
        s = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()
    except Exception:
        return "hash-error"

class Template(ABC):
    """Base class for callable templates."""
    
    template_id: str
    description: str
    ParamModel: Type[BaseModel]
    OutputModel: Type[BaseModel]
    deterministic: bool = True
    max_runtime_ms: int = 2000
    is_write_template: bool = False
    
    def validate(self, params: Dict[str, Any]) -> BaseModel:
        """Validate parameters against schema."""
        return self.ParamModel.model_validate(params)
    
    def get_seed(self, params: BaseModel, session_id: str = "", claim_id: str = "") -> int:
        """Get deterministic seed for reproducibility."""
        seed = getattr(params, "seed", None)
        if seed is not None:
            return seed
        # Deterministic seed from context
        hash_input = f"{session_id}:{claim_id}:{self.template_id}"
        return int(hashlib.sha256(hash_input.encode()).hexdigest()[:8], 16) % (2**31)
    
    @abstractmethod
    def run(self, params: BaseModel, context: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute the template. Must be implemented by subclasses."""
        pass


# =============================================================================
# Concrete Template Implementations
# =============================================================================

class BootstrapCITemplate(Template):
    template_id = "bootstrap_ci"
    description = "Estimate effect with confidence interval via bootstrap"
    ParamModel = BootstrapCIParams
    OutputModel = BootstrapCIOutput
    
    def run(self, params: BootstrapCIParams, context: Optional[Dict] = None) -> Dict[str, Any]:
        context = context or {}
        seed = self.get_seed(params, context.get("session_id", ""), context.get("claim_id", ""))
        np.random.seed(seed)
        
        data = np.array(params.data)
        n = len(data)
        
        bootstrap_means = []
        for _ in range(params.n_bootstrap):
            sample = np.random.choice(data, size=n, replace=True)
            bootstrap_means.append(np.mean(sample))
        
        bootstrap_means = np.array(bootstrap_means)
        alpha = 1 - params.confidence_level
        
        return {
            "method": "bootstrap_ci",
            "estimate": float(np.mean(bootstrap_means)),
            "ci_low": float(np.percentile(bootstrap_means, 100 * alpha / 2)),
            "ci_high": float(np.percentile(bootstrap_means, 100 * (1 - alpha / 2))),
            "variance": float(np.var(bootstrap_means)),
            "n_samples": params.n_bootstrap,
            "seed": seed,
        }


class BayesianUpdateTemplate(Template):
    template_id = "bayesian_update"
    description = "Conjugate normal-normal Bayesian posterior estimation"
    ParamModel = BayesianUpdateParams
    OutputModel = BayesianUpdateOutput
    
    def run(self, params: BayesianUpdateParams, context: Optional[Dict] = None) -> Dict[str, Any]:
        context = context or {}
        seed = self.get_seed(params, context.get("session_id", ""), context.get("claim_id", ""))
        np.random.seed(seed)
        
        observations = np.array(params.observations)
        n_obs = len(observations)
        obs_mean = np.mean(observations)
        
        prior_var = params.prior_std ** 2
        likelihood_var = params.likelihood_std ** 2
        
        posterior_var = 1.0 / (1.0 / prior_var + n_obs / likelihood_var)
        posterior_mean = posterior_var * (params.prior_mean / prior_var + n_obs * obs_mean / likelihood_var)
        posterior_std = np.sqrt(posterior_var)
        
        samples = np.random.normal(posterior_mean, posterior_std, params.n_samples)
        
        return {
            "method": "bayesian_update",
            "posterior_mean": float(posterior_mean),
            "posterior_std": float(posterior_std),
            "ci_low": float(np.percentile(samples, 2.5)),
            "ci_high": float(np.percentile(samples, 97.5)),
            "n_samples": params.n_samples,
            "seed": seed,
        }


class ThresholdCheckTemplate(Template):
    template_id = "threshold_check"
    description = "Check if metric exceeds threshold"
    ParamModel = ThresholdCheckParams
    OutputModel = ThresholdCheckOutput
    deterministic = True
    
    def run(self, params: ThresholdCheckParams, context: Optional[Dict] = None) -> Dict[str, Any]:
        context = context or {}
        values = np.array(params.values)
        mean_val = float(np.mean(values))
        
        if params.direction == "above":
            passes = mean_val > params.threshold
            margin = mean_val - params.threshold
        else:
            passes = mean_val < params.threshold
            margin = params.threshold - mean_val
        
        return {
            "method": "threshold_check",
            "passes": passes,
            "value": mean_val,
            "threshold": params.threshold,
            "margin": float(margin),
            "direction": params.direction,
        }


class NumericConsistencyTemplate(Template):
    template_id = "numeric_consistency"
    description = "Verify claimed numeric value against observed data"
    ParamModel = NumericConsistencyParams
    OutputModel = NumericConsistencyOutput
    deterministic = True
    
    def run(self, params: NumericConsistencyParams, context: Optional[Dict] = None) -> Dict[str, Any]:
        context = context or {}
        observed = np.array(params.observed_values)
        observed_mean = float(np.mean(observed))
        deviation = abs(params.claimed_value - observed_mean)
        
        return {
            "method": "numeric_consistency",
            "consistent": deviation <= params.tolerance,
            "claimed_value": params.claimed_value,
            "observed_mean": observed_mean,
            "deviation": deviation,
            "within_tolerance": deviation <= params.tolerance,
        }


class SensitivitySuiteTemplate(Template):
    template_id = "sensitivity_suite"
    description = "Prior perturbation analysis for fragility detection"
    ParamModel = SensitivitySuiteParams
    OutputModel = SensitivitySuiteOutput
    
    def run(self, params: SensitivitySuiteParams, context: Optional[Dict] = None) -> Dict[str, Any]:
        context = context or {}
        seed = self.get_seed(params, context.get("session_id", ""), context.get("claim_id", ""))
        np.random.seed(seed)
        
        flip_count = 0
        base_supports = params.base_ci_low > 0 or params.base_ci_high < 0
        
        for _ in range(params.n_perturbations):
            noise = np.random.normal(0, params.prior_widening_factor * 0.1)
            perturbed = params.base_result + noise
            width = (params.base_ci_high - params.base_ci_low) * params.prior_widening_factor
            perturbed_supports = (perturbed - width/2) > 0 or (perturbed + width/2) < 0
            
            if base_supports != perturbed_supports:
                flip_count += 1
        
        flip_rate = flip_count / params.n_perturbations
        
        return {
            "method": "sensitivity_suite",
            "flip_rate": float(flip_rate),
            "stable": flip_rate < 0.15,
            "fragile": flip_rate >= 0.15,
            "n_perturbations": params.n_perturbations,
            "prior_widening_factor": params.prior_widening_factor,
        }


class ContradictionDetectTemplate(Template):
    template_id = "contradiction_detect"
    description = "Detect conflicting evidence for a claim"
    ParamModel = ContradictionDetectParams
    OutputModel = ContradictionDetectOutput
    deterministic = True
    
    def run(self, params: ContradictionDetectParams, context: Optional[Dict] = None) -> Dict[str, Any]:
        context = context or {}
        contradictions = []
        
        # Find evidence items that conflict
        supporting = [e for e in params.evidence_items if e.get("supports_claim", False)]
        refuting = [e for e in params.evidence_items if not e.get("supports_claim", True)]
        
        for s in supporting:
            for r in refuting:
                contradictions.append({
                    "supporting_id": s.get("id", "unknown"),
                    "refuting_id": r.get("id", "unknown"),
                    "claim_id": params.claim_id,
                })
        
        return {
            "method": "contradiction_detect",
            "contradictions": contradictions,
            "unresolved_count": len(contradictions),
            "has_conflicts": len(contradictions) > 0,
        }


class CitationCheckTemplate(Template):
    template_id = "citation_check"
    description = "Verify citation presence for a claim"
    ParamModel = CitationCheckParams
    OutputModel = CitationCheckOutput
    deterministic = True
    
    def run(self, params: CitationCheckParams, context: Optional[Dict] = None) -> Dict[str, Any]:
        context = context or {}
        sources = []
        
        for item in params.evidence_bundle:
            if item.get("claim_id") == params.claim_id or item.get("hypothesis_id") == params.claim_id:
                source = item.get("source", item.get("source_id", ""))
                if source:
                    sources.append(source)
        
        return {
            "method": "citation_check",
            "has_citations": len(sources) > 0,
            "citation_count": len(sources),
            "sources": sources[:10],  # Limit output size
        }


class EffectDirectionTemplate(Template):
    template_id = "effect_direction"
    description = "Check if effect direction matches expectation"
    ParamModel = EffectDirectionParams
    OutputModel = EffectDirectionOutput
    deterministic = True
    
    def run(self, params: EffectDirectionParams, context: Optional[Dict] = None) -> Dict[str, Any]:
        context = context or {}
        values = np.array(params.observations)
        mean_val = float(np.mean(values))
        std_val = float(np.std(values)) if len(values) > 1 else 0.0
        
        # Determine actual direction
        if std_val > 0 and abs(mean_val) > std_val:
            actual = "positive" if mean_val > 0 else "negative"
            confidence = min(1.0, abs(mean_val) / (std_val + 1e-9))
        else:
            actual = "zero"
            confidence = 1.0 - min(1.0, abs(mean_val) / (std_val + 1e-9)) if std_val > 0 else 1.0
        
        return {
            "method": "effect_direction",
            "matches": actual == params.expected_direction,
            "actual_direction": actual,
            "confidence": float(confidence),
            "mean_value": mean_val,
        }


# =============================================================================
# Template Registry
# =============================================================================

@dataclass
class TemplateExecution:
    """Record of a template execution for auditing."""
    execution_id: str
    template_id: str
    claim_id: str
    params: Dict[str, Any]
    result: Dict[str, Any]
    success: bool
    runtime_ms: float
    warnings: List[str]
    params_hash: Optional[str] = None
    result_hash: Optional[str] = None


class TemplateRegistry:
    """Registry of callable templates."""
    
    def __init__(self):
        self._templates: Dict[str, Template] = {}
        self._register_defaults()
    
    def _register_defaults(self):
        """Register default templates."""
        self.register(BootstrapCITemplate())
        self.register(BayesianUpdateTemplate())
        self.register(ThresholdCheckTemplate())
        self.register(NumericConsistencyTemplate())
        self.register(SensitivitySuiteTemplate())
        self.register(ContradictionDetectTemplate())
        self.register(CitationCheckTemplate())
        self.register(EffectDirectionTemplate())
    
    def register(self, template: Template):
        """Register a template."""
        self._templates[template.template_id] = template
    
    def get(self, template_id: str) -> Template:
        """Get a template by ID."""
        if template_id not in self._templates:
            raise KeyError(f"Unknown template: {template_id}. Available: {list(self._templates.keys())}")
        return self._templates[template_id]
    
    def list_templates(self) -> List[Dict[str, str]]:
        """List available templates."""
        return [
            {"id": t.template_id, "description": t.description}
            for t in self._templates.values()
        ]
    
    def run_template(
        self,
        template_id: str,
        params: Dict[str, Any],
        context: Optional[Dict] = None,
        caller_role: str = "verify",
    ) -> TemplateExecution:
        """
        Run a template with validated parameters.
        
        Returns a TemplateExecution record for auditing.
        """
        template = self.get(template_id)
        
        # Enforce write template restrictions
        if template.is_write_template and caller_role != "steward":
            raise PermissionError(f"Write template '{template_id}' can only be called by steward")
        
        context = context or {}
        warnings = []
        
        # Validate params
        try:
            validated_params = template.validate(params)
        except Exception as e:
            return TemplateExecution(
                execution_id=f"exec-{time.time_ns()}",
                template_id=template_id,
                claim_id=context.get("claim_id", "unknown"),
                params=params,
                result={"error": str(e)},
                success=False,
                runtime_ms=0,
                warnings=[f"Validation failed: {e}"],
                params_hash=sha256_json(params),
                result_hash=sha256_json({"error": str(e)}),
            )
        
        # Execute template
        start_time = time.time()
        try:
            result = template.run(validated_params, context)
            success = True
            
            # Validate output against schema (Audit requirement)
            try:
                template.OutputModel.model_validate(result)
            except Exception as e:
                success = False
                warnings.append(f"Output validation failed: {str(e)}")
                result = {"error": f"Output validation failed: {str(e)}", "raw_result": result}
                
        except Exception as e:
            logger.error(f"Template {template_id} execution failed: {e}")
            result = {"error": str(e)}
            success = False
            warnings.append(f"Execution failed: {e}")
        
        runtime_ms = (time.time() - start_time) * 1000
        
        if runtime_ms > template.max_runtime_ms:
            warnings.append(f"Exceeded max runtime: {runtime_ms:.1f}ms > {template.max_runtime_ms}ms")
            
        params_dict = validated_params.model_dump()
        params_hash = sha256_json(params_dict)
        result_hash = sha256_json(result)
        
        return TemplateExecution(
            execution_id=f"exec-{time.time_ns()}",
            template_id=template_id,
            claim_id=context.get("claim_id", "unknown"),
            params=params_dict,
            result=result,
            success=success,
            runtime_ms=runtime_ms,
            warnings=warnings,
            params_hash=params_hash,
            result_hash=result_hash,
        )


# Global registry instance
registry = TemplateRegistry()
