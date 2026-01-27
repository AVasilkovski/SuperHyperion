"""
CLI Wiring

Constructs IntentStore + WriteIntentService based on environment.

Production: TypeDBIntentStore
Testing: InMemoryIntentStore (injected)
"""

import os
from typing import Optional

from src.hitl.intent_store import IntentStore, InMemoryIntentStore, TypeDBIntentStore
from src.hitl.intent_service import WriteIntentService


def get_intent_store() -> IntentStore:
    """
    Get the appropriate IntentStore based on environment.
    
    Returns:
        TypeDBIntentStore for production
        InMemoryIntentStore if SUPERHYPERION_TEST_MODE=1
    """
    if os.environ.get("SUPERHYPERION_TEST_MODE") == "1":
        return InMemoryIntentStore()
    
    # Production: connect to TypeDB
    try:
        from typedb.driver import TypeDB
        
        typedb_host = os.environ.get("TYPEDB_HOST", "localhost")
        typedb_port = os.environ.get("TYPEDB_PORT", "1729")
        database = os.environ.get("TYPEDB_DATABASE", "scientific_knowledge")
        
        driver = TypeDB.core_driver(f"{typedb_host}:{typedb_port}")
        return TypeDBIntentStore(driver, database)
    except ImportError:
        # TypeDB driver not installed, fall back to in-memory
        import logging
        logging.warning("TypeDB driver not available, using InMemoryIntentStore")
        return InMemoryIntentStore()
    except Exception as e:
        import logging
        logging.warning(f"Failed to connect to TypeDB: {e}, using InMemoryIntentStore")
        return InMemoryIntentStore()


def get_intent_service(store: Optional[IntentStore] = None) -> WriteIntentService:
    """
    Get WriteIntentService with the appropriate store.
    
    Args:
        store: Optional store to inject (for testing)
    
    Returns:
        WriteIntentService instance
    """
    if store is None:
        store = get_intent_store()
    return WriteIntentService(store=store)


# Global service instance (lazily initialized)
_service: Optional[WriteIntentService] = None


def get_service() -> WriteIntentService:
    """Get or create the global WriteIntentService instance."""
    global _service
    if _service is None:
        _service = get_intent_service()
    return _service
