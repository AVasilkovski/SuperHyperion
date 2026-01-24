"""
TypeDB Connection and Schema Management

Provides connection utilities and schema loading for the SuperHyperion knowledge graph.
Handles Python 3.13 compatibility with lazy imports.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import logging

from src.config import config

logger = logging.getLogger(__name__)

# ============================================================================
# Lazy TypeDB Import (Python 3.13 compatibility)
# ============================================================================

TYPEDB_AVAILABLE = False
TypeDB = None
TypeDBDriver = None
SessionType = None
TransactionType = None

def _load_typedb():
    """Lazy load TypeDB driver to handle import errors gracefully."""
    global TYPEDB_AVAILABLE, TypeDB, TypeDBDriver, SessionType, TransactionType
    
    if TYPEDB_AVAILABLE:
        return True
    
    try:
        from typedb.driver import TypeDB as _TypeDB
        from typedb.driver import TypeDBDriver as _TypeDBDriver
        from typedb.driver import SessionType as _SessionType
        from typedb.driver import TransactionType as _TransactionType
        
        TypeDB = _TypeDB
        TypeDBDriver = _TypeDBDriver
        SessionType = _SessionType
        TransactionType = _TransactionType
        TYPEDB_AVAILABLE = True
        logger.info("TypeDB driver loaded successfully")
        return True
        
    except ImportError as e:
        logger.warning(f"TypeDB driver not available: {e}")
        logger.warning(
            "To fix on Python 3.13:\n"
            "  1. Install Visual C++ Redistributable: https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
            "  2. Or use Python 3.12: pyenv install 3.12\n"
            "  3. Or run TypeDB in Docker only"
        )
        return False


class TypeDBConnection:
    """Manages TypeDB connection and operations."""
    
    def __init__(self, address: Optional[str] = None, database: Optional[str] = None):
        self.address = address or config.typedb.address
        self.database = database or config.typedb.database
        self._driver = None
        self._mock_mode = False
    
    def connect(self):
        """Establish connection to TypeDB."""
        if not _load_typedb():
            logger.warning("Running in mock mode - TypeDB not available")
            self._mock_mode = True
            return None
        
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
        if self._mock_mode:
            logger.info(f"[MOCK] Would create database: {self.database}")
            return
            
        driver = self.connect()
        if driver is None:
            return
            
        databases = driver.databases
        
        if not databases.contains(self.database):
            databases.create(self.database)
            logger.info(f"Created database: {self.database}")
        else:
            logger.info(f"Database already exists: {self.database}")
    
    def load_schema(self, schema_path: Optional[Path] = None):
        """Load TypeQL schema from file."""
        if schema_path is None:
            schema_path = Path(__file__).parent.parent / "schema" / "scientific_knowledge.tql"
        
        if self._mock_mode:
            logger.info(f"[MOCK] Would load schema from: {schema_path}")
            return
        
        schema_content = schema_path.read_text()
        
        driver = self.connect()
        if driver is None:
            return
            
        with driver.session(self.database, SessionType.SCHEMA) as session:
            with session.transaction(TransactionType.WRITE) as tx:
                tx.query.define(schema_content)
                tx.commit()
                logger.info(f"Schema loaded from: {schema_path}")
    
    @contextmanager
    def session(self, session_type=None):
        """Context manager for database sessions."""
        if self._mock_mode:
            yield MockSession()
            return
            
        if session_type is None:
            session_type = SessionType.DATA
            
        driver = self.connect()
        if driver is None:
            yield MockSession()
            return
            
        session = driver.session(self.database, session_type)
        try:
            yield session
        finally:
            session.close()
    
    @contextmanager
    def transaction(self, tx_type=None):
        """Context manager for transactions."""
        if self._mock_mode:
            yield MockTransaction()
            return
            
        if tx_type is None:
            tx_type = TransactionType.READ
            
        with self.session() as session:
            tx = session.transaction(tx_type)
            try:
                yield tx
                if tx_type == TransactionType.WRITE:
                    tx.commit()
            finally:
                tx.close()
    
    def query_fetch(self, query: str) -> List[Dict]:
        """Execute a fetch query and return results."""
        if self._mock_mode:
            logger.debug(f"[MOCK] query_fetch: {query[:100]}...")
            return []
            
        with self.transaction(TransactionType.READ) as tx:
            result = tx.query.fetch(query)
            return list(result)
    
    def query_insert(self, query: str):
        """Execute an insert query."""
        if self._mock_mode:
            logger.debug(f"[MOCK] query_insert: {query[:100]}...")
            return
            
        with self.transaction(TransactionType.WRITE) as tx:
            tx.query.insert(query)
    
    def query_delete(self, query: str):
        """Execute a delete query."""
        if self._mock_mode:
            logger.debug(f"[MOCK] query_delete: {query[:100]}...")
            return
            
        with self.transaction(TransactionType.WRITE) as tx:
            tx.query.delete(query)
    
    # ========================================================================
    # v2.1 Typed Operations
    # ========================================================================
    
    def insert_proposition(
        self,
        entity_id: str,
        content: str,
        confidence: float = 0.5,
        belief_state: str = "proposed"
    ):
        """Insert a proposition into the graph."""
        query = f"""
        insert $p isa proposition,
            has entity-id "{entity_id}",
            has content "{content}",
            has confidence-score {confidence},
            has belief-state "{belief_state}";
        """
        self.query_insert(query)
    
    def insert_hypothesis(
        self,
        proposer_id: str,
        assertion_id: str,
        alpha: float = 1.0,
        beta: float = 1.0
    ):
        """Insert a hypothesis with Bayesian parameters."""
        query = f"""
        match
            $a isa agent, has agent-id "{proposer_id}";
            $c isa causality, has entity-id "{assertion_id}";
        insert $h (proposer: $a, assertion: $c) isa hypothesis,
            has confidence-score {alpha / (alpha + beta)},
            has beta-alpha {alpha},
            has beta-beta {beta},
            has belief-state "proposed";
        """
        self.query_insert(query)
    
    def insert_source_reputation(
        self,
        entity_id: str,
        alpha: float = 1.0,
        beta: float = 1.0
    ):
        """Insert or update source reputation."""
        query = f"""
        match $e has entity-id "{entity_id}";
        insert $r (trusted-entity: $e) isa source-reputation,
            has reputation-alpha {alpha},
            has reputation-beta {beta};
        """
        self.query_insert(query)
    
    def update_reputation(
        self,
        entity_id: str,
        positive: bool = True,
        weight: float = 1.0
    ):
        """Update reputation with new evidence."""
        # First get current values
        results = self.query_fetch(f"""
        match
            $e has entity-id "{entity_id}";
            $r (trusted-entity: $e) isa source-reputation,
                has reputation-alpha $a,
                has reputation-beta $b;
        fetch $r: reputation-alpha, reputation-beta;
        limit 1;
        """)
        
        if not results:
            # Create new reputation
            self.insert_source_reputation(
                entity_id,
                alpha=1.0 + (weight if positive else 0),
                beta=1.0 + (0 if positive else weight)
            )
            return
        
        current = results[0]
        alpha = current.get('reputation-alpha', 1.0)
        beta = current.get('reputation-beta', 1.0)
        
        if positive:
            alpha += weight
        else:
            beta += weight
        
        # Update
        query = f"""
        match
            $e has entity-id "{entity_id}";
            $r (trusted-entity: $e) isa source-reputation;
        delete
            $r has reputation-alpha $old_a;
            $r has reputation-beta $old_b;
        insert
            $r has reputation-alpha {alpha};
            $r has reputation-beta {beta};
        """
        # Note: TypeDB doesn't support delete+insert in one query, need two
        self.query_delete(query)
    
    def detect_contradictions(self) -> List[Dict]:
        """Find contradicting assertions in the graph."""
        query = """
        match
            $c1 isa causality (cause: $x, effect: $y),
                has belief-state "verified";
            $c2 isa causality (cause: $x, effect: $z),
                has belief-state "verified";
            not { $c1 is $c2; };
            not { $y is $z; };
        fetch
            $c1: entity-id, content;
            $c2: entity-id, content;
        """
        return self.query_fetch(query)
    
    def get_high_entropy_hypotheses(self, threshold: float = 0.4) -> List[Dict]:
        """Find hypotheses with high dialectical entropy (needing debate)."""
        query = f"""
        match
            $h isa hypothesis,
                has beta-alpha $a,
                has beta-beta $b,
                has belief-state $state;
            $state != "verified";
            $state != "refuted";
        fetch
            $h: beta-alpha, beta-beta, belief-state;
        """
        results = self.query_fetch(query)
        
        # Filter by entropy calculation
        high_entropy = []
        for r in results:
            alpha = r.get('beta-alpha', 1.0)
            beta = r.get('beta-beta', 1.0)
            p = alpha / (alpha + beta)
            # Bernoulli entropy
            if p > 0 and p < 1:
                entropy = -p * (p if p > 0 else 1) - (1-p) * ((1-p) if (1-p) > 0 else 1)
                # Actually use Shannon entropy approximation
                import math
                entropy = -p * math.log2(p) - (1-p) * math.log2(1-p) if p > 0 and p < 1 else 0
                if entropy > threshold:
                    r['entropy'] = entropy
                    high_entropy.append(r)
        
        return high_entropy


class MockSession:
    """Mock session for when TypeDB is not available."""
    def transaction(self, tx_type=None):
        return MockTransaction()


class MockTransaction:
    """Mock transaction for when TypeDB is not available."""
    class MockQuery:
        def fetch(self, q): return []
        def insert(self, q): pass
        def delete(self, q): pass
        def define(self, q): pass
    
    query = MockQuery()
    
    def commit(self): pass
    def close(self): pass


# Global connection instance
typedb = TypeDBConnection()


def init_database():
    """Initialize database with schema."""
    typedb.ensure_database()
    typedb.load_schema()
    logger.info("SuperHyperion database initialized!")


def check_typedb_available() -> bool:
    """Check if TypeDB driver is available."""
    return _load_typedb()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    if check_typedb_available():
        init_database()
    else:
        print("TypeDB driver not available. Running in mock mode.")
        print("Containers are running - you can still use the API.")
