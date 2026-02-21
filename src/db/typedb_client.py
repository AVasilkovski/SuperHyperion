"""
TypeDB Connection and Schema Management

Provides connection utilities and schema loading for the SuperHyperion knowledge graph.
Handles Python 3.13 compatibility with lazy imports.
"""

import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.config import config

logger = logging.getLogger(__name__)

# ============================================================================
# Lazy TypeDB Import (Python 3.13 compatibility)
# ============================================================================

TYPEDB_AVAILABLE = False
TypeDB = None
TypeDBDriver = None
TransactionType = None
Credentials = None
DriverOptions = None
SessionType = None

def _load_typedb():
    """Lazy load TypeDB driver to handle import errors gracefully."""
    global TYPEDB_AVAILABLE, TypeDB, TypeDBDriver, TransactionType, Credentials, DriverOptions, SessionType

    if TYPEDB_AVAILABLE:
        return True

    try:
        from typedb.driver import Credentials as _Credentials
        from typedb.driver import DriverOptions as _DriverOptions
        from typedb.driver import TransactionType as _TransactionType
        from typedb.driver import TypeDB as _TypeDB
        TypeDB = _TypeDB
        TypeDBDriver = getattr(__import__("typedb.driver", fromlist=["TypeDBDriver"]), "TypeDBDriver", None)
        TransactionType = _TransactionType
        Credentials = _Credentials
        DriverOptions = _DriverOptions
        TYPEDB_AVAILABLE = True
        logger.info("TypeDB driver loaded successfully")
        return True

    except ImportError as e:
        logger.warning(f"TypeDB driver not available: {e}")
        logger.warning(
            "TypeDB import failed; ensure typedb-driver is installed and compatible "
            "with this runtime."
        )
        return False


