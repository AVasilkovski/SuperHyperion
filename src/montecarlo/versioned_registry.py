"""
Versioned Template Registry

Explicit registry of all template versions with their specs.
This is the source of truth at runtime.
"""

from typing import Dict, Type

from pydantic import BaseModel

from .template_metadata import (
    EpistemicSemantics,
    TemplateCapability,
    TemplateSpec,
    TemplateVersion,
    VersionedTemplateRegistry,
)
from .templates import (
    BayesianUpdateOutput,
    BayesianUpdateParams,
    BayesianUpdateTemplate,
    BootstrapCIOutput,
    BootstrapCIParams,
    BootstrapCITemplate,
    CitationCheckOutput,
    CitationCheckParams,
    CitationCheckTemplate,
    CodeActOutput,
    CodeActParams,
    CodeActTemplate,
    ContradictionDetectOutput,
    ContradictionDetectParams,
    ContradictionDetectTemplate,
    EffectDirectionOutput,
    EffectDirectionParams,
    EffectDirectionTemplate,
    NumericConsistencyOutput,
    NumericConsistencyParams,
    NumericConsistencyTemplate,
    SensitivitySuiteOutput,
    SensitivitySuiteParams,
    SensitivitySuiteTemplate,
    Template,
    ThresholdCheckOutput,
    ThresholdCheckParams,
    ThresholdCheckTemplate,
)


def _schema_from_model(model: Type[BaseModel]) -> Dict:
    """Extract JSON schema from Pydantic model."""
    return model.model_json_schema()


# =============================================================================
# Template Specs (Declared Contracts)
# =============================================================================

BOOTSTRAP_CI_SPEC = TemplateSpec(
    template_id="bootstrap_ci",
    version=TemplateVersion(1, 0, 0),
    description="Estimate effect with confidence interval via bootstrap resampling",
    param_schema=_schema_from_model(BootstrapCIParams),
    output_schema=_schema_from_model(BootstrapCIOutput),
    invariants=[
        "ci_low <= estimate <= ci_high",
        "variance >= 0",
        "n_samples == n_bootstrap",
        "deterministic with same seed",
    ],
    depends_on=[],
    capabilities={TemplateCapability.RANDOMNESS},
    required_tests=[
        "contract.deterministic_with_seed",
        "contract.output_schema_valid",
        "contract.ci_bounds_correct",
    ],
    deterministic=True,
    epistemic=EpistemicSemantics(
        instrument="replication",
        negative_role_on_fail="replicate",
        default_failure_mode="null_effect",
        strength_model="ci_proximity_to_null",
    ),
)

BAYESIAN_UPDATE_SPEC = TemplateSpec(
    template_id="bayesian_update",
    version=TemplateVersion(1, 0, 0),
    description="Conjugate normal-normal Bayesian posterior estimation",
    param_schema=_schema_from_model(BayesianUpdateParams),
    output_schema=_schema_from_model(BayesianUpdateOutput),
    invariants=[
        "posterior_std > 0",
        "ci_low <= posterior_mean <= ci_high",
        "deterministic with same seed",
    ],
    depends_on=[],
    capabilities={TemplateCapability.RANDOMNESS},
    required_tests=[
        "contract.deterministic_with_seed",
        "contract.output_schema_valid",
        "contract.posterior_valid",
    ],
    deterministic=True,
)

THRESHOLD_CHECK_SPEC = TemplateSpec(
    template_id="threshold_check",
    version=TemplateVersion(1, 0, 0),
    description="Check if metric exceeds threshold",
    param_schema=_schema_from_model(ThresholdCheckParams),
    output_schema=_schema_from_model(ThresholdCheckOutput),
    invariants=[
        "passes == (value > threshold if direction == 'above' else value < threshold)",
        "margin == abs(value - threshold)",
    ],
    depends_on=[],
    capabilities=set(),
    required_tests=[
        "contract.output_schema_valid",
        "contract.threshold_logic_correct",
    ],
    deterministic=True,
    epistemic=EpistemicSemantics(
        instrument="falsification",
        negative_role_on_fail="refute",
        default_failure_mode="sign_flip",
        strength_model="binary_default",
    ),
)

NUMERIC_CONSISTENCY_SPEC = TemplateSpec(
    template_id="numeric_consistency",
    version=TemplateVersion(1, 0, 0),
    description="Verify claimed numeric value against observed data",
    param_schema=_schema_from_model(NumericConsistencyParams),
    output_schema=_schema_from_model(NumericConsistencyOutput),
    invariants=[
        "within_tolerance == (deviation <= tolerance)",
        "consistent == within_tolerance",
    ],
    depends_on=[],
    capabilities=set(),
    required_tests=[
        "contract.output_schema_valid",
        "contract.consistency_logic_correct",
    ],
    deterministic=True,
    epistemic=EpistemicSemantics(
        instrument="consistency_check",
        negative_role_on_fail="undercut",
        default_failure_mode="violated_assumption",
        strength_model="binary_default",
    ),
)

