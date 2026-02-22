"""
Template Store

Persistence layer for template metadata and governance.
Handles freezing, tainting, and manifest synchronization.

INVARIANTS:
- Metadata is immutable (except status updates)
- Status/Frozen/Tainted attributes use delete-insert
- All lifecycle events are logged append-only
"""

import hashlib
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .template_metadata import TemplateMetadata, TemplateStatus, TemplateVersion

logger = logging.getLogger(__name__)


def _escape(s: str) -> str:
    if s is None:
        return ""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _iso_now() -> str:
    """Return TypeDB `datetime` literal string (timezone-naive UTC)."""
    dt = datetime.now(timezone.utc).replace(microsecond=0)
    # `created-at` in schema is `datetime` (not `datetime-tz`), so drop timezone suffix.
    return dt.replace(tzinfo=None).isoformat(timespec="seconds")


def _make_template_event_id(
    template_id: str,
    version: str,
    event_type: str,
    evidence_id: Optional[str] = None,
) -> str:
    """
    Deterministic lifecycle event ID.
    Prevents duplicate events under concurrent freeze/taint calls.
    Uses schema key: template-lifecycle-event owns entity-id @key
    Format: tevt-{event_type[:4]}-{hash(tuple)[:12]}
    """
    # Deterministic seed tuple
    seed = f"{template_id}@{version}:{event_type}:{evidence_id or ''}"
    h = hashlib.md5(seed.encode("utf-8")).hexdigest()[:12]
    # Prefix helps with readability/debugging
    return f"tevt-{event_type[:4]}-{h}"


class TemplateStore(ABC):
    """Abstract store for template metadata and audit logs."""

    @abstractmethod
    def insert_metadata(self, metadata: TemplateMetadata) -> None:
        """Insert or update template metadata."""
        pass

    @abstractmethod
    def get_metadata(self, template_id: str, version: str) -> Optional[TemplateMetadata]:
        """Get metadata for specific version."""
        pass

    @abstractmethod
    def freeze(
        self,
        template_id: str,
        version: str,
        evidence_id: str,
        claim_id: Optional[str] = None,
        scope_lock_id: Optional[str] = None,
        actor: str = "system",
    ) -> None:
        """Freeze a template on first evidence."""
        pass

    @abstractmethod
    def taint(
        self,
        template_id: str,
        version: str,
        reason: str,
        superseded_by: Optional[str] = None,
        actor: str = "system",
    ) -> None:
        """Mark a template as tainted."""
        pass

    @abstractmethod
    def append_event(
        self,
        template_id: str,
        version: str,
        event_type: str,
        actor: str,
        rationale: str = "",
        extra_json: Dict[str, Any] = None,
    ) -> None:
        """Append audit event."""
        pass


class InMemoryTemplateStore(TemplateStore):
    """In-memory implementation for testing."""

    def __init__(self):
        self.metadata: Dict[str, TemplateMetadata] = {}  # qualified_id -> meta
        self.events: List[Dict] = []

    def _qid(self, tid, v):
        return f"{tid}@{v}"

    def insert_metadata(self, metadata: TemplateMetadata) -> None:
        qid = metadata.qualified_id
        if qid in self.metadata:
            return
        # Store a copy to simulate immutability
        import copy

        self.metadata[qid] = copy.deepcopy(metadata)
        self.append_event(metadata.template_id, str(metadata.version), "registered", "system")

    def get_metadata(self, template_id: str, version: str) -> Optional[TemplateMetadata]:
        # Return copy to prevent mutation
        import copy

        meta = self.metadata.get(self._qid(template_id, version))
        return copy.deepcopy(meta) if meta else None

    def freeze(
        self, template_id, version, evidence_id, claim_id=None, scope_lock_id=None, actor="system"
    ):
        # In-memory stores update the *stored* object, not the one returned by get_metadata earlier
        qid = self._qid(template_id, version)
        if qid not in self.metadata:
            return

        meta = self.metadata[qid]
        if meta.frozen:
            return

        new_meta = replace(
            meta,
            frozen=True,
            frozen_at=datetime.now(timezone.utc),
            first_evidence_id=evidence_id,
            freeze_claim_id=claim_id,
            freeze_scope_lock_id=scope_lock_id,
        )
        self.metadata[qid] = new_meta

        self.append_event(
            template_id, version, "frozen", actor, extra_json={"evidence_id": evidence_id}
        )

    def taint(self, template_id, version, reason, superseded_by=None, actor="system"):
        qid = self._qid(template_id, version)
        if qid not in self.metadata:
            return

        meta = self.metadata[qid]
        new_meta = replace(
            meta,
            tainted=True,
            tainted_at=datetime.now(timezone.utc),
            tainted_reason=reason,
            superseded_by=superseded_by,
        )
        self.metadata[qid] = new_meta

        self.append_event(template_id, version, "tainted", actor, rationale=reason)

    def append_event(self, template_id, version, event_type, actor, rationale="", extra_json=None):
        self.events.append(
            {
                "template_id": template_id,
                "version": version,
                "event_type": event_type,
                "actor": actor,
                "rationale": rationale,
                "extra_json": extra_json or {},
                "created_at": datetime.now(timezone.utc),
            }
        )


