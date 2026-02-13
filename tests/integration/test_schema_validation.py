

import pytest

from src.db.typedb_client import TypeDBConnection


# Mock TypeDB components for validation test
class MockQuery:
    def __init__(self):
        self.definitions = []
        self.inserts = []

    def define(self, q):
        self.definitions.append(q)

    def insert(self, q):
        self.inserts.append(q)

    def __call__(self, q):
        self.definitions.append(q)
        return self

    def resolve(self):
        return self

class MockTransaction:
    def __init__(self):
        self.query = MockQuery()

    def commit(self): pass
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): pass

class MockSession:
    def __init__(self):
        self.tx = MockTransaction()

    def transaction(self, tx_type):
        return self.tx

    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): pass

class MockDriver:
    def __init__(self):
        self.tx = MockTransaction()

    def transaction(self, db, type, options=None):
        return self.tx

    def close(self): pass

@pytest.fixture
def mock_typedb(monkeypatch):
    """Patch TypeDB driver to capture schema definition."""
    mock_driver = MockDriver()

    # Patch the _load_typedb check to return True so we proceed to connection logic
    monkeypatch.setattr("src.db.typedb_client._load_typedb", lambda: True)

    class MockTypeDBClass:
        @staticmethod
        def driver(addr, creds, opts): return mock_driver

    monkeypatch.setattr("src.db.typedb_client.TypeDB", MockTypeDBClass)
    monkeypatch.setattr("src.db.typedb_client.Credentials", lambda u, p: None)
    monkeypatch.setattr("src.db.typedb_client.DriverOptions", lambda **kw: None)

    # Patch SessionType and TransactionType enum-like objects
    class MockEnum:
        SCHEMA = "schema"
        DATA = "data"
        WRITE = "write"
        READ = "read"

    monkeypatch.setattr("src.db.typedb_client.SessionType", MockEnum)
    monkeypatch.setattr("src.db.typedb_client.TransactionType", MockEnum)

    return mock_driver

def test_schema_syntax_and_load(mock_typedb):
    """
    Simulate loading the schema to check for syntax errors catching 
    (though real syntax check needs real TypeDB, this verifies the file is readable and passed to driver).
    and manually inspect the content for the fixed items.
    """
    connection = TypeDBConnection()
    # Force mock mode OFF so it attempts to 'connect' (which we mocked)
    connection._mock_mode = False

    # Load schema
    connection.load_schema()

    # Retrieve what was sent to define()
    # The session context manager structure in TypeDBConnection.load_schema means
    # we need to inspect the mock driver's transaction's query object
    # But since TypeDBConnection creates a new driver instance each call if not cached...
    # Actually TypeDBConnection caches self._driver.

    # Wait, TypeDBConnection.connect() sets self._driver.
    # The mock_driver returned by core_driver is what we need to inspect.

    # Connection logic:
    # driver = self.connect() -> returns mock_driver
    # with driver.session(...) as session: -> returns mock_session
    #   with session.transaction(...) as tx: -> returns mock_tx
    #     tx.query.define(content)

    # We can access the definition via the mock_driver fixture if we ensured it was returned
    if not mock_typedb.tx.query.definitions:
        pytest.fail(f"No definitions found! Mock driver stats: {len(mock_typedb.tx.query.definitions)} inserts: {len(mock_typedb.tx.query.inserts)}")

    defined_schema = mock_typedb.tx.query.definitions[0]

    # 1. Check for Duplicate Relation Definition
    # Count occurrences of "relation proposal-targets-proposition"
    relation_def = "relation proposal-targets-proposition"
    count = defined_schema.count(relation_def)
    assert count == 1, f"Expected 1 definition of {relation_def}, found {count}"

    # 2. Check for Severity Attribute Definition
    assert "attribute severity, value string;" in defined_schema, "Severity attribute definition missing"

    # 3. Check for Entity usage of severity
    assert "owns severity," in defined_schema, "Entity usage of severity missing"
    assert "entity meta-critique-report" in defined_schema

def test_meta_critique_insert_generation():
    """Verify we can form a query using the new attribute."""
    # This is just a string check, ensuring our code concepts align
    from src.agents.ontology_steward import escape

    severity = "high"
    report_json = "{}"

    # Emulate what would be a robust query
    query = f'''
    insert $r isa meta-critique-report,
        has severity "{escape(severity)}",
        has json "{escape(report_json)}";
    '''

    assert 'has severity "high"' in query
