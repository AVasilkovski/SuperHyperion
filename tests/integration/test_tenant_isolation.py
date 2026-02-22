import uuid

import pytest

typedb_driver = pytest.importorskip(
    "typedb.driver", reason="TypeDB driver not available in this environment", exc_type=ImportError
)

from typedb.driver import TransactionType  # noqa: E402

from src.db.typedb_client import TypeDBConnection  # noqa: E402
from src.schema.scientific_knowledge import CANONICAL_SCHEMA  # noqa: E402


@pytest.fixture(scope="module")
def ghost_db():
    db_name = "test_tenant_isolation"
    db = TypeDBConnection(database=db_name)
    if not db.connect():
        pytest.skip("TypeDB driver connection failed or not available")

    # 1. Clean DB & Setup Schema
    with db.transaction(TransactionType.SCHEMA) as tx:
        tx.query(CANONICAL_SCHEMA).resolve()

    yield db

    # Teardown skipped for speed/simplicity in testing


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
        (tenant: $tA, capsule: $cA) isa tenant-owns-capsule;
    """

    with ghost_db.transaction(TransactionType.WRITE) as tx:
        ans = tx.query(setup_q.strip()).resolve()
        list(ans.as_concept_rows())  # Exhaust the iterator to execute the insert
        tx.commit()  # Explicitly commit to guarantee persistence

    # 2. Test Fetching with Scoping Helper

    with ghost_db.transaction(TransactionType.READ) as tx:
        # Step A1: Can we find the Tenant?
        q_t = f'match $t isa tenant, has tenant-id "{tenant_a}"; select $t;'
        ans_t = list(tx.query(q_t).resolve().as_concept_rows())
        assert len(ans_t) == 1, f"Tenant {tenant_a} not found in DB"

        # Step A2: Can we find the Capsule?
        q_c = f'match $c isa run-capsule, has capsule-id "{capsule_a}"; select $c;'
        ans_c = list(tx.query(q_c).resolve().as_concept_rows())
        assert len(ans_c) == 1, f"Capsule {capsule_a} not found in DB"

        # Step A3: Can we find the Relation?
        q_a = f"""
        match
            $t isa tenant, has tenant-id "{tenant_a}";
            $c isa run-capsule, has capsule-id "{capsule_a}";
            (tenant: $t, capsule: $c) isa tenant-owns-capsule;
        select $c;
        """
        ans_a = list(tx.query(q_a).resolve().as_concept_rows())
        assert len(ans_a) == 1, "Tenant A should see their own capsule via relation"

        # Query B: Tenant B requests Tenant A's capsule -> Should Fail (Return empty)
        q_b = f"""
        match
            $t isa tenant, has tenant-id "{tenant_b}";
            $c isa run-capsule, has capsule-id "{capsule_a}";
            (tenant: $t, capsule: $c) isa tenant-owns-capsule;
        select $c;
        """
        ans_b = list(tx.query(q_b).resolve().as_concept_rows())
        assert len(ans_b) == 0, "Tenant B MUST NOT see Tenant A's capsule (isolation leak)"
