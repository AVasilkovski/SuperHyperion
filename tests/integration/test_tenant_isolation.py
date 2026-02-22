import os
import uuid

import pytest

from src.config import config
from src.db.typedb_client import TypeDBConnection

typedb_driver = pytest.importorskip(
    "typedb.driver", reason="TypeDB driver not available in this environment", exc_type=ImportError
)

from typedb.driver import Credentials, DriverOptions, TransactionType, TypeDB  # noqa: E402


def is_typedb_ready():
    """Helper to check TypeDB connectivity based on env vars."""
    address = config.typedb.address
    username = config.typedb.username
    password = config.typedb.password
    opts = DriverOptions(
        is_tls_enabled=config.typedb.tls_enabled,
        tls_root_ca_path=config.typedb.tls_root_ca_path,
    )
    creds = Credentials(username, password)
    try:
        with TypeDB.driver(address, creds, opts) as d:
            d.databases.all()
            return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def ghost_db():
    if not is_typedb_ready():
        pytest.skip("TypeDB not reachable or not available")

    use_isolated = os.getenv("SUPERHYPERION_TEST_ISOLATED_DB", "false").lower() == "true"
    
    if use_isolated:
        db_name = f"test_iso_{uuid.uuid4().hex[:6]}"
        db = TypeDBConnection(database=db_name)
        driver = db.connect()
        if driver.databases.contains(db_name):
            driver.databases.get(db_name).delete()
        driver.databases.create(db_name)
        
        # We must apply schema and migrations for isolated DB
        import subprocess
        subprocess.run(["python", "scripts/apply_schema.py", "--schema", "src/schema/scientific_knowledge.tql", "--database", db_name], check=True)
        subprocess.run(["python", "scripts/migrate.py", "--migrations-dir", "src/schema/migrations", "--database", db_name], check=True)
    else:
        # Default behavior: run against the already-provisioned CI DB
        db_name = os.getenv("TYPEDB_DATABASE", "scientific_knowledge")
        db = TypeDBConnection(database=db_name)
        driver = db.connect()
        if not driver.databases.contains(db_name):
            pytest.skip(f"TypeDB database '{db_name}' not found. Ensure CI workflow creates it.")
            
    yield db
    
    if use_isolated:
        driver = db.connect()
        if driver.databases.contains(db_name):
            driver.databases.get(db_name).delete()


def test_tenant_isolation_baseline(ghost_db):
    """
    Acceptance test for TRUST-1.1 Tenant Isolation Baseline.
    Asserts cross-tenant data leakage is prevented at the schema boundary.
    """
    driver = ghost_db.driver
    db_name = ghost_db.database

    tenant_a = f"T-A-{uuid.uuid4().hex[:8]}"
    tenant_b = f"T-B-{uuid.uuid4().hex[:8]}"
    capsule_a = f"cap-A-{uuid.uuid4().hex[:8]}"

    # Match-only TypeQL 3.x queries. No select/get.
    
    # 1. Setup Tenant A and their Capsule
    setup_q = f"""
    insert 
        $tA isa tenant, has tenant-id "{tenant_a}";
        $tB isa tenant, has tenant-id "{tenant_b}";
        $cA isa run-capsule, has capsule-id "{capsule_a}", has tenant-id "{tenant_a}";
        (tenant: $tA, capsule: $cA) isa tenant-owns-capsule;
    """

    with driver.transaction(db_name, TransactionType.WRITE) as tx:
        # Loudly fail on write if TypeDB rejects it
        ans = tx.query(setup_q.strip()).resolve()
        list(ans.as_concept_rows())  # Exhaust iterator
        tx.commit()

    # Regression check: does it exist in the exact DB we're testing?
    with driver.transaction(db_name, TransactionType.READ) as tx:
        q_verify = f'match $t isa tenant, has tenant-id "{tenant_a}";'
        ans_verify = list(tx.query(q_verify).resolve().as_concept_rows())
        if len(ans_verify) == 0:
            raise AssertionError(f"Write swallowed! Tenant {tenant_a} not found in DB '{db_name}'. Address: {ghost_db.address}")

    # 2. Test Fetching with Scoping Helper
    with driver.transaction(db_name, TransactionType.READ) as tx:
        # Step A1: Can we find the Tenant?
        q_t = f'match $t isa tenant, has tenant-id "{tenant_a}";'
        ans_t = list(tx.query(q_t).resolve().as_concept_rows())
        assert len(ans_t) == 1, f"Tenant {tenant_a} not found in DB"

        # Step A2: Can we find the Capsule?
        q_c = f'match $c isa run-capsule, has capsule-id "{capsule_a}";'
        ans_c = list(tx.query(q_c).resolve().as_concept_rows())
        assert len(ans_c) == 1, f"Capsule {capsule_a} not found in DB"

        # Step A3: Can we find the Relation?
        q_a = f"""
        match
            $t isa tenant, has tenant-id "{tenant_a}";
            $c isa run-capsule, has capsule-id "{capsule_a}";
            (tenant: $t, capsule: $c) isa tenant-owns-capsule;
        """
        ans_a = list(tx.query(q_a).resolve().as_concept_rows())
        assert len(ans_a) == 1, "Tenant A should see their own capsule via relation"

        # Query B: Tenant B requests Tenant A's capsule -> Should Fail (Return empty)
        q_b = f"""
        match
            $t isa tenant, has tenant-id "{tenant_b}";
            $c isa run-capsule, has capsule-id "{capsule_a}";
            (tenant: $t, capsule: $c) isa tenant-owns-capsule;
        """
        ans_b = list(tx.query(q_b).resolve().as_concept_rows())
        assert len(ans_b) == 0, "Tenant B MUST NOT see Tenant A's capsule (isolation leak)"
