"""
Intent Store Abstraction

Persistence layer for write-intents and status events.
Provides InMemory (testing) and TypeDB (production) implementations.

INVARIANTS:
- Events are append-only (no delete/update)
- Intent status updates are atomic
- All writes are auditable
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Store Protocol (Interface)
# =============================================================================

class IntentStore(ABC):
    """
    Abstract store for write-intents and status events.
    
    Two implementations:
    - InMemoryIntentStore: For unit tests
    - TypeDBIntentStore: For production
    """

    # =========================================================================
    # Intent Operations
    # =========================================================================

    @abstractmethod
    def insert_intent(
        self,
        intent_id: str,
        intent_type: str,
        lane: str,
        payload: Dict[str, Any],
        impact_score: float,
        status: str,
        created_at: datetime,
        expires_at: Optional[datetime] = None,
        scope_lock_id: Optional[str] = None,
        supersedes_intent_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
    ) -> None:
        """Insert a new intent. Raises if intent_id exists."""
        pass

    @abstractmethod
    def get_by_proposal_id(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """Get intent by proposal_id. Returns None if not found."""
        pass

    @abstractmethod
    def update_intent_status(
        self,
        intent_id: str,
        new_status: str,
    ) -> None:
        """Update intent's denormalized status. Raises if not found."""
        pass

    @abstractmethod
    def get_intent(self, intent_id: str) -> Optional[Dict[str, Any]]:
        """Get intent by ID. Returns None if not found."""
        pass

    @abstractmethod
    def list_intents_by_status(self, status: str) -> List[Dict[str, Any]]:
        """List all intents with given status."""
        pass

    @abstractmethod
    def list_expirable_intents(self, cutoff: datetime) -> List[Dict[str, Any]]:
        """List intents with expires_at < cutoff and non-terminal status."""
        pass

    # =========================================================================
    # Event Operations (Append-Only)
    # =========================================================================

    @abstractmethod
    def append_event(
        self,
        event_id: str,
        intent_id: str,
        from_status: str,
        to_status: str,
        actor_type: str,
        actor_id: str,
        created_at: datetime,
        rationale: Optional[str] = None,
        defer_until: Optional[datetime] = None,
        execution_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Append a status event. NEVER modify or delete events.
        
        Constitutional: Events are append-only audit trail.
        """
        pass

    @abstractmethod
    def get_events(self, intent_id: str) -> List[Dict[str, Any]]:
        """Get all events for an intent, ordered by created_at."""
        pass

    @abstractmethod
    def has_event_with_status(self, intent_id: str, to_status: str) -> bool:
        """Check if intent has an event transitioning to given status."""
        pass


# =============================================================================
# In-Memory Implementation (Testing)
# =============================================================================

class InMemoryIntentStore(IntentStore):
    """
    In-memory store for unit testing.
    
    Thread-safe for single-threaded tests only.
    """

    def __init__(self):
        self._intents: Dict[str, Dict[str, Any]] = {}
        self._events: Dict[str, List[Dict[str, Any]]] = {}  # intent_id -> events

    def insert_intent(
        self,
        intent_id: str,
        intent_type: str,
        lane: str,
        payload: Dict[str, Any],
        impact_score: float,
        status: str,
        created_at: datetime,
        expires_at: Optional[datetime] = None,
        scope_lock_id: Optional[str] = None,
        supersedes_intent_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
    ) -> None:
        if intent_id in self._intents:
            raise ValueError(f"Intent already exists: {intent_id}")

        self._intents[intent_id] = {
            "intent_id": intent_id,
            "intent_type": intent_type,
            "lane": lane,
            "payload": payload,
            "impact_score": impact_score,
            "status": status,
            "created_at": created_at,
            "expires_at": expires_at,
            "scope_lock_id": scope_lock_id,
            "supersedes_intent_id": supersedes_intent_id,
            "proposal_id": proposal_id,
        }
        self._events[intent_id] = []

    def get_by_proposal_id(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        for intent in self._intents.values():
            if intent.get("proposal_id") == proposal_id:
                return intent
        return None

    def update_intent_status(self, intent_id: str, new_status: str) -> None:
        if intent_id not in self._intents:
            raise KeyError(f"Intent not found: {intent_id}")
        self._intents[intent_id]["status"] = new_status

    def get_intent(self, intent_id: str) -> Optional[Dict[str, Any]]:
        return self._intents.get(intent_id)

    def list_intents_by_status(self, status: str) -> List[Dict[str, Any]]:
        return [i for i in self._intents.values() if i["status"] == status]

    def list_expirable_intents(self, cutoff: datetime) -> List[Dict[str, Any]]:
        terminal = {"rejected", "cancelled", "expired", "executed", "failed"}
        return [
            i for i in self._intents.values()
            if i.get("expires_at") and i["expires_at"] < cutoff and i["status"] not in terminal
        ]

    def append_event(
        self,
        event_id: str,
        intent_id: str,
        from_status: str,
        to_status: str,
        actor_type: str,
        actor_id: str,
        created_at: datetime,
        rationale: Optional[str] = None,
        defer_until: Optional[datetime] = None,
        execution_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        if intent_id not in self._events:
            self._events[intent_id] = []

        self._events[intent_id].append({
            "event_id": event_id,
            "intent_id": intent_id,
            "from_status": from_status,
            "to_status": to_status,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "created_at": created_at,
            "rationale": rationale,
            "defer_until": defer_until,
            "execution_id": execution_id,
            "error": error,
        })

    def get_events(self, intent_id: str) -> List[Dict[str, Any]]:
        events = self._events.get(intent_id, [])
        return sorted(events, key=lambda e: e["created_at"])

    def has_event_with_status(self, intent_id: str, to_status: str) -> bool:
        events = self._events.get(intent_id, [])
        return any(e["to_status"] == to_status for e in events)


# =============================================================================
# TypeDB Implementation (Production)
# =============================================================================

def _escape(s: str) -> str:
    """Escape string for TypeQL."""
    if s is None:
        return ""
    return s.replace("\\", "\\\\").replace('"', '\\"')


class TypeDBIntentStore(IntentStore):
    """
    TypeDB-backed store for production.
    
    INVARIANTS:
    - Events are append-only (insert only, never delete/update)
    - Intent status updates use delete+insert pattern for attributes
    """

    def __init__(self, driver, database: str = "scientific_knowledge"):
        """
        Initialize with TypeDB driver.
        
        Args:
            driver: TypeDB driver instance
            database: Database name
        """
        self.driver = driver
        self.database = database

    def _write_query(self, query: str) -> None:
        """Execute a write query."""
        from typedb.driver import SessionType, TransactionType

        with self.driver.session(self.database, SessionType.DATA) as session:
            with session.transaction(TransactionType.WRITE) as tx:
                tx.query.insert(query)
                tx.commit()

    def _read_query(self, query: str) -> List[Dict[str, Any]]:
        """Execute a read query and return results."""
        from typedb.driver import SessionType, TransactionType

        results = []
        with self.driver.session(self.database, SessionType.DATA) as session:
            with session.transaction(TransactionType.READ) as tx:
                answer = tx.query.get(query)
                for concept_map in answer:
                    row = {}
                    for var in concept_map.variables():
                        concept = concept_map.get(var)
                        if hasattr(concept, 'get_value'):
                            row[var] = concept.get_value()
                        elif hasattr(concept, 'get_iid'):
                            row[var] = concept.get_iid()
                    results.append(row)
        return results

    def insert_intent(
        self,
        intent_id: str,
        intent_type: str,
        lane: str,
        payload: Dict[str, Any],
        impact_score: float,
        status: str,
        created_at: datetime,
        expires_at: Optional[datetime] = None,
        scope_lock_id: Optional[str] = None,
        supersedes_intent_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
    ) -> None:
        payload_json = json.dumps(payload, default=str)
        created_str = created_at.isoformat()

        query = f'''
            insert $intent isa write-intent,
                has intent-id "{_escape(intent_id)}",
                has intent-type "{_escape(intent_type)}",
                has intent-status "{_escape(status)}",
                has impact-score {impact_score},
                has lane "{_escape(lane)}",
                has json "{_escape(payload_json)}",
                has created-at {created_str}'''

        if expires_at:
            query += f',\n                has expires-at {expires_at.isoformat()}'
        if scope_lock_id:
            query += f',\n                has scope-lock-id "{_escape(scope_lock_id)}"'
        if supersedes_intent_id:
            query += f',\n                has supersedes-intent-id "{_escape(supersedes_intent_id)}"'
        if proposal_id:
            query += f',\n                has proposal-id "{_escape(proposal_id)}"'

        query += ";"

        self._write_query(query)
        logger.info(f"Inserted intent: {intent_id}")

    def update_intent_status(self, intent_id: str, new_status: str) -> None:
        """Update intent status using delete+insert pattern."""
        from typedb.driver import SessionType, TransactionType

        with self.driver.session(self.database, SessionType.DATA) as session:
            with session.transaction(TransactionType.WRITE) as tx:
                # Delete old status
                delete_query = f'''
                    match $i isa write-intent, has intent-id "{_escape(intent_id)}",
                          has intent-status $s;
                    delete $i has $s;
                '''
                tx.query.delete(delete_query)

                # Insert new status
                insert_query = f'''
                    match $i isa write-intent, has intent-id "{_escape(intent_id)}";
                    insert $i has intent-status "{_escape(new_status)}";
                '''
                tx.query.insert(insert_query)
                tx.commit()

        logger.info(f"Updated intent {intent_id} status to {new_status}")

    def get_intent(self, intent_id: str) -> Optional[Dict[str, Any]]:
        query = f'''
            match $i isa write-intent,
                  has intent-id $id,
                  has intent-type $type,
                  has intent-status $status,
                  has impact-score $score,
                  has json $payload,
                  has created-at $created;
            $id = "{_escape(intent_id)}";

            try {{ $i has lane $lane; }};
            try {{ $i has scope-lock-id $slid; }};
            try {{ $i has proposal-id $pid; }};
            try {{ $i has expires-at $expires; }};
            try {{ $i has supersedes-intent-id $sup; }};

            get $id, $type, $status, $score, $payload, $created,
                $lane, $slid, $pid, $expires, $sup;
            limit 1;
        '''

        results = self._read_query(query)
        if not results:
            return None

        row = results[0]
        return {
            "intent_id": row.get("id"),
            "intent_type": row.get("type"),
            "status": row.get("status"),
            "impact_score": row.get("score"),
            "payload": json.loads(row.get("payload", "{}")),
            "created_at": row.get("created"),
            "lane": row.get("lane", "grounded"),
            "scope_lock_id": row.get("slid"),
            "proposal_id": row.get("pid"),
            "expires_at": row.get("expires"),
            "supersedes_intent_id": row.get("sup"),
        }

    def get_by_proposal_id(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        query = f'''
            match $i isa write-intent,
                  has proposal-id "{_escape(proposal_id)}",
                  has intent-id $id;
            get $id;
            limit 1;
        '''
        results = self._read_query(query)
        if not results:
            return None
        iid = results[0].get("id")
        return self.get_intent(iid) if iid else None

    def list_intents_by_status(self, status: str) -> List[Dict[str, Any]]:
        query = f'''
            match $i isa write-intent,
                  has intent-id $id,
                  has intent-type $type,
                  has intent-status "{_escape(status)}",
                  has created-at $created;
            get $id, $type, $created;
        '''

        results = self._read_query(query)
        return [
            {
                "intent_id": r.get("id"),
                "intent_type": r.get("type"),
                "status": status,
                "created_at": r.get("created"),
            }
            for r in results
        ]

    def list_expirable_intents(self, cutoff: datetime) -> List[Dict[str, Any]]:
        cutoff_str = cutoff.isoformat()
        query = f'''
            match $i isa write-intent,
                  has intent-id $id,
                  has intent-status $status,
                  has expires-at $exp;
            $exp < {cutoff_str};
            not {{ $status = "rejected"; }};
            not {{ $status = "cancelled"; }};
            not {{ $status = "expired"; }};
            not {{ $status = "executed"; }};
            not {{ $status = "failed"; }};
            get $id, $status, $exp;
        '''

        results = self._read_query(query)
        return [
            {
                "intent_id": r.get("id"),
                "status": r.get("status"),
                "expires_at": r.get("exp"),
            }
            for r in results
        ]

    def append_event(
        self,
        event_id: str,
        intent_id: str,
        from_status: str,
        to_status: str,
        actor_type: str,
        actor_id: str,
        created_at: datetime,
        rationale: Optional[str] = None,
        defer_until: Optional[datetime] = None,
        execution_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Append event. NEVER delete or update events.
        
        Constitutional: Events are append-only audit trail.
        """
        extra_json = json.dumps({
            "error": error,
        }) if error else "{}"

        query = f'''
            insert $e isa intent-status-event,
                has entity-id "{_escape(event_id)}",
                has intent-id "{_escape(intent_id)}",
                has from-status "{_escape(from_status)}",
                has to-status "{_escape(to_status)}",
                has actor-type "{_escape(actor_type)}",
                has agent-id "{_escape(actor_id)}",
                has created-at {created_at.isoformat()}'''

        if rationale:
            query += f',\n                has rationale "{_escape(rationale)}"'
        if defer_until:
            query += f',\n                has defer-until {defer_until.isoformat()}'
        if execution_id:
            query += f',\n                has execution-id "{_escape(execution_id)}"'
        if error:
            query += f',\n                has json "{_escape(extra_json)}"'

        query += ";"

        self._write_query(query)
        logger.info(f"Appended event {event_id} for intent {intent_id}: {from_status} → {to_status}")

    def get_events(self, intent_id: str) -> List[Dict[str, Any]]:
        query = f'''
            match $e isa intent-status-event,
                  has entity-id $eid,
                  has intent-id "{_escape(intent_id)}",
                  has from-status $from,
                  has to-status $to,
                  has actor-type $atype,
                  has agent-id $aid,
                  has created-at $created;
            get $eid, $from, $to, $atype, $aid, $created;
            sort $created asc;
        '''

        results = self._read_query(query)
        return [
            {
                "event_id": r.get("eid"),
                "intent_id": intent_id,
                "from_status": r.get("from"),
                "to_status": r.get("to"),
                "actor_type": r.get("atype"),
                "actor_id": r.get("aid"),
                "created_at": r.get("created"),
            }
            for r in results
        ]

    def has_event_with_status(self, intent_id: str, to_status: str) -> bool:
        query = f'''
            match $e isa intent-status-event,
                  has intent-id "{_escape(intent_id)}",
                  has to-status "{_escape(to_status)}";
            get $e; limit 1;
        '''

        results = self._read_query(query)
        return len(results) > 0
