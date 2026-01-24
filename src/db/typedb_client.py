"""
TypeDB Connection and Schema Management

Provides connection utilities and schema loading for the SuperHyperion knowledge graph.
"""

from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from typedb.driver import TypeDB, TypeDBDriver, SessionType, TransactionType

from src.config import config


class TypeDBConnection:
    """Manages TypeDB connection and operations."""
    
    def __init__(self, address: Optional[str] = None, database: Optional[str] = None):
        self.address = address or config.typedb.address
        self.database = database or config.typedb.database
        self._driver: Optional[TypeDBDriver] = None
    
    def connect(self) -> TypeDBDriver:
        """Establish connection to TypeDB."""
        if self._driver is None:
            self._driver = TypeDB.core_driver(self.address)
        return self._driver
    
    def close(self):
        """Close the connection."""
        if self._driver:
            self._driver.close()
            self._driver = None
    
    def ensure_database(self):
        """Create database if it doesn't exist."""
        driver = self.connect()
        databases = driver.databases
        
        if not databases.contains(self.database):
            databases.create(self.database)
            print(f"Created database: {self.database}")
        else:
            print(f"Database already exists: {self.database}")
    
    def load_schema(self, schema_path: Optional[Path] = None):
        """Load TypeQL schema from file."""
        if schema_path is None:
            schema_path = Path(__file__).parent.parent / "schema" / "scientific_knowledge.tql"
        
        schema_content = schema_path.read_text()
        
        driver = self.connect()
        with driver.session(self.database, SessionType.SCHEMA) as session:
            with session.transaction(TransactionType.WRITE) as tx:
                tx.query.define(schema_content)
                tx.commit()
                print(f"Schema loaded from: {schema_path}")
    
    @contextmanager
    def session(self, session_type: SessionType = SessionType.DATA):
        """Context manager for database sessions."""
        driver = self.connect()
        session = driver.session(self.database, session_type)
        try:
            yield session
        finally:
            session.close()
    
    @contextmanager
    def transaction(self, tx_type: TransactionType = TransactionType.READ):
        """Context manager for transactions."""
        with self.session() as session:
            tx = session.transaction(tx_type)
            try:
                yield tx
                if tx_type == TransactionType.WRITE:
                    tx.commit()
            finally:
                tx.close()
    
    def query_fetch(self, query: str) -> list:
        """Execute a fetch query and return results."""
        with self.transaction(TransactionType.READ) as tx:
            result = tx.query.fetch(query)
            return list(result)
    
    def query_insert(self, query: str):
        """Execute an insert query."""
        with self.transaction(TransactionType.WRITE) as tx:
            tx.query.insert(query)
    
    def query_delete(self, query: str):
        """Execute a delete query."""
        with self.transaction(TransactionType.WRITE) as tx:
            tx.query.delete(query)


# Global connection instance
typedb = TypeDBConnection()


def init_database():
    """Initialize database with schema."""
    typedb.ensure_database()
    typedb.load_schema()
    print("SuperHyperion database initialized!")


if __name__ == "__main__":
    init_database()
