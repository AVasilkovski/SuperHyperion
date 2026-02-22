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
            # Simple check to see if we can list databases
            d.databases.all()
            return True
    except Exception:
        return False


def exec_write(tx, q: str) -> None:
    qs = q.strip()
    if not qs:
        raise ValueError("empty query")
    
    q_lower = qs.lower()
    # Anton V requirement: prevent accidental reads in write helper
    if q_lower.startswith("match") and not any(k in q_lower for k in ["insert", "update", "delete"]):
        raise AssertionError(f"exec_write received a non-mutating match-only query: {qs[:50]}...")
        
    if not any(qs.startswith(k) for k in ["insert", "match", "define", "undefine"]):
        raise ValueError(f"exec_write query must start with insert, match, define, or undefine. Got: {qs[:20]}")
        
    # Correct TypeDB 3.x driver execution: query then resolve and materialize
    ans = tx.query(qs).resolve()
    if hasattr(ans, "as_concept_rows"):
        list(ans.as_concept_rows())
    elif hasattr(ans, "as_concept_documents"):
        list(ans.as_concept_documents())
    else:
        list(ans)


def exec_read_rows(tx, q: str):
    qs = q.strip()
    if not qs:
        raise ValueError("empty query")
    # Correct TypeDB 3.x driver execution: query, resolve, then materialize concept rows
    ans = tx.query(qs).resolve()
    return list(ans.as_concept_rows()) if hasattr(ans, "as_concept_rows") else list(ans)


@pytest.fixture(scope="module")
def ghost_db():
    if not is_typedb_ready():
        pytest.skip("TypeDB not reachable or not available")

    # Force isolated DB in CI if requested, or fallback to scientific_knowledge
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


def test_tenant_ownership_relation_baseline(ghost_db):
    """
    PROVES: The tenant-ownership relation exists and works at the TypeDB schema level.
    NOTE: This does NOT prove application-level isolation enforcement.
    """
    driver = ghost_db.driver
    db_name = ghost_db.database

    tenant_a = f"T-A-{uuid.uuid4().hex[:8]}"
    tenant_b = f"T-B-{uuid.uuid4().hex[:8]}"
    capsule_a = f"cap-A-{uuid.uuid4().hex[:8]}"

    # 1. Setup Data with Materialization
    setup_q = f"""
    insert 
        $tA isa tenant, has tenant-id '{tenant_a}';
        $tB isa tenant, has tenant-id '{tenant_b}';
        $cA isa run-capsule, has capsule-id '{capsule_a}', has tenant-id '{tenant_a}';
        (owner: $tA, owned: $cA) isa tenant-ownership;
    """

    with driver.transaction(db_name, TransactionType.WRITE) as tx:
        exec_write(tx, setup_q)
        tx.commit()

    # 2. Persistence check: prove existence after commit
    with driver.transaction(db_name, TransactionType.READ) as tx:
        verify_q = f"match $t isa tenant, has tenant-id '{tenant_a}';"
        ans = exec_read_rows(tx, verify_q)
        if not ans:
            raise AssertionError(f"Write swallowed after commit! Tenant {tenant_a} not found in DB '{db_name}'.")

    # 3. Join-based isolation baseline (The 'Correctness' check)
    with driver.transaction(db_name, TransactionType.READ) as tx:
        # Tenant A should see their own capsule
        q_a = f"""
        match
            $t isa tenant, has tenant-id '{tenant_a}';
            $c isa run-capsule, has capsule-id '{capsule_a}';
            (owner: $t, owned: $c) isa tenant-ownership;
        """
        ans_a = exec_read_rows(tx, q_a)
        assert len(ans_a) == 1, "Tenant A should see their own capsule via join"

        # Tenant B should NOT see Tenant A's capsule
        q_b = f"""
        match
            $t isa tenant, has tenant-id '{tenant_b}';
            $c isa run-capsule, has capsule-id '{capsule_a}';
            (owner: $t, owned: $c) isa tenant-ownership;
        """
        ans_b = exec_read_rows(tx, q_b)
        assert len(ans_b) == 0, "Tenant B MUST NOT see Tenant A's capsule via join"


def test_tenant_isolation_enforcement(ghost_db):
    """
    PROVES: The application-level read paths (typedb_reads.py) enforce tenant isolation.
    """
    from src.api.services import typedb_reads

    # Note: TypeDBConnection in the service layer will use the default database from config.
    # We must temporarily patch the config to point to our test database if it's isolated.
    original_db = config.typedb.database
    config.typedb.database = ghost_db.database
    try:
        tenant_x = f'T-X-{uuid.uuid4().hex[:8]}'
        tenant_y = f'T-Y-{uuid.uuid4().hex[:8]}'
        capsule_x = f'cap-X-{uuid.uuid4().hex[:8]}'

        import datetime
        dt_now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(timespec='seconds')
        
        # 1. Insert data directly for testing
        setup_q = f"""
        insert 
            $tX isa tenant, has tenant-id '{tenant_x}';
            $tY isa tenant, has tenant-id '{tenant_y}';
            $cX isa run-capsule, 
                has capsule-id '{capsule_x}', 
                has tenant-id '{tenant_x}',
                has session-id 'sess-X',
                has query-hash 'hash-X',
                has scope-lock-id 'sl-X',
                has intent-id 'int-X',
                has proposal-id 'prop-X',
                has created-at {dt_now};
            (owner: $tX, owned: $cX) isa tenant-ownership;
        """

        with ghost_db.driver.transaction(ghost_db.database, TransactionType.WRITE) as tx:
            exec_write(tx, setup_q)
            tx.commit()

        # 2. Test production read paths
        # Tenant X should see their capsule
        results_x, _ = typedb_reads.list_capsules_for_tenant(tenant_x)
        assert any(r["capsule_id"] == capsule_x for r in results_x), f"Tenant X should see their own capsule via service. Got: {results_x}"

        # Tenant Y should NOT see Tenant X's capsule
        results_y, _ = typedb_reads.list_capsules_for_tenant(tenant_y)
        assert not any(r["capsule_id"] == capsule_x for r in results_y), "Tenant Y MUST NOT see Tenant X's capsule via service"

        # Scoped fetch by ID
        # Tenant X fetch -> Found
        item_x = typedb_reads.fetch_capsule_by_id_scoped(tenant_x, capsule_x)
        assert item_x is not None
        assert item_x["capsule_id"] == capsule_x

        # Tenant Y fetch -> Not Found (Isolated)
        item_y = typedb_reads.fetch_capsule_by_id_scoped(tenant_y, capsule_x)
        assert item_y is None, "Tenant Y should receive None (404-equivalent) when requesting Tenant X's capsule"
    finally:
        config.typedb.database = original_db
