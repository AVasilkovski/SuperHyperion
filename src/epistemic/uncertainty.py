"""
Scientific Uncertainty Calculation

v2.1: Replaces rhetorical entropy (LLM disagreement) with
scientific uncertainty based on variance, sensitivity, sample size,
and model fit error.
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class UncertaintyComponents:
    """Components of scientific uncertainty."""

    variance: float
    sensitivity: float
    sample_size: int
    model_fit_error: float
    confidence_interval: Tuple[float, float]

    def total(self) -> float:
        """Calculate total scientific uncertainty."""
        return calculate_scientific_uncertainty(
            self.variance, self.sensitivity, self.sample_size, self.model_fit_error
        )


def calculate_scientific_uncertainty(
    variance: float, sensitivity_to_assumptions: float, sample_size: int, model_fit_error: float
) -> float:
    """
    Calculate scientific uncertainty.

    This is NOT rhetorical disagreement between agents.
    This is empirical uncertainty from experiments.

    Formula:
        U = (variance * sensitivity) / sqrt(n) + model_fit_error

    Args:
        variance: Statistical variance of experimental results
        sensitivity_to_assumptions: How much results change with assumptions
        sample_size: Number of experiments/observations
        model_fit_error: Residual error from model fitting

    Returns:
        Total scientific uncertainty (0 = certain, 1+ = highly uncertain)
    """
    if sample_size == 0:
        return 1.0  # Maximum uncertainty when no data

    return (variance * sensitivity_to_assumptions) / math.sqrt(sample_size) + model_fit_error


def compute_confidence_interval(
    values: List[float], confidence_level: float = 0.95
) -> Tuple[float, float]:
    """
    Compute confidence interval from experimental results.

    Args:
        values: List of experimental results
        confidence_level: Desired confidence level (default 0.95)

    Returns:
        (lower_bound, upper_bound) tuple
    """
    if not values:
        return (0.0, 1.0)

    n = len(values)
    mean = sum(values) / n

    if n == 1:
        return (mean, mean)

    # Standard deviation
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    std = math.sqrt(variance)

    # Z-score for confidence level (approximation)
    z_scores = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
    z = z_scores.get(confidence_level, 1.96)

    margin = z * std / math.sqrt(n)
    return (mean - margin, mean + margin)


def uncertainty_from_codeact_result(
    result_values: List[float],
    assumption_variations: Optional[List[float]] = None,
) -> UncertaintyComponents:
    """
    Compute uncertainty from CodeAct execution results.

    This is the primary way to compute scientific uncertainty
    from experimental evidence.

    Args:
        result_values: Results from repeated experiments
        assumption_variations: Results when assumptions are varied

    Returns:
        UncertaintyComponents with all uncertainty metrics
    """
    if not result_values:
        return UncertaintyComponents(
            variance=1.0,
            sensitivity=1.0,
            sample_size=0,
            model_fit_error=0.0,
            confidence_interval=(0.0, 1.0),
        )

    n = len(result_values)
    mean = sum(result_values) / n
    variance = sum((x - mean) ** 2 for x in result_values) / max(n - 1, 1)

    # Compute sensitivity if assumption variations provided
    sensitivity = 0.0
    if assumption_variations and len(assumption_variations) > 1:
        var_mean = sum(assumption_variations) / len(assumption_variations)
        sensitivity = abs(var_mean - mean) / max(abs(mean), 0.001)

    ci = compute_confidence_interval(result_values)

    return UncertaintyComponents(
        variance=variance,
        sensitivity=sensitivity,
        sample_size=n,
        model_fit_error=0.0,  # Set by model fitting if applicable
        confidence_interval=ci,
    )
