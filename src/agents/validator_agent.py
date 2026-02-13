"""
Validator Agent

v2.1 Step 6: CodeAct-based evidence production.
This is the BELIEF GATEKEEPER - the only agent that can authorize belief updates.
"""

import logging
from typing import Any, Dict, List, Optional

from src.agents.base_agent import AgentContext, BaseAgent
from src.agents.codeact_executor import CodeActExecutor
from src.graph.state import Evidence, ScientificUncertainty

logger = logging.getLogger(__name__)


VALIDATOR_CODE_TEMPLATE = """
# Validation experiment for claim: {claim_content}
# This code produces evidence that can authorize belief updates.

import numpy as np
import statistics

# Run experiment {n} times
results = []
for i in range({n}):
    # Simulate experiment (replace with actual test)
    result = {experiment_code}
    results.append(result)

# Calculate statistics
mean = np.mean(results)
std = np.std(results)
variance = np.var(results)
ci_95 = (mean - 1.96*std/np.sqrt(len(results)), mean + 1.96*std/np.sqrt(len(results)))

print(f"Mean: {{mean:.4f}}")
print(f"Std: {{std:.4f}}")
print(f"Variance: {{variance:.4f}}")
print(f"95% CI: {{ci_95}}")
print(f"Sample size: {{len(results)}}")

# Output structured result
result = {{
    "mean": mean,
    "std": std,
    "variance": variance,
    "confidence_interval": ci_95,
    "sample_size": len(results),
    "supports_claim": mean > 0.5  # Adjust threshold as needed
}}
print(result)
"""


class ValidatorAgent(BaseAgent):
    """
    Step 6: Produces evidence via CodeAct execution.
    
    CRITICAL: This is the BELIEF GATEKEEPER.
    
    Rules:
        1. Only this agent can produce Evidence objects
        2. Only Evidence.authorizes_update() == True allows belief changes
        3. Bayesian updates must reference codeact_execution_id
        4. No belief update without executed evidence
    """

    def __init__(self):
        super().__init__(name="ValidatorAgent")
        self._executor = CodeActExecutor()
        self._execution_counter = 0

    async def run(self, context: AgentContext) -> AgentContext:
        """
        Execute validation experiments for all claims.
        """
        claims = context.graph_context.get("atomic_claims", [])

        if not claims:
            logger.warning("No claims to validate")
            return context

        # Ensure we're in grounded mode for validation
        if context.graph_context.get("epistemic_mode") != "grounded":
            context.graph_context["epistemic_mode"] = "grounded"

        evidence_list = []

        for claim in claims:
            evidence = await self._validate_claim(claim, context)
            if evidence:
                evidence_list.append(evidence)

        # Store evidence in context
        context.code_results.extend([e.__dict__ for e in evidence_list])
        context.graph_context["evidence"] = [e.__dict__ for e in evidence_list]

        logger.info(f"Produced {len(evidence_list)} pieces of evidence")

        return context

    async def _validate_claim(
        self,
        claim: Dict[str, Any],
        context: AgentContext
    ) -> Optional[Evidence]:
        """
        Execute validation experiment for a single claim.
        """
        claim_id = claim.get("claim_id", "unknown")
        claim_content = claim.get("content", "")

        # Generate experiment code
        code = self._generate_experiment_code(claim, context)

        if not code:
            logger.warning(f"Could not generate experiment for claim {claim_id}")
            return None

        # Execute via CodeAct
        self._execution_counter += 1
        execution_id = self._execution_counter

        try:
            self._executor.start()
            result = self._executor.execute(code)
            self._executor.stop()

            # Parse results and compute uncertainty
            uncertainty = self._compute_uncertainty_from_result(result)

            # Create Evidence object
            evidence = Evidence(
                hypothesis_id=claim_id,
                test_description=f"Validation experiment for: {claim_content}",
                codeact_execution_id=execution_id,
                result={"stdout": result.stdout, "success": result.success},
                uncertainty=uncertainty,
                assumptions=self._extract_assumptions(claim, context),
                success=result.success,
            )

            logger.info(
                f"Evidence produced for {claim_id}: "
                f"success={evidence.success}, "
                f"uncertainty={uncertainty.total():.3f}"
            )

            return evidence

        except Exception as e:
            logger.error(f"Validation failed for {claim_id}: {e}")
            return Evidence(
                hypothesis_id=claim_id,
                test_description=f"Failed validation for: {claim_content}",
                codeact_execution_id=execution_id,
                result={"error": str(e)},
                uncertainty=ScientificUncertainty(variance=1.0, sample_size=0),
                assumptions=[],
                success=False,
            )

    def _generate_experiment_code(
        self,
        claim: Dict[str, Any],
        context: AgentContext
    ) -> Optional[str]:
        """
        Generate Python code for the validation experiment.
        """
        claim_content = claim.get("content", "")

        # Use LLM to generate experiment code
        prompt = f"""
Generate a Python validation experiment for this scientific claim:

Claim: {claim_content}
Subject: {claim.get('subject', '')}
Relation: {claim.get('relation', '')}  
Object: {claim.get('object', '')}

The code should:
1. Run a testable experiment (simulation is OK for demo)
2. Compute mean, variance, confidence interval
3. Output structured results with 'supports_claim' boolean

Output ONLY the Python code, no explanation.
"""

        try:
            code = self.generate(prompt=prompt, temperature=0.2)
            # Basic sanitization
            if "import" in code and "print" in code:
                return code
            else:
                # Fallback to template
                return VALIDATOR_CODE_TEMPLATE.format(
                    claim_content=claim_content,
                    n=10,
                    experiment_code="np.random.random() * 2 - 1"
                )
        except Exception:
            return VALIDATOR_CODE_TEMPLATE.format(
                claim_content=claim_content,
                n=10,
                experiment_code="np.random.random()"
            )

    def _compute_uncertainty_from_result(self, result) -> ScientificUncertainty:
        """Compute scientific uncertainty from CodeAct result."""
        if not result.success:
            return ScientificUncertainty(variance=1.0, sample_size=0)

        # Try to parse structured output
        try:
            import re
            stdout = result.stdout

            variance = 0.5  # Default
            sample_size = 10

            # Extract variance if present
            var_match = re.search(r"Variance:\s*([\d.]+)", stdout)
            if var_match:
                variance = float(var_match.group(1))

            # Extract sample size if present
            n_match = re.search(r"Sample size:\s*(\d+)", stdout)
            if n_match:
                sample_size = int(n_match.group(1))

            return ScientificUncertainty(
                variance=variance,
                sensitivity=0.1,
                sample_size=sample_size,
                model_fit_error=0.05,
            )
        except Exception:
            return ScientificUncertainty(variance=0.5, sample_size=1)

    def _extract_assumptions(
        self,
        claim: Dict[str, Any],
        context: AgentContext
    ) -> List[str]:
        """Extract assumptions made in the validation."""
        return [
            "Simulated experiment (not real data)",
            f"Conditions: {claim.get('conditions', {})}",
        ]


# Global instance
validator_agent = ValidatorAgent()