class TypeDBConnection:
    """Manages TypeDB connection and operations."""

    def __init__(self, address: Optional[str] = None, database: Optional[str] = None):
        self.address = address or config.typedb.address
        self.database = database or config.typedb.database
        self._driver = None
        self._mock_mode = False

    @property
    def driver(self):
        """Backward-compatible raw driver accessor for legacy call sites."""
        return self._driver

    def connect(self):
        """Establish connection to TypeDB."""
        if not _load_typedb():
            logger.warning("Running in mock mode - TypeDB not available")
            self._mock_mode = True
            return None

        if self._driver is None:
            creds = Credentials(config.typedb.username, config.typedb.password)
            # Ops 1.0: TLS driven by config (local Core = False, Cloud = True)
            opts = DriverOptions(
                is_tls_enabled=config.typedb.tls_enabled,
                tls_root_ca_path=config.typedb.tls_root_ca_path,
            )
            self._driver = TypeDB.driver(self.address, creds, opts)
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

    def load_schema(self, schema_paths: Optional[List[Path]] = None):
        """
        Load TypeQL schema into database.
        
        Args:
            schema_paths: List of paths to .tql schema files. 
                        If None, loads scientific_knowledge.tql and schema_v22_patch.tql.
        """
        if schema_paths is None:
            base = Path(__file__).parent.parent / "schema" / "scientific_knowledge.tql"
            # patch = Path(__file__).parent.parent / "schema" / "schema_v22_patch.tql" # Merged into unified schema
            schema_paths = [base]

        if self._mock_mode:
            for p in schema_paths:
                logger.info(f"[MOCK] Would load schema from: {p}")
            return

        try:
            schema_content = "\n\n".join(p.read_text(encoding="utf-8") for p in schema_paths)
        except Exception as e:
            logger.error(f"Failed to read schema files: {e}")
            return

        driver = self.connect()
        if driver is None:
            return

        try:
            with driver.transaction(self.database, TransactionType.SCHEMA) as tx:
                tx.query(schema_content).resolve()
                tx.commit()
            logger.info(f"Schema loaded: {[p.name for p in schema_paths]}")
        except Exception as e:
            logger.error(f"Failed to load schema: {e}")

    @contextmanager
    def session(self, session_type=None):
        """
        [DEPRECATED] Context manager for database sessions.
        TypeDB 3.x is session-less. This now returns a MockSession that yields nothing useful
        but preserves some legacy call sites. Use .transaction() instead.
        """
        logger.warning("TypeDBConnection.session() is deprecated in TypeDB 3.x. Use .transaction() directly.")
        yield MockSession()

    @staticmethod
    def _tx_execute(tx, query: str):
        """Execute TypeQL against TypeDB 3.x callable API and legacy query objects."""
        query_api = tx.query
        if callable(query_api):
            result = query_api(query)
            return result.resolve() if hasattr(result, "resolve") else result

        if hasattr(query_api, "insert"):
            q = " ".join(query.strip().lower().split())
            is_delete = " delete " in f" {q} " and " insert " not in f" {q} "
            if is_delete and hasattr(query_api, "delete"):
                query_api.delete(query)
            else:
                query_api.insert(query)
            return None

        raise TypeError("Unsupported TypeDB query API")

    @staticmethod
    def _to_rows(answer) -> List[Dict]:
        """Normalize driver answers into list-of-dicts with stable keys."""
        if answer is None:
            return []

        if hasattr(answer, "as_concept_documents"):
            return list(answer.as_concept_documents())

        if hasattr(answer, "as_concept_rows"):
            rows: List[Dict] = []
            for concept_row in answer.as_concept_rows():
                row: Dict[str, object] = {}
                for col in concept_row.column_names():
                    key = col[1:] if isinstance(col, str) and col.startswith("$") else col
                    concept = concept_row.get(col)
                    if concept is None:
                        continue
                    if hasattr(concept, "is_attribute") and concept.is_attribute():
                        row[key] = concept.as_attribute().get_value()
                    elif hasattr(concept, "is_value") and concept.is_value():
                        row[key] = concept.as_value().get()
                    elif hasattr(concept, "get_iid"):
                        row[key] = concept.get_iid()
                    else:
                        row[key] = str(concept)
                rows.append(row)
            return rows

        return list(answer)

    @contextmanager
    def transaction(self, tx_type=None, options=None):
        """Context manager for transactions."""
        if self._mock_mode:
            yield MockTransaction()
            return

        if tx_type is None:
            tx_type = TransactionType.READ

        driver = self.connect()
        if driver is None:
            yield MockTransaction()
            return

        with driver.transaction(self.database, tx_type, options) as tx:
            yield tx
            if tx_type == TransactionType.WRITE:
                tx.commit()

    def query_fetch(self, query: str) -> List[Dict]:
        """Execute a read query and return normalized results."""
        if self._mock_mode:
            logger.debug(f"[MOCK] query_fetch: {query[:100]}...")
            return []

        tx_type = TransactionType.READ if TransactionType else "READ"
        with self.transaction(tx_type) as tx:
            answer = self._tx_execute(tx, query)
            return self._to_rows(answer)

    def query_insert(self, query: str, *, cap=None):
        """Execute an insert query. Requires WriteCap."""
        from src.db.capabilities import WriteCap
        if not isinstance(cap, WriteCap):
            raise PermissionError("query_insert requires a WriteCap")
        if self._mock_mode:
            logger.debug(f"[MOCK] query_insert: {query[:100]}...")
            return

        tx_type = TransactionType.WRITE if TransactionType else "WRITE"
        with self.transaction(tx_type) as tx:
            self._tx_execute(tx, query)

    def query_delete(self, query: str, *, cap=None):
        """Execute a delete query. Requires WriteCap."""
        from src.db.capabilities import WriteCap
        if not isinstance(cap, WriteCap):
            raise PermissionError("query_delete requires a WriteCap")
        if self._mock_mode:
            logger.debug(f"[MOCK] query_delete: {query[:100]}...")
            return

        tx_type = TransactionType.WRITE if TransactionType else "WRITE"
        with self.transaction(tx_type) as tx:
            self._tx_execute(tx, query)

    # ========================================================================
    # v2.1 Typed Operations
    # ========================================================================

    def insert_proposition(
        self,
        entity_id: str,
        content: str,
        confidence: float = 0.5,
        belief_state: str = "proposed",
        *,
        cap=None
    ):
        """Insert a proposition into the graph."""
        query = f"""
        insert $p isa proposition,
            has entity-id "{entity_id}",
            has content "{content}",
            has confidence-score {confidence},
            has belief-state "{belief_state}";
        """
        self.query_insert(query, cap=cap)

    def insert_hypothesis(
        self,
        proposer_id: str,
        assertion_id: str,
        alpha: float = 1.0,
        beta: float = 1.0,
        *,
        cap=None
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
        self.query_insert(query, cap=cap)

    def insert_source_reputation(
        self,
        entity_id: str,
        entity_type: str,
        alpha: float = 1.0,
        beta: float = 1.0,
        *,
        cap=None
    ):
        """Insert or update source reputation."""
        query = f"""
        match $e isa {entity_type}, has entity-id "{entity_id}";
        insert
        $s isa source-reputation,
            has reputation-alpha {alpha},
            has reputation-beta {beta},
            has last-updated "{datetime.now().isoformat()}";
        (trusted-entity: $e) isa source-reputation;
        """
        self.query_insert(query, cap=cap)

    def update_reputation(
        self,
        entity_id: str,
        positive: bool = True,
        weight: float = 1.0,
        *,
        cap=None
    ):
        """Update reputation with new evidence."""
        # First get current values
        results = self.query_fetch(f"""
        match
            $e isa $entity_type, has entity-id "{entity_id}";
            $r (trusted-entity: $e) isa source-reputation,
                has reputation-alpha $a,
                has reputation-beta $b;
        fetch $r: reputation-alpha, reputation-beta, $e: entity-id, $entity_type;
        limit 1;
        """)

        if not results:
            # This should not happen if the entity exists and has reputation,
            # but if it's a new entity or reputation, we need its type.
            # For now, assume it's an agent if not found.
            # TODO: Refine this to fetch entity type if reputation is not found.
            logger.warning(f"No existing reputation found for {entity_id}. Cannot update.")
            return

        current = results[0]
        alpha = current.get('reputation-alpha', 1.0)
        beta = current.get('reputation-beta', 1.0)
        entity_type = current.get('entity_type', 'agent') # Default to agent if not found

        if positive:
            alpha += weight
        else:
            beta += weight

        # Update
        # v2.2 Fix: Separate delete and insert operations
        delete_query = f"""
        match 
            $s isa source-reputation, has trusted-entity $entity;
            $entity has entity-id "{entity_id}";
        delete $s;
        """

        insert_query = f"""
        match $entity isa {entity_type}, has entity-id "{entity_id}";
        insert
        $s isa source-reputation,
            has reputation-alpha {alpha},
            has reputation-beta {beta},
            has last-updated "{datetime.now().isoformat()}";
        (trusted-entity: $entity) isa source-reputation;
        """

        if self._mock_mode:
            logger.info(f"[MOCK] Would update reputation for {entity_id}")
            return

        # Execute separately
        self.query_delete(delete_query, cap=cap)
        self.query_insert(insert_query, cap=cap)

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
        query = """
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