class TypeDBTemplateStore(TemplateStore):
    """
    TypeDB implementation of TemplateStore.

    Uses delete+insert for mutable attributes (status, frozen, tainted).
    Logs all changes to template-lifecycle-event.
    """

    def __init__(self, driver, database: str = "scientific_knowledge"):
        self.driver = driver
        self.database = database

    @staticmethod
    def _exec_query(tx, query: str):
        """Execute TypeQL across TypeDB driver API variants."""
        query_api = tx.query
        if callable(query_api):
            result = query_api(query)
            if hasattr(result, "resolve"):
                return result.resolve()
            return result

        if hasattr(query_api, "insert"):
            query_api.insert(query)
            return None

        raise TypeError("Unsupported TypeDB query API")

    def _write_query(self, query: str) -> None:
        from typedb.driver import TransactionType

        with self.driver.transaction(self.database, TransactionType.WRITE) as tx:
            self._exec_query(tx, query)
            tx.commit()

    def _read_query(self, query: str) -> List[Dict[str, Any]]:
        from typedb.driver import TransactionType

        results: List[Dict[str, Any]] = []
        with self.driver.transaction(self.database, TransactionType.READ) as tx:
            answer = self._exec_query(tx, query)

            if answer is None:
                return results

            if hasattr(answer, "as_concept_rows"):
                for concept_row in answer.as_concept_rows():
                    row: Dict[str, Any] = {}
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
                    results.append(row)
                return results

            for concept_map in answer:
                row = {}
                for var in concept_map.variables():
                    concept = concept_map.get(var)
                    var_name = var.name() if hasattr(var, "name") else str(var)
                    if hasattr(concept, "get_value"):
                        row[var_name] = concept.get_value()
                    elif hasattr(concept, "get_iid"):
                        row[var_name] = concept.get_iid()
                results.append(row)

        return results

    def append_event(
        self,
        template_id: str,
        version: str,
        event_type: str,
        actor: str,
        rationale: str = "",
        extra_json: Dict[str, Any] = None,
    ) -> None:
        # Generate event entity
        evt_id = f"tevt-{uuid.uuid4().hex[:12]}"
        now = _iso_now()
        json_str = json.dumps(extra_json or {}, sort_keys=True)

        query = f'''
            match $m isa template-metadata,
                has template-id "{_escape(template_id)}",
                has version "{_escape(version)}";
            insert 
                $e isa template-lifecycle-event,
                    has entity-id "{evt_id}",
                    has template-id "{_escape(template_id)}",
                    has version "{_escape(version)}",
                    has event-type "{_escape(event_type)}",
                    has actor "{_escape(actor)}",
                    has rationale "{_escape(rationale)}",
                    has json "{_escape(json_str)}",
                    has created-at {now};
                ($m, $e) isa template-has-lifecycle-event;
        '''
        self._write_query(query)
        logger.info(f"Appended event {event_type} for {template_id}@{version}")

    def insert_metadata(self, metadata: TemplateMetadata) -> None:
        # Check if exists
        current = self.get_metadata(metadata.template_id, str(metadata.version))
        if current:
            logger.info(f"Metadata already exists for {metadata.qualified_id}, skipping insert.")
            return

        now = _iso_now()

        # Build insert query with cleaner attribute construction
        attributes = [
            f'has template-id "{_escape(metadata.template_id)}"',
            f'has version "{_escape(str(metadata.version))}"',
            f'has spec-hash "{_escape(metadata.spec_hash)}"',
            f'has code-hash "{_escape(metadata.code_hash)}"',
            f'has status "{_escape(metadata.status.value)}"',
            f"has frozen {str(metadata.frozen).lower()}",
            f"has tainted {str(metadata.tainted).lower()}",
            f"has created-at {now}",
        ]

        if metadata.deps_hash:
            attributes.append(f'has deps-hash "{_escape(metadata.deps_hash)}"')

        attr_block = ",\n                ".join(attributes)

        query = f"""
            insert $m isa template-metadata,
                {attr_block};
        """

        self._write_query(query)
        logger.info(f"Inserted metadata for {metadata.qualified_id}")

        # Log registration event
        try:
            self.append_event(
                metadata.template_id,
                str(metadata.version),
                "registered",
                metadata.approved_by or "system",  # Auto-approved bootstrap
                rationale="Initial registration",
            )
        except Exception as e:
            logger.error(f"Failed to log registration event: {e}")

    def get_metadata(self, template_id: str, version: str) -> Optional[TemplateMetadata]:
        query = f'''
            match $m isa template-metadata,
                has template-id "{_escape(template_id)}",
                has version "{_escape(version)}",
                has spec-hash $spec,
                has code-hash $code,
                has status $status,
                has frozen $frozen,
                has tainted $tainted;
            select $spec, $code, $status, $frozen, $tainted;
        '''
        results = self._read_query(query)
        if not results:
            return None

        row = results[0]
        # Construct partially populated metadata
        return TemplateMetadata(
            template_id=template_id,
            version=TemplateVersion.parse(version),
            spec_hash=row.get("spec"),
            code_hash=row.get("code"),
            status=TemplateStatus(row.get("status")),
            frozen=row.get("frozen"),
            tainted=row.get("tainted"),
        )

    def freeze(
        self,
        template_id: str,
        version: str,
        evidence_id: str,
        claim_id: Optional[str] = None,
        scope_lock_id: Optional[str] = None,
        actor: str = "system",
    ) -> None:
        """
        Freeze a template on first evidence.

        HARDENED (concurrency-safe + atomic audit):
        - No pre-read outside the transaction.
        - Only transitions frozen=false -> frozen=true.
        - Lifecycle event is inserted in the same write transaction.
        - If already frozen, this becomes a no-op (no duplicate events).
        """
        now = _iso_now()
        # Deterministic event ID for idempotency
        evt_id = _make_template_event_id(template_id, version, "frozen", evidence_id)

        extra_json = {
            "evidence_id": evidence_id,
            "claim_id": claim_id,
            "scope_lock_id": scope_lock_id,
        }
        json_str = json.dumps(extra_json, sort_keys=True)

        from typedb.driver import TransactionType

        # NOTE: This relies on the invariant that template-metadata always has an explicit
        # frozen attribute at creation time (insert_metadata sets has frozen false).
        # Therefore, "match has frozen false" is a complete guard.

        # Single atomic query for mutation + audit
        query = f'''
            match
              $m isa template-metadata,
                 has template-id "{_escape(template_id)}",
                 has version "{_escape(version)}",
                 has frozen $frozen;
              $frozen == false;

            delete
              has $frozen of $m;

            insert
              $m has frozen true,
                 has frozen-at {now},
                 has first-evidence-id "{_escape(evidence_id)}"
                 {"," if claim_id else ""}{f' has freeze-claim-id "{_escape(claim_id)}"' if claim_id else ""}
                 {"," if scope_lock_id else ""}{f' has freeze-scope-lock-id "{_escape(scope_lock_id)}"' if scope_lock_id else ""};

              $e isa template-lifecycle-event,
                 has entity-id "{evt_id}",
                 has template-id "{_escape(template_id)}",
                 has version "{_escape(version)}",
                 has event-type "frozen",
                 has actor "{_escape(actor)}",
                 has rationale "{_escape(f"Frozen on first evidence {evidence_id}")}",
                 has json "{_escape(json_str)}",
                 has created-at {now};

              ($m, $e) isa template-has-lifecycle-event;
        '''

        # Execute in transaction
        with self.driver.transaction(self.database, TransactionType.WRITE) as tx:
            # Use a single query containing match/delete/insert so it is atomic.
            self._exec_query(tx, query)
            tx.commit()

        logger.info(
            f"Freeze attempted for {template_id}@{version} on evidence {evidence_id} (guarded)"
        )

    def taint(
        self,
        template_id: str,
        version: str,
        reason: str,
        superseded_by: Optional[str] = None,
        actor: str = "system",
    ) -> None:
        now = _iso_now()

        delete_query = f'''
            match $m isa template-metadata,
                has template-id "{_escape(template_id)}",
                has version "{_escape(version)}",
                has tainted $old;
            delete has $old of $m;
        '''

        insert_attrs = [
            "has tainted true",
            f"has tainted-at {now}",
            f'has tainted-reason "{_escape(reason)}"',
        ]
        if superseded_by:
            insert_attrs.append(f'has superseded-by "{_escape(superseded_by)}"')

        attr_block = ",\n                ".join(insert_attrs)

        insert_query = f'''
            match $m isa template-metadata,
                has template-id "{_escape(template_id)}",
                has version "{_escape(version)}";
            insert $m 
                {attr_block};
        '''

        from typedb.driver import TransactionType

        with self.driver.transaction(self.database, TransactionType.WRITE) as tx:
            self._exec_query(tx, delete_query)
            self._exec_query(tx, insert_query)
            tx.commit()

        logger.info(f"TAINTED template {template_id}@{version}: {reason}")

        # Log event
        self.append_event(
            template_id,
            version,
            "tainted",
            actor,
            rationale=reason,
            extra_json={"superseded_by": superseded_by},
        )
