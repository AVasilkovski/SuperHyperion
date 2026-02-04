#!/usr/bin/env python3
"""
Golden Path Audit Replay Script

Runs a claim through the full SuperHyperion pipeline and prints
a complete audit trail. This serves as both a demo and a regression oracle.

Usage:
    python scripts/audit_replay.py --claim "Aspirin reduces inflammation"
    python scripts/audit_replay.py --mock  # Uses mock data for CI
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from src.utils.logging_setup import setup_logging

# Configure logging
if __name__ == "__main__":
    setup_logging()

logger = logging.getLogger(__name__)


def print_section(title: str, content: Any = None):
    """Print a formatted section header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    if content:
        if isinstance(content, dict):
            print(json.dumps(content, indent=2, default=str))
        elif isinstance(content, list):
            for i, item in enumerate(content):
                print(f"  [{i+1}] {item}")
        else:
            print(f"  {content}")


async def run_mock_pipeline() -> Dict[str, Any]:
    """
    Run a mock pipeline for CI testing.
    Returns a complete audit trail without requiring real LLM/TypeDB.
    """
    session_id = f"sess-mock-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    claim_id = "claim-mock-001"
    
    return {
        "session": {
            "session_id": session_id,
            "started_at": datetime.now().isoformat(),
            "mode": "mock",
        },
        "claims": [
            {
                "claim_id": claim_id,
                "content": "Aspirin reduces inflammation by inhibiting COX enzymes",
                "subject": "Aspirin",
                "relation": "reduces",
                "object": "inflammation",
            }
        ],
        "speculative_context": {
            claim_id: {
                "alternatives": [
                    {
                        "hypothesis": "COX-1 inhibition is primary mechanism",
                        "mechanism": "COX-1 enzyme blockade",
                        "testable_prediction": "COX-1 knockout mice show no anti-inflammatory effect",
                    },
                    {
                        "hypothesis": "COX-2 inhibition is primary mechanism",
                        "mechanism": "COX-2 enzyme blockade",
                        "testable_prediction": "COX-2 selective inhibitors match aspirin efficacy",
                    },
                ],
                "edge_cases": ["low dose", "high dose", "chronic use"],
                "analogies": [
                    {"domain": "pharmacology", "parallel": "ibuprofen mechanism"}
                ],
                "epistemic_status": "speculative",
            }
        },
        "experiment_hints": {
            claim_id: {
                "claim_id": claim_id,
                "candidate_mechanisms": ["COX-1 enzyme blockade", "COX-2 enzyme blockade"],
                "sensitivity_axes": ["low dose", "high dose", "chronic use"],
                "prior_suggestions": [{"domain": "pharmacology", "parallel": "ibuprofen mechanism"}],
                "digest": "a1b2c3d4e5f67890",
                "epistemic_status": "speculative",
            }
        },
        "experiment_spec": {
            "claim_id": claim_id,
            "hypothesis": "Verify that Aspirin reduces inflammation by inhibiting COX enzymes",
            "template_id": "sensitivity_suite",
            "params": {
                "base_value": 0.75,
                "sensitivity_axes": ["low dose", "high dose", "chronic use"],
                "variation_range": 0.2,
            },
        },
        "execution": {
            "execution_id": f"exec-{claim_id}-001",
            "template_id": "sensitivity_suite",
            "success": True,
            "result": {
                "estimate": 0.82,
                "ci_95": [0.75, 0.89],
                "variance": 0.004,
                "supports_claim": True,
                "is_fragile": False,
            },
            "diagnostics": {
                "ess": 4200,
                "rhat": 1.001,
                "divergences": 0,
            },
        },
        "evidence": {
            "claim_id": claim_id,
            "execution_id": f"exec-{claim_id}-001",
            "success": True,
            "confidence_score": 0.82,
            "fragility": False,
        },
        "proposal": {
            "claim_id": claim_id,
            "current_status": "unresolved",
            "proposed_status": "supported",
            "confidence": 0.82,
            "cap_reasons": [],
        },
        "write_intent": {
            "intent_id": f"intent-{claim_id}-001",
            "action": "update_epistemic_status",
            "payload": {
                "claim_id": claim_id,
                "new_status": "supported",
            },
            "status": "pending_approval",
        },
    }


async def run_real_pipeline(claim: str) -> Dict[str, Any]:
    """
    Run the actual pipeline. Requires LLM and TypeDB.
    """
    # Import agents
    from src.agents.base_agent import AgentContext
    from src.agents.decomposer_agent import decomposer_agent
    from src.agents.speculative_agent import speculative_agent
    from src.agents.verify_agent import VerifyAgent
    
    session_id = f"sess-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    # Initialize context
    context = AgentContext(
        graph_context={
            "session_id": session_id,
            "raw_input": claim,
        }
    )
    
    # Phase 2: Decompose
    logger.info("Phase 2: Decomposing claim...")
    context = await decomposer_agent.run(context)
    claims = context.graph_context.get("atomic_claims", [])
    
    # Phase 5: Speculate
    logger.info("Phase 5: Generating speculative hypotheses...")
    context = await speculative_agent.run(context)
    
    # Phase 6-9: Verify
    logger.info("Phases 6-9: Running verification pipeline...")
    verify_agent = VerifyAgent()
    context = await verify_agent.run_mc_pipeline(context)
    
    return {
        "session": {"session_id": session_id},
        "claims": claims,
        "speculative_context": context.graph_context.get("speculative_context", {}),
        "experiment_hints": context.graph_context.get("experiment_hints", {}),
        "mc_results": context.graph_context.get("mc_results", {}),
        "evidence": context.graph_context.get("validation_evidence", []),
        "proposals": context.graph_context.get("epistemic_proposals", []),
    }


async def main():
    parser = argparse.ArgumentParser(description="Golden Path Audit Replay")
    parser.add_argument("--claim", type=str, help="Claim to process")
    parser.add_argument("--mock", action="store_true", help="Use mock data for CI")
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("  SUPERHYPERION — GOLDEN PATH AUDIT REPLAY")
    print("="*60)
    print(f"  Started: {datetime.now().isoformat()}")
    
    if args.mock:
        logger.info("Running in MOCK mode...")
        result = await run_mock_pipeline()
    elif args.claim:
        logger.info(f"Processing claim: {args.claim}")
        result = await run_real_pipeline(args.claim)
    else:
        logger.info("No claim provided, running mock pipeline...")
        result = await run_mock_pipeline()
    
    # Print audit trail
    print_section("SESSION", result.get("session"))
    print_section("ATOMIC CLAIMS", result.get("claims"))
    print_section("SPECULATIVE CONTEXT (Speculative Lane)", result.get("speculative_context"))
    print_section("EXPERIMENT HINTS (Bridge -> digest only)", {
        k: {"claim_id": v.get("claim_id"), "digest": v.get("digest"), "sensitivity_axes": v.get("sensitivity_axes")}
        for k, v in result.get("experiment_hints", {}).items()
    })
    print_section("EXPERIMENT SPEC", result.get("experiment_spec"))
    print_section("EXECUTION RESULT", result.get("execution"))
    print_section("VALIDATION EVIDENCE", result.get("evidence"))
    print_section("EPISTEMIC PROPOSAL", result.get("proposal"))
    print_section("WRITE INTENT", result.get("write_intent"))
    
    print("\n" + "="*60)
    print("  AUDIT REPLAY COMPLETE")
    print("="*60)
    print(f"  Finished: {datetime.now().isoformat()}")
    print(f"  Exit: SUCCESS")
    print()


if __name__ == "__main__":
    asyncio.run(main())
