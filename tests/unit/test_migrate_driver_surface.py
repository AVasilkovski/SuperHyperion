import pytest
from pathlib import Path

def test_migrate_driver_surface_invariants():
    """
    Ensure scripts/migrate.py adheres to the callable tx.query(...) promise-based pattern
    required by TypeDB driver 3.x and does not use legacy define/get/insert methods.
    """
    migrate_path = Path("scripts/migrate.py")
    if not migrate_path.exists():
        pytest.skip("scripts/migrate.py not found")
        
    content = migrate_path.read_text(encoding="utf-8")
    
    forbidden = [".query.define", ".query.get", ".query.insert"]
    for word in forbidden:
        assert word not in content, f"Forbidden legacy driver surface found: {word}. Use tx.query(q).resolve() instead."

    assert 'tx.query(' in content, "Expected callable tx.query(...) pattern not found in migrate.py"

def test_schema_health_driver_surface_invariants():
    """
    Ensure scripts/schema_health.py adheres to the callable tx.query(...) pattern.
    """
    sh_path = Path("scripts/schema_health.py")
    if not sh_path.exists():
        pytest.skip("scripts/schema_health.py not found")
        
    content = sh_path.read_text(encoding="utf-8")
    
    forbidden = [".query.define", ".query.get", ".query.insert"]
    for word in forbidden:
        assert word not in content, f"Forbidden legacy driver surface found in schema_health.py: {word}."

    assert 'tx.query(' in content, "Expected callable tx.query(...) pattern not found in schema_health.py"
