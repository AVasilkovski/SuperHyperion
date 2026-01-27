"""
Template Store

Persistence layer for template metadata and governance.
Handles freezing, tainting, and manifest synchronization.

INVARIANTS:
- Metadata is immutable (except status updates)
- Status/Frozen/Tainted attributes use delete-insert
- All lifecycle events are logged append-only
"""

from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import json
import logging
import uuid

from .template_metadata import TemplateMetadata, TemplateVersion, TemplateStatus

logger = logging.getLogger(__name__)


def _escape(s: str) -> str:
    if s is None:
        return ""
    return s.replace("\\", "\\\\").replace('"', '\\"')

def _iso_now() -> str:
    """Return ISO format string compatible with TypeDB (no microseconds, UTC 'Z')."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
        self.metadata: Dict[str, TemplateMetadata] = {} # qualified_id -> meta
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

    def freeze(self, template_id, version, evidence_id, claim_id=None, scope_lock_id=None, actor="system"):
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
        
        self.append_event(template_id, version, "frozen", actor, 
                         extra_json={"evidence_id": evidence_id})

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
        
        self.append_event(template_id, version, "tainted", actor, 
                         rationale=reason)

    def append_event(self, template_id, version, event_type, actor, rationale="", extra_json=None):
        self.events.append({
            "template_id": template_id,
            "version": version,
            "event_type": event_type,
            "actor": actor,
            "rationale": rationale,
            "extra_json": extra_json or {},
            "created_at": datetime.now(timezone.utc)
        })


class TypeDBTemplateStore(TemplateStore):
    """
    TypeDB implementation of TemplateStore.
    
    Uses delete+insert for mutable attributes (status, frozen, tainted).
    Logs all changes to template-lifecycle-event.
    """
    
    def __init__(self, driver, database: str = "scientific_knowledge"):
        self.driver = driver
        self.database = database
    
    def _write_query(self, query: str) -> None:
        from typedb.driver import SessionType, TransactionType
        with self.driver.session(self.database, SessionType.DATA) as session:
            with session.transaction(TransactionType.WRITE) as tx:
                tx.query.insert(query)
                tx.commit()
    
    def _read_query(self, query: str) -> List[Dict[str, Any]]:
        from typedb.driver import SessionType, TransactionType
        results = []
        with self.driver.session(self.database, SessionType.DATA) as session:
            with session.transaction(TransactionType.READ) as tx:
                answer = tx.query.get(query)
                for concept_map in answer:
                    row = {}
                    for var in concept_map.variables():
                        concept = concept_map.get(var)
                        # Correct variable mapping fix
                        var_name = var.name() if hasattr(var, "name") else str(var)
                        
                        if hasattr(concept, 'get_value'):
                            row[var_name] = concept.get_value()
                        elif hasattr(concept, 'get_iid'):
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
            f'has frozen {str(metadata.frozen).lower()}',
            f'has tainted {str(metadata.tainted).lower()}',
            f'has created-at {now}'
        ]
        
        if metadata.deps_hash:
            attributes.append(f'has deps-hash "{_escape(metadata.deps_hash)}"')
            
        attr_block = ",\n                ".join(attributes)

        query = f'''
            insert $m isa template-metadata,
                {attr_block};
        '''
        
        self._write_query(query)
        logger.info(f"Inserted metadata for {metadata.qualified_id}")
        
        # Log registration event
        try:
            self.append_event(
                metadata.template_id, 
                str(metadata.version), 
                "registered", 
                metadata.approved_by or "system", # Auto-approved bootstrap
                rationale="Initial registration"
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
            get $spec, $code, $status, $frozen, $tainted;
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
        # Idempotent: check if already frozen
        meta = self.get_metadata(template_id, version)
        if meta and meta.frozen:
            return

        now = _iso_now()
        
        from typedb.driver import SessionType, TransactionType
        
        # Correctly manage attributes: delete 'frozen false', insert 'frozen true'
        # Fix 1: attribute type specified in delete
        delete_query = f'''
            match $m isa template-metadata,
                has template-id "{_escape(template_id)}",
                has version "{_escape(version)}",
                has frozen $old_frozen;
            delete $m has frozen $old_frozen;
        '''
        
        # Fix 2: single insert clause with comma separation
        insert_attrs = [
            f'has frozen true',
            f'has frozen-at {now}',
            f'has first-evidence-id "{_escape(evidence_id)}"'
        ]
        if claim_id:
            insert_attrs.append(f'has freeze-claim-id "{_escape(claim_id)}"')
        if scope_lock_id:
            insert_attrs.append(f'has freeze-scope-lock-id "{_escape(scope_lock_id)}"')
            
        attr_block = ",\n                ".join(insert_attrs)
        
        insert_query = f'''
            match $m isa template-metadata,
                has template-id "{_escape(template_id)}",
                has version "{_escape(version)}";
            insert $m 
                {attr_block};
        '''
            
        # Execute in transaction
        with self.driver.session(self.database, SessionType.DATA) as session:
            with session.transaction(TransactionType.WRITE) as tx:
                tx.query.delete(delete_query)
                tx.query.insert(insert_query)
                tx.commit()
                
        logger.info(f"FROZEN template {template_id}@{version} on evidence {evidence_id}")
        
        # Log event
        self.append_event(
            template_id,
            version,
            "frozen",
            actor,
            rationale=f"Frozen on first evidence {evidence_id}",
            extra_json={
                "evidence_id": evidence_id,
                "claim_id": claim_id,
                "scope_lock_id": scope_lock_id
            }
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
            delete $m has tainted $old;
        '''
        
        insert_attrs = [
            f'has tainted true',
            f'has tainted-at {now}',
            f'has tainted-reason "{_escape(reason)}"'
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
            
        with self.driver.session(self.database, SessionType.DATA) as session:
            with session.transaction(TransactionType.WRITE) as tx:
                tx.query.delete(delete_query)
                tx.query.insert(insert_query)
                tx.commit()
            
        logger.info(f"TAINTED template {template_id}@{version}: {reason}")
        
        # Log event
        self.append_event(
            template_id,
            version,
            "tainted",
            actor,
            rationale=reason,
            extra_json={"superseded_by": superseded_by}
        )
