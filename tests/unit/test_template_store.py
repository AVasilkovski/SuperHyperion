
import pytest
from datetime import datetime
from src.montecarlo.template_metadata import TemplateMetadata, TemplateVersion, TemplateStatus
from src.montecarlo.template_store import InMemoryTemplateStore

@pytest.fixture
def store():
    return InMemoryTemplateStore()

@pytest.fixture
def meta():
    return TemplateMetadata(
        template_id="test_tmpl",
        version=TemplateVersion(1,0,0),
        spec_hash="abc",
        code_hash="def",
        status=TemplateStatus.ACTIVE,
        frozen=False,
        tainted=False,
        approved_by="tester"
    )

def test_insert_metadata(store, meta):
    store.insert_metadata(meta)
    
    retrieved = store.get_metadata("test_tmpl", "1.0.0")
    assert retrieved is not None
    assert retrieved.spec_hash == "abc"
    assert retrieved.frozen is False
    
    # Check updated audit
    assert len(store.events) == 1
    assert store.events[0]["event_type"] == "registered"

def test_freeze_template(store, meta):
    store.insert_metadata(meta)
    store.freeze("test_tmpl", "1.0.0", "ev-123", "claim-1", "lock-1")
    
    retrieved = store.get_metadata("test_tmpl", "1.0.0")
    assert retrieved.frozen is True
    assert retrieved.first_evidence_id == "ev-123"
    assert retrieved.freeze_claim_id == "claim-1"
    
    # Check audit events (register + freeze)
    assert len(store.events) == 2
    assert store.events[1]["event_type"] == "frozen"
    assert store.events[1]["extra_json"]["evidence_id"] == "ev-123"

def test_freeze_is_idempotent(store, meta):
    store.insert_metadata(meta)
    store.freeze("test_tmpl", "1.0.0", "ev-123")
    store.freeze("test_tmpl", "1.0.0", "ev-999") # Should ignore
    
    retrieved = store.get_metadata("test_tmpl", "1.0.0")
    assert retrieved.first_evidence_id == "ev-123"
    assert len(store.events) == 2 # No new event

def test_taint_template(store, meta):
    store.insert_metadata(meta)
    store.taint("test_tmpl", "1.0.0", "Found bug", actor="Nina")
    
    retrieved = store.get_metadata("test_tmpl", "1.0.0")
    assert retrieved.tainted is True
    assert retrieved.tainted_reason == "Found bug"
    
    # Audit
    assert store.events[-1]["event_type"] == "tainted"
    assert store.events[-1]["actor"] == "Nina"
