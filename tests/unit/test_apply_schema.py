import sys
from pathlib import Path

import pytest

# Add scripts directory to path to import apply_schema
sys.path.append(str(Path(__file__).parent.parent.parent / "scripts"))
import apply_schema


def test_resolve_schema_empty():
    with pytest.raises(ValueError, match="No --schema provided"):
        apply_schema.resolve_schema_files([])
    
    with pytest.raises(ValueError, match="Empty --schema argument is invalid"):
        apply_schema.resolve_schema_files([""])
    
    with pytest.raises(ValueError, match="Empty --schema argument is invalid"):
        apply_schema.resolve_schema_files(["   "])

def test_resolve_schema_triple_star():
    with pytest.raises(FileNotFoundError, match="Invalid schema glob pattern \\(triple-star\\):"):
        apply_schema.resolve_schema_files(["src/schema/***.tql"])

def test_planner_basic_owns():
    schema = """
    entity evidence @abstract,
        owns template-id;
        
    entity validation-evidence sub evidence, owns template-id;
    """
    
    parent_of, owns_of, plays_of = apply_schema.parse_canonical_caps(schema)
    
    assert parent_of.get("validation-evidence") == "evidence"
    assert "template-id" in owns_of.get("evidence", set())
    
    owns_specs, plays_specs = apply_schema.plan_auto_migrations(parent_of, owns_of, plays_of)
    assert ("validation-evidence", "template-id") in [pair for pair in owns_specs]
    assert len(plays_specs) == 0

def test_planner_multiple_subtypes_owns():
    schema = """
    entity evidence @abstract,
        owns template-id;
        
    entity validation-evidence sub evidence, owns template-id;
    entity negative-evidence sub evidence, owns template-id;
    """
    
    parent_of, owns_of, plays_of = apply_schema.parse_canonical_caps(schema)
    owns_specs, plays_specs = apply_schema.plan_auto_migrations(parent_of, owns_of, plays_of)
    
    assert ("validation-evidence", "template-id") in owns_specs
    assert ("negative-evidence", "template-id") in owns_specs

def test_planner_basic_plays():
    schema = """
    entity evidence @abstract,
        plays session-has-evidence:evidence;
        
    entity validation-evidence sub evidence,
        plays session-has-evidence:evidence;
    """
    
    parent_of, owns_of, plays_of = apply_schema.parse_canonical_caps(schema)
    
    assert "session-has-evidence:evidence" in plays_of.get("evidence", set())
    
    owns_specs, plays_specs = apply_schema.plan_auto_migrations(parent_of, owns_of, plays_of)
    assert ("validation-evidence", "session-has-evidence:evidence") in plays_specs
    assert len(owns_specs) == 0

def test_planner_hardened_edge_cases():
    schema = """
    # Commented out entity
    # entity old-evidence sub entity, owns legacy-id;

    entity evidence sub entity, # valid comment
        owns template-id; # another comment

    entity validation-evidence sub evidence,
        owns template-id,
        owns validation-only-attr; # should not be inherited upwards

    relation session-has-evidence sub relation,
        relates session,
        relates evidence;

    # Deceptive names containing keywords
    entity owns-metadata sub entity,
        owns metadata-id;
    """
    
    parent_of, owns_of, plays_of = apply_schema.parse_canonical_caps(schema)
    
    # Comments should be stripped
    assert "old-evidence" not in parent_of
    
    # Correct inheritance
    assert parent_of.get("validation-evidence") == "evidence"
    assert "template-id" in owns_of.get("evidence")
    
    # Deceptive names should match as entities, not keywords
    assert "owns-metadata" in owns_of or "owns-metadata" in parent_of or "owns-metadata" in plays_of
    assert "metadata-id" in owns_of.get("owns-metadata")
    
    owns_specs, plays_specs = apply_schema.plan_auto_migrations(parent_of, owns_of, plays_of)
    
    # validation-evidence should inherit template-id
    assert ("validation-evidence", "template-id") in owns_specs
    # validation-only-attr should NOT be an undefine target for anyone unless it has subtypes
    # (Checking that the supertype capability is what triggers inheritance)
    
    # owns-metadata should NOT be an undefine target because it's not a subtype of something with attributes we've defined
    assert not any(t == "owns-metadata" for t, a in owns_specs)

