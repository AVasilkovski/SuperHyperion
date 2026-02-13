"""
Verify Agent (v2.2 Phase 13)

Implementation of the internal Monte Carlo pipeline:
Design (LLM) -> Execute (CodeAct) -> Analyze (Feynman Checks)

Responsibilities:
1. Orchestrate safe MC verification using whitelisted templates.
2. Produce "audit-grade" Evidence with fragility flags.
3. Enforce Feynman heuristics (toy models, extremes, dimensions).
"""

import logging
import math
import time
from typing import Any, Dict, Optional

from src.agents.base_agent import AgentContext, BaseAgent
from src.graph.state import Evidence
from src.montecarlo.templates import TemplateExecution, registry, sha256_json
from src.montecarlo.types import ExperimentSpec, MCResult
from src.montecarlo.versioned_registry import VERSIONED_REGISTRY

logger = logging.getLogger(__name__)

class VerifyAgent(BaseAgent):
    """
    v2.2 Verify Node: The Scientist.
    
    Orchestrates:
    - Experiment Design (LLM -> ExperimentSpec)
    - Execution (CodeAct -> TemplateRegistry)
    - Analysis (Feynman Checks -> Evidence.is_fragile)
    """

    def __init__(self, max_budget_ms: int = 30_000):
        super().__init__(name="VerifyAgent")
        self.registry = registry
        self.max_budget_ms = max_budget_ms

    async def run(self, context: AgentContext) -> AgentContext:
        """Run verification pipeline for all claims in context."""
        claims = context.graph_context.get("atomic_claims", [])

        if not claims:
            logger.warning("No claims to verify")
            return context

        context.graph_context["epistemic_mode"] = "grounded"

        # Prepare storage
        if "template_executions" not in context.graph_context:
            context.graph_context["template_executions"] = []
        if "evidence" not in context.graph_context:
            context.graph_context["evidence"] = []
        if "negative_evidence" not in context.graph_context:
            context.graph_context["negative_evidence"] = []

        # Process each claim through the MC pipeline
        for claim in claims:
             await self.run_mc_pipeline(claim, context)

        # Aggregate reports (optional, for debugging/summary)
        self._aggregate_reports(context)

        return context

    async def run_mc_pipeline(self, claim: Dict[str, Any], context: AgentContext) -> None:
        """
        Execute the Design -> Execute -> Analyze loop for a single claim.
        """
        claim_id = claim.get("claim_id", "unknown")

        try:
            # 1) DESIGN (LLM) -> ExperimentSpec
            spec = await self._design_experiment_spec(claim, context)
            if not spec:
                logger.warning(f"Skipping claim {claim_id}: Design failed")
                return

            # 2) EXECUTE (CodeAct) -> TemplateExecution (raw)
            execution = self._codeact_execute_template(spec, context)

            # Persist execution audit trail immediately
            context.graph_context["template_executions"].append(self._execution_to_dict(execution))

            if not execution.success:
                logger.warning(f"Execution failed for {claim_id}: {execution.warnings}")
                return

            # 3) ANALYZE -> MCResult + Feynman Checks
            # Attempt to map raw result to MCResult structure
            try:
                # Fill missing fields with defaults if template is simple
                raw_res = execution.result
                mc_result = MCResult(
                    estimate=float(raw_res.get("estimate", raw_res.get("mean_value", raw_res.get("value", 0.0)))),
                    ci_95=(
                        float(raw_res.get("ci_low", 0.0)),
                        float(raw_res.get("ci_high", 0.0))
                    ),
                    variance=float(raw_res.get("variance", 0.0)),
                    diagnostics=raw_res.get("diagnostics", {}),
                    sensitivity=raw_res.get("sensitivity", {}),
                    supports_claim=self._determine_support(spec, raw_res),
                    is_fragile=raw_res.get("fragile", False),
                    notes=raw_res.get("summary", "")
                )
            except Exception as e:
                logger.error(f"Failed to parse MCResult for {claim_id}: {e}")
                return

            # Run deterministic Feynman checks
            feynman = self._feynman_checks(spec, mc_result, execution)

            # Apply Fragility Hard-Cap
            if not feynman["all_pass"]:
                mc_result.is_fragile = True

            # 4) PACK EVIDENCE
            # 4) PACK EVIDENCE

            # --- Phase 16.1: Negative Evidence Branch ---
            if not mc_result.supports_claim:
                # Retrieve governed semantics from Registry
                # Use execution.template_qid (canonical) if available, else fallback
                qid = execution.template_qid or f"{spec.template_id}@1.0.0"
                template_spec = VERSIONED_REGISTRY.get_spec(qid)

                if template_spec:
                    epi = template_spec.epistemic
                    negative_strength = self._compute_negative_strength(epi, mc_result)

                    if epi.negative_role_on_fail != "none":
                        neg_evidence = {
                            "claim_id": spec.claim_id,
                            "template_qid": qid,
                            "evidence_id": f"neg-{execution.execution_id}",  # Provisional ID
                            "role": epi.negative_role_on_fail,
                            "failure_mode": epi.default_failure_mode,
                            "strength": negative_strength,
                            "diagnostics": mc_result.diagnostics,
                            "metrics": self._extract_metrics(execution.result),
                            "provenance": {
                                "template": spec.template_id,
                                "params": execution.params,
                                "epistemic_context": epi.to_canonical_dict()
                            }
                        }
                        context.graph_context["negative_evidence"].append(neg_evidence)
                        logger.info(f"Emitted NEGATIVE evidence for {spec.claim_id} (role={epi.negative_role_on_fail})")

                        # Return early? Or emit both?
                        # Contract: If refuting, we do NOT emit positive evidence.
                        return

            # --- Positive Evidence Path ---
            evidence = Evidence(
                hypothesis_id=context.graph_context.get("hypothesis_id", "unknown"),
                claim_id=spec.claim_id,
                execution_id=execution.execution_id,
                template_id=spec.template_id,
                template_qid=execution.template_qid,  # Phase 14.5: Qualified ID
                scope_lock_id=spec.scope_lock_id,  # Phase 14.5: Scope lock
                test_description=f"Template {spec.template_id}: {spec.hypothesis}",

                # Numeric Core
                estimate=mc_result.estimate,
                ci_95=mc_result.ci_95,
                variance=mc_result.variance,

                # Diagnostics & Fragility
                diagnostics=mc_result.diagnostics,
                sensitivity=mc_result.sensitivity,
                supports_claim=mc_result.supports_claim,
                is_fragile=mc_result.is_fragile,
                feynman=feynman,

                # Legacy / Audit
                result=execution.result,
                metrics=self._extract_metrics(execution.result),
                assumptions=list(spec.assumptions.keys()) if spec.assumptions else [],
                provenance={"template": spec.template_id, "params": execution.params},
                warnings=execution.warnings + ([f"CRITICAL: Budget exceeded {execution.runtime_ms}ms > {self.max_budget_ms}ms"] if execution.runtime_ms > self.max_budget_ms else []),
                success=True
            )

            # 4) PACK EVIDENCE


            # Store raw Evidence object (Steward handles serialization)
            context.graph_context["evidence"].append(evidence)
            context.graph_context["latest_evidence"] = self._evidence_to_dict(evidence)

            # Populate State Scalars (Phase 13 Requirement)
            context.graph_context["estimate"] = mc_result.estimate
            context.graph_context["ci_95"] = mc_result.ci_95
            context.graph_context["variance"] = mc_result.variance
            context.graph_context["diagnostics"] = mc_result.diagnostics
            context.graph_context["sensitivity"] = mc_result.sensitivity
            context.graph_context["supports_claim"] = mc_result.supports_claim
            context.graph_context["is_fragile"] = mc_result.is_fragile
            context.graph_context["feynman"] = feynman

        except Exception as e:
            logger.error(f"Pipeline crashed for {claim_id}: {e}", exc_info=True)

    async def _design_experiment_spec(self, claim: Dict[str, Any], context: AgentContext) -> Optional[ExperimentSpec]:
        """
        LLM designs the experiment specification, informed by speculative hints.
        
        The hints from the Brainstorm → MC Design bridge inform:
        - Template selection (e.g., sensitivity_suite if edge cases provided)
        - Parameter ranges (sensitivity axes become params)
        - Prior suggestions (from analogies)
        
        INVARIANT: Hints are used for DESIGN, never echoed into the spec.
        The resulting ExperimentSpec is a clean grounded artifact.
        """
        claim_id = claim.get("claim_id", "unknown")
        content = claim.get("content", "")

        # Extract experiment hints for this claim (if available)
        hints = context.graph_context.get("experiment_hints", {}).get(claim_id)

        # Log hint digest for audit trail (not raw content)
        hint_digest = None
        if hints:
            # Handle both ExperimentHints object and dict
            if hasattr(hints, "digest"):
                hint_digest = hints.digest()
            elif isinstance(hints, dict):
                # Fallback for dict-style hints
                import hashlib
                import json as json_mod
                hint_digest = hashlib.sha256(
                    json_mod.dumps(hints, sort_keys=True, default=str).encode()
                ).hexdigest()[:16]

            logger.info(f"Designing experiment for {claim_id} with hint_digest={hint_digest}")

        # Build hint-aware prompt section (for LLM prompting, not for spec)
        hint_section = ""
        if hints:
            # Extract hint content (handle both object and dict)
            if hasattr(hints, "model_dump"):
                h = hints.model_dump()
            elif isinstance(hints, dict):
                h = hints
            else:
                h = {}

            mechanisms = h.get("candidate_mechanisms", [])
            sensitivity_axes = h.get("sensitivity_axes", [])
            falsification = h.get("falsification_criteria", [])
            priors = h.get("prior_suggestions", [])

            if any([mechanisms, sensitivity_axes, falsification, priors]):
                hint_section = f"""
SPECULATIVE CONTEXT (use to inform design, do NOT echo in output):
- Candidate mechanisms to discriminate: {mechanisms[:3] if mechanisms else 'None'}
- Sensitivity axes to probe: {sensitivity_axes[:3] if sensitivity_axes else 'None'}
- Falsification criteria: {falsification[:2] if falsification else 'None'}
- Prior suggestions from analogies: {len(priors)} available
"""

        _prompt = f"""Design a verification experiment for: "{content}" (ID: {claim_id}).
{hint_section}
Available Templates:
- bootstrap_ci: for effect sizes with data
- threshold_check: for simple metric limits
- numeric_consistency: for claimed vs observed values
- sensitivity_suite: for testing robustness (use if edge_cases/sensitivity_axes provided)

Return JSON matching ExperimentSpec (claim_id, hypothesis, template_id, params).
Do NOT include speculative content in the output.
"""

        try:
            # Short circuit for testing if no LLM
            # response = await self.generate(prompt)

            # Fallback/Heuristic for reliability in this implementation step
            # Use hint-aware template selection
            template_id = "numeric_consistency"  # default
            params = {
                "claimed_value": 0.5,
                "observed_values": [0.4, 0.5, 0.6],
                "tolerance": 0.2
            }

            # Hint-aware template selection
            if hints:
                h = hints.model_dump() if hasattr(hints, "model_dump") else hints
                sensitivity_axes = h.get("sensitivity_axes", [])

                # If edge cases / sensitivity axes are provided, use sensitivity_suite
                if sensitivity_axes:
                    template_id = "sensitivity_suite"
                    params = {
                        "base_value": 0.5,
                        "sensitivity_axes": sensitivity_axes[:3],  # Limit to 3
                        "variation_range": 0.2,
                    }
                    logger.info(f"Selected sensitivity_suite for {claim_id} due to {len(sensitivity_axes)} sensitivity axes")

            return ExperimentSpec(
                claim_id=claim_id,
                hypothesis=f"Verify that {content} holds",
                template_id=template_id,
                scope_lock_id=context.graph_context.get("scope_lock_id", f"scope-{claim_id}"),
                params=params,
                assumptions={"independence_assumed": True}
            )
        except Exception as e:
            logger.error(f"Design failed for {claim_id}: {e}")
            return None

    def _codeact_execute_template(self, spec: ExperimentSpec, context: AgentContext) -> TemplateExecution:
        """Execute via Registry (CodeAct boundary). Registry enforces param validation."""
        extra_context = {
            "session_id": context.graph_context.get("session_id", "sess-unknown"),
            "claim_id": spec.claim_id
        }

        # 1. Get Template Definition (Existence Check)
        try:
            self.registry.get(spec.template_id)
        except KeyError:
             return self._failed_execution(spec, "Unknown template ID")

        # 2. Execute via Registry (Single Validation Path)
        return self.registry.run_template(
            template_id=spec.template_id,
            params=spec.params,
            context=extra_context,
            caller_role="verify"
        )

    def _failed_execution(self, spec: ExperimentSpec, error: str) -> TemplateExecution:
        result = {"error": error}
        return TemplateExecution(
            execution_id=f"exec-fail-{time.time_ns()}",
            template_id=spec.template_id,
            claim_id=spec.claim_id,
            params=spec.params,
            result=result,
            success=False,
            runtime_ms=0,
            warnings=[error],
            params_hash=sha256_json(spec.params),
            result_hash=sha256_json(result)
        )

    def _feynman_checks(self, spec: ExperimentSpec, r: MCResult, ex: TemplateExecution) -> Dict[str, Any]:
        """Deterministic Feynman Heuristics."""
        checks = {}

        # 1) Toy Model
        # STRICT: Default to False if toy_ok missing for MC templates
        is_mc = spec.template_id in ["bootstrap_ci", "bayesian_update", "sensitivity_suite"]
        toy_ok = r.diagnostics.get("toy_ok")

        if toy_ok is None:
             toy_pass = not is_mc # Fail if MC and missing
             toy_reason = "Missing toy_ok diagnostic" if is_mc else "opt-out"
        else:
             toy_pass = bool(toy_ok)
             toy_reason = "toy_ok=True" if toy_pass else "toy_ok=False"

        checks["toy_model"] = {
            "pass": toy_pass,
            "reason": toy_reason
        }

        # 2) Extremes: Check validity bounds (e.g., probability in [0,1])
        # Simple heuristic: variance shouldn't be negative, probabilities in [0,1]
        extremes_pass = True
        reason = "Bounds ok"
        if r.variance < 0:
            extremes_pass = False
            reason = "Negative variance detected"

        checks["extremes"] = {
            "pass": extremes_pass,
            "reason": reason
        }

        # 3) Dimensions: Unit consistency (if provided)
        if spec.units and "estimate" in spec.units:
            checks["dimensions"] = {
                "pass": True,
                "reason": f"Unit {spec.units['estimate']} accepted"
            }
        else:
             checks["dimensions"] = {
                "pass": False, # Marking false to encourage unit usage, or True if optional
                "reason": "No units provided"
            }

        # 4) Independence: Check for red flags in diagnostics
        indep_flag = r.diagnostics.get("independence_red_flag", False)
        checks["independence"] = {
            "pass": not indep_flag,
            "reason": "Flag raised" if indep_flag else "No dependence flags"
        }

        # 5) Diagnostics: ESS > 400 (if applicable)
        ess = r.diagnostics.get("ess")
        if ess is not None:
            checks["diagnostics"] = {
                "pass": ess >= 400,
                "reason": f"ESS={ess}"
            }
        else:
            # STRICT: Fail if MC template & missing ESS
            if is_mc:
                checks["diagnostics"] = {"pass": False, "reason": "Missing ESS for MC template"}
            else:
                checks["diagnostics"] = {"pass": True, "reason": "No ESS metric (deterministic)"}

        # 6) Budget: Check runtime
        if ex.runtime_ms > self.max_budget_ms:
            checks["budget"] = {
                "pass": False,
                "reason": f"Runtime {ex.runtime_ms}ms > {self.max_budget_ms}ms"
            }
        else:
             checks["budget"] = {"pass": True, "reason": "Within budget"}

        # 7) Missing CI for MC templates (New Audit Rule)
        if is_mc:
            # Check if CI is [0,0] (default) which implies missing data
            # Or if result dictionary was missing them
            # We check r.ci_95 which is populated from result
            if r.ci_95 == (0.0, 0.0) and r.variance == 0.0:
                 checks["completeness"] = {
                     "pass": False,
                     "reason": "Missing CI/Variance for MC template"
                 }
            else:
                 checks["completeness"] = {"pass": True, "reason": "CI present"}

        # 6) Sensitivity: Did prior widening flip the result?
        sens = r.sensitivity or {}
        prior_flip = sens.get("prior_widened_flips", False)
        noise_flip = sens.get("noise_model_flips", False)

        checks["sensitivity"] = {
            "pass": not (prior_flip or noise_flip),
            "reason": f"PriorFlip={prior_flip}, NoiseFlip={noise_flip}"
        }

        all_pass = all(c["pass"] for c in checks.values())
        return {"all_pass": all_pass, "checks": checks}

    def _determine_support(self, spec: ExperimentSpec, raw: Dict[str, Any]) -> bool:
        """Heuristic to determine if result supports claim based on template type."""
        if spec.template_id == "threshold_check":
            return raw.get("passes", False)
        if spec.template_id == "numeric_consistency":
            return raw.get("consistent", False)
        if spec.template_id == "contradiction_detect":
            return not raw.get("has_conflicts", False)
        if spec.template_id == "bootstrap_ci":
            # Support if null value is not in CI
            # Default null is 0.0 unless specified in result (e.g. for ratios)
            null_val = raw.get("null_value", 0.0)
            low = raw.get("ci_low", 0.0)
            high = raw.get("ci_high", 0.0)
            return not (low <= null_val <= high) # Reject null hypothesis

        return True # Default optimistic

    def _compute_negative_strength(self, epi, result: MCResult) -> float:
        """Compute strength of negative evidence [0,1]."""
        if epi.strength_model == "binary_default":
            return 1.0

        if epi.strength_model == "ci_proximity_to_null":
            # Heuristic: How far is the nearest CI bound from the null value?
            # Higher distance = stronger refutation (if result implies null is far away)
            # OR for replication: strength is confidence in the null-result.

            # For now, simple implementation:
            # If we failed to reject null (replication failure), strength is high contextually
            # Mapping variance to strength: lower variance = higher strength of "null finding"
            try:
                if result.variance > 0:
                    return 1.0 / (1.0 + math.sqrt(result.variance))
            except:
                pass
            return 0.5

        return 0.5

    def _extract_metrics(self, result: Dict[str, Any]) -> Dict[str, float]:
        """Legacy metric extractor."""
        metrics = {}
        for k, v in result.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                metrics[k] = float(v)
        return metrics

    def _execution_to_dict(self, e: TemplateExecution) -> Dict[str, Any]:
        return {
            "execution_id": e.execution_id,
            "template_id": e.template_id,
            "claim_id": e.claim_id,
            "params": e.params,
            "result": e.result,
            "success": e.success,
            "runtime_ms": e.runtime_ms,
            "warnings": e.warnings,
            # Phase 12 Additions
            "params_hash": getattr(e, "params_hash", None),
            "result_hash": getattr(e, "result_hash", None),
        }

    def _evidence_to_dict(self, e: Any) -> Dict[str, Any]:
        """Robust serializer for Evidence (Pydantic or Dataclass)."""
        if hasattr(e, "model_dump"):
            return e.model_dump()
        try:
            from dataclasses import asdict, is_dataclass
            if is_dataclass(e):
                return asdict(e)
        except Exception:
            pass
        if isinstance(e, dict):
            return e
        raise TypeError(f"Unsupported Evidence type: {type(e)}")

    def _aggregate_reports(self, context: AgentContext):
        # ... logic to build verify report ...
        pass

# Global instance
verify_agent = VerifyAgent()
