"""
SuperHyperion Engine Showcase (The "Engine Start")

This script executes a complex scientific inquiry through the full Phase 16.7 spine.
Query: "Environmental noise sustains quantum coherence in the avian compass."
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

# Override default model before any imports that load config
os.environ["OLLAMA_MODEL"] = "tinyllama"
os.environ["SUPERHYPERION_UNSAFE_BYPASS_GOVERNANCE"] = "true"
os.environ["ENVIRONMENT"] = "dev"  # Ensure bypass is allowed in local showcase

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("engine_showcase.log")
    ]
)
logger = logging.getLogger("EngineShowcase")

# Ensure project root is in path
sys.path.append(str(Path(__file__).parent.parent))

from src.graph.workflow_v21 import run_v21_query
from src.db.typedb_client import TypeDBConnection

async def main():
    logger.info("Starting SuperHyperion Engine (The 'Engine Start')...")
    
    # Check TypeDB connection
    db_conn = TypeDBConnection()
    try:
        driver = db_conn.connect()
        if driver:
            # Trivial call to ensure live connection
            dbs = [d.name for d in driver.databases.all()]
            logger.info(f"Connected to TypeDB Core. Available databases: {dbs}")
        else:
            logger.warning("Driver could not connect. Running in MOCK mode.")
    except Exception as e:
        logger.error(f"Failed to connect to TypeDB: {e}")
        logger.warning("Proceeding in MOCK mode...")
        # Note: If TypeDB is down, the workflow may degrade gracefully or fail based on node logic
    
    query = "The observed quantum coherence in the Avian Compass is sustained by environmental noise, contradicting the standard decoherence model."
    session_id = f"showcase-{uuid.uuid4().hex[:8]}"
    
    logger.info(f"Query: '{query}'")
    logger.info(f"Session ID: {session_id}")
    
    try:
        # Run the full v2.1 pipeline
        # We use a custom thread_id to keep the session isolated
        result = await run_v21_query(query, thread_id=session_id, session_id=session_id)
        
        logger.info("Workflow execution complete.")
        
        # Extract and report results
        resp = result.get("grounded_response", {})
        status = resp.get("status", "UNKNOWN")
        
        print("\n" + "="*80)
        print(f"ENGINE START RESULT: {status}")
        print("="*80)
        
        if status == "HOLD":
            print(f"HOLD CODE: {resp.get('hold_code')}")
            print(f"REASON: {resp.get('summary')}")
        else:
            print(f"SUMMARY: {resp.get('summary')}")
            
            # Show Governance Metadata
            gov = result.get("governance", {})
            print(f"\nGOVERNANCE METADATA:")
            print(f"- Intent ID:   {gov.get('intent_id')}")
            print(f"- Proposal ID: {gov.get('proposal_id')}")
            print(f"- Scope Lock:  {gov.get('scope_lock_id')}")
            print(f"- Evidence:    {gov.get('persisted_evidence_ids', [])}")
            
            # Show Run Capsule
            capsule = result.get("run_capsule", {})
            if capsule:
                print(f"\nRUN CAPSULE GENERATED:")
                print(f"- Capsule ID:   {capsule.get('capsule_id')}")
                print(f"- Capsule Hash: {capsule.get('capsule_hash')}")
                print(f"- Created At:   {capsule.get('created_at')}")
                
                # Save capsule info for reproducibility test
                with open("last_capsule.json", "w") as f:
                    json.dump(capsule, f, indent=2)
                logger.info("Saved capsule info to last_capsule.json")
            else:
                print("\nWARNING: No Run Capsule generated.")
                
        # Show Speculative Alternatives (Entropy)
        alts = result.get("speculative_alternatives", [])
        if alts:
            print(f"\nSPECULATIVE ALTERNATIVES (n={len(alts)}):")
            for i, alt in enumerate(alts[:3], 1):
                print(f"{i}. {alt.get('hypothesis')}")

        print("="*80)
        
    except Exception as e:
        logger.exception(f"Engine execution failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
