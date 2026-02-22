import os
import uuid
import sys
from unittest.mock import MagicMock

# Ensure we can import src
sys.path.insert(0, os.path.abspath(os.curdir))

from src.db.typedb_client import TypeDBConnection
from src.schema.scientific_knowledge import CANONICAL_SCHEMA
from typedb.driver import TransactionType

def debug_isolation():
    db_name = f"debug_iso_{uuid.uuid4().hex[:8]}"
    print(f"--- Debugging Isolation in DB: {db_name} ---")
    
    db = TypeDBConnection(database=db_name)
    if not db.connect():
        print("FAIL: Could not connect to TypeDB")
        return

    # 1. Setup Schema
    print("Step 1: Loading Schema...")
    with db.transaction(TransactionType.SCHEMA) as tx:
        tx.query(CANONICAL_SCHEMA).resolve()
    print("Schema Loaded.")

    tenant_a = "DEBUG-T-A"
    capsule_a = "DEBUG-CAP-A"

    # 2. Insert Data
    print(f"Step 2: Inserting Tenant {tenant_a} and Capsule {capsule_a}...")
    setup_q = f"""
    insert 
        $tA isa tenant, has tenant-id "{tenant_a}";
        $cA isa run-capsule, has capsule-id "{capsule_a}", has tenant-id "{tenant_a}";
        (tenant: $tA, capsule: $cA) isa tenant-owns-capsule;
    """
    with db.transaction(TransactionType.WRITE) as tx:
        tx.query(setup_q.strip()).resolve()
    print("Insert complete.")

    # 3. Diagnostic Queries
    with db.transaction(TransactionType.READ) as tx:
        print("\nChecking Tenant...")
        q_t = f'match $t isa tenant, has tenant-id "{tenant_a}"; select $t;'
        ans_t = list(tx.query(q_t).resolve().as_concept_rows())
        print(f"Found {len(ans_t)} tenants.")

        print("\nChecking Capsule...")
        q_c = f'match $c isa run-capsule, has capsule-id "{capsule_a}"; select $c;'
        ans_c = list(tx.query(q_c).resolve().as_concept_rows())
        print(f"Found {len(ans_c)} capsules.")

        print("\nChecking Relation...")
        q_r = f"""
        match
            $t isa tenant, has tenant-id "{tenant_a}";
            $c isa run-capsule, has capsule-id "{capsule_a}";
            (tenant: $t, capsule: $c) isa tenant-owns-capsule;
        select $t;
        """
        ans_r = list(tx.query(q_r).resolve().as_concept_rows())
        print(f"Found {len(ans_r)} full matches.")

    # Cleanup
    # db.driver.databases.get(db_name).delete()

if __name__ == "__main__":
    debug_isolation()
