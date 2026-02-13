"""
Monte Carlo Module

v2.2: Safe Monte Carlo execution with callable templates.
LLM selects template_id + params only. Templates are vetted Python callables.

CRITICAL: No exec(), no eval(), no dynamic imports.
"""

from .templates import (
    BayesianUpdateTemplate,
    BootstrapCITemplate,
    CitationCheckTemplate,
    ContradictionDetectTemplate,
    EffectDirectionTemplate,
    NumericConsistencyTemplate,
    SensitivitySuiteTemplate,
    Template,
    TemplateExecution,
    TemplateRegistry,
    ThresholdCheckTemplate,
    registry,
)

__all__ = [
    "registry",
    "TemplateRegistry",
    "TemplateExecution",
    "Template",
    "BootstrapCITemplate",
    "BayesianUpdateTemplate",
    "ThresholdCheckTemplate",
    "NumericConsistencyTemplate",
    "SensitivitySuiteTemplate",
    "ContradictionDetectTemplate",
    "CitationCheckTemplate",
    "EffectDirectionTemplate",
]

