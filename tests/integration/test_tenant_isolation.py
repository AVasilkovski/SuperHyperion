import os
import uuid

import pytest

typedb_driver = pytest.importorskip(
    "typedb.driver", 
    reason="TypeDB driver not available in this environment", 
    exc_type=ImportError
)

from typedb.driver import TransactionType  # noqa: E402

from src.db.typedb_client import TypeDBConnection  # noqa: E402
from src.schema.scientific_knowledge import CANONICAL_SCHEMA  # noqa: E402


@pytest.fixture(scope="module")
def ghost_db():
    os.environ["TYPEDB_DATABASE"] = "test_tenant_isolation"
    db = TypeDBConnection()
    if not db.connect():
        pytest.skip("TypeDB driver connection failed or not available")
        
    # 1. Clean DB & Setup Schema
    with db.transaction(TransactionType.SCHEMA) as tx:
        tx.query(CANONICAL_SCHEMA).resolve()
            
    yield db
    
    # Teardown skipped for speed/simplicity in testing; usually DB is dropped
    os.environ.pop("TYPEDB_DATABASE", None)

def test_tenant_isolation_baseline(ghost_db):
    """
    Acceptance test for TRUST-1.1 Tenant Isolation Baseline.
    Asserts cross-tenant data leakage is prevented at the schema boundary.
    """
    
    tenant_a = f"T-A-{uuid.uuid4().hex[:8]}"
    tenant_b = f"T-B-{uuid.uuid4().hex[:8]}"
    capsule_a = f"cap-A-{uuid.uuid4().hex[:8]}"
    
    # 1. Setup Tenant A and their Capsule
    setup_q = f"""
    insert 
        $tA isa tenant, has tenant-id "{tenant_a}";
        $tB isa tenant, has tenant-id "{tenant_b}";
        $cA isa run-capsule, has capsule-id "{capsule_a}", has tenant-id "{tenant_a}";
        (owner: $tA, owned: $cA) isa tenant-ownership;
    """
    
    with ghost_db.transaction(TransactionType.WRITE) as tx:
        tx.query(setup_q.strip()).resolve()

    # 2. Test Fetching with Scoping Helper
    from src.trust.tenant_scope import scope_prefix
    
    with ghost_db.transaction(TransactionType.READ) as tx:
        # Query A: Tenant A requests their own capsule -> Should Succeed
        scope_a = scope_prefix(tenant_a, target_var="c").strip()
        q_a = f"match $c isa run-capsule, has capsule-id \"{capsule_a}\", {scope_a.replace('$c ', '')}; select $c;"
        ans_a = list(tx.query(q_a).resolve())
        assert len(ans_a) == 1, "Tenant A should see their own capsule"
        
        # Query B: Tenant B requests Tenant A's capsule -> Should Fail (Return empty)
        scope_b = scope_prefix(tenant_b, target_var="c").strip()
        q_b = f"match $c isa run-capsule, has capsule-id \"{capsule_a}\", {scope_b.replace('$c ', '')}; select $c;"
        ans_b = list(tx.query(q_b).resolve())
        assert len(ans_b) == 0, "Tenant B MUST NOT see Tenant A's capsule (isolation leak)"