SENSITIVITY_SUITE_SPEC = TemplateSpec(
    template_id="sensitivity_suite",
    version=TemplateVersion(1, 0, 0),
    description="Prior perturbation analysis for fragility detection",
    param_schema=_schema_from_model(SensitivitySuiteParams),
    output_schema=_schema_from_model(SensitivitySuiteOutput),
    invariants=[
        "0 <= flip_rate <= 1",
        "fragile == (flip_rate > 0.15)",
        "stable == (flip_rate < 0.05)",
        "n_perturbations == params.n_perturbations",
    ],
    depends_on=[],
    capabilities={TemplateCapability.RANDOMNESS},
    required_tests=[
        "contract.deterministic_with_seed",
        "contract.output_schema_valid",
        "contract.flip_rate_bounds",
    ],
    deterministic=True,
)

CONTRADICTION_DETECT_SPEC = TemplateSpec(
    template_id="contradiction_detect",
    version=TemplateVersion(1, 0, 0),
    description="Detect conflicting evidence for a claim",
    param_schema=_schema_from_model(ContradictionDetectParams),
    output_schema=_schema_from_model(ContradictionDetectOutput),
    invariants=[
        "has_conflicts == (unresolved_count > 0)",
        "len(contradictions) == unresolved_count",
    ],
    depends_on=[],
    capabilities=set(),
    required_tests=[
        "contract.output_schema_valid",
        "contract.contradiction_detection_correct",
    ],
    deterministic=True,
    epistemic=EpistemicSemantics(
        instrument="method_audit",
        negative_role_on_fail="undercut",
        default_failure_mode="violated_assumption",
        strength_model="binary_default",
    ),
)

CITATION_CHECK_SPEC = TemplateSpec(
    template_id="citation_check",
    version=TemplateVersion(1, 0, 0),
    description="Verify citation presence for a claim",
    param_schema=_schema_from_model(CitationCheckParams),
    output_schema=_schema_from_model(CitationCheckOutput),
    invariants=[
        "has_citations == (citation_count > 0)",
        "citation_count == len(sources)",
    ],
    depends_on=[],
    capabilities=set(),
    required_tests=[
        "contract.output_schema_valid",
        "contract.citation_count_correct",
    ],
    deterministic=True,
)

EFFECT_DIRECTION_SPEC = TemplateSpec(
    template_id="effect_direction",
    version=TemplateVersion(1, 0, 0),
    description="Check if effect direction matches expectation",
    param_schema=_schema_from_model(EffectDirectionParams),
    output_schema=_schema_from_model(EffectDirectionOutput),
    invariants=[
        "matches == (actual_direction == expected_direction)",
        "0 <= confidence <= 1",
    ],
    depends_on=[],
    capabilities=set(),
    required_tests=[
        "contract.output_schema_valid",
        "contract.direction_logic_correct",
    ],
    deterministic=True,
)


CODEACT_V1_SPEC = TemplateSpec(
    template_id="codeact_v1",
    version=TemplateVersion(1, 0, 0),
    description="Ad-hoc code execution for validation experiments",
    param_schema=_schema_from_model(CodeActParams),
    output_schema=_schema_from_model(CodeActOutput),
    invariants=["success is boolean"],
    depends_on=[],
    capabilities=set(),
    required_tests=[],
    deterministic=False,
)


# =============================================================================
# Build Versioned Registry
# =============================================================================


def build_versioned_registry() -> VersionedTemplateRegistry:
    """Build the versioned template registry with all known templates."""
    registry = VersionedTemplateRegistry()

    # Register all templates with their specs
    templates_specs = [
        (BootstrapCITemplate(), BOOTSTRAP_CI_SPEC),
        (BayesianUpdateTemplate(), BAYESIAN_UPDATE_SPEC),
        (ThresholdCheckTemplate(), THRESHOLD_CHECK_SPEC),
        (NumericConsistencyTemplate(), NUMERIC_CONSISTENCY_SPEC),
        (SensitivitySuiteTemplate(), SENSITIVITY_SUITE_SPEC),
        (ContradictionDetectTemplate(), CONTRADICTION_DETECT_SPEC),
        (CitationCheckTemplate(), CITATION_CHECK_SPEC),
        (EffectDirectionTemplate(), EFFECT_DIRECTION_SPEC),
        (CodeActTemplate(), CODEACT_V1_SPEC),
    ]

    for template, spec in templates_specs:
        registry.register(template, spec)

    return registry


# =============================================================================
# Explicit Registry (Source of Truth)
# =============================================================================

# This is built once at module load
VERSIONED_REGISTRY = build_versioned_registry()


def get_template(qualified_id: str) -> Template:
    """
    Get a template by qualified ID.

    Args:
        qualified_id: e.g. "bootstrap_ci@1.0.0"

    Returns:
        Template instance

    Raises:
        ValueError if not found
    """
    template = VERSIONED_REGISTRY.get(qualified_id)
    if not template:
        raise ValueError(f"Template not found: {qualified_id}")
    return template


def get_latest_template(template_id: str) -> Template:
    """
    Get the latest version of a template.

    Args:
        template_id: e.g. "bootstrap_ci"

    Returns:
        Template instance

    Raises:
        ValueError if not found
    """
    template = VERSIONED_REGISTRY.get_latest(template_id)
    if not template:
        raise ValueError(f"Template not found: {template_id}")
    return template


def list_templates() -> list:
    """List all registered template qualified IDs."""
    return VERSIONED_REGISTRY.list_all()
