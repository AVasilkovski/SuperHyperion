import pytest
from pathlib import Path

def test_no_legacy_get_select_in_scripts():
    """
    Anton V Requirement: Ensure no 'get $' or 'select $' legacy TypeQL syntax
    exists in the migration or health scripts. 
    TypeDB 3.x uses match-only queries for ConceptRows.
    """
    scripts = [
        Path("scripts/migrate.py"),
        Path("scripts/schema_health.py"),
        Path("scripts/apply_schema.py"),
        Path("scripts/ops12_ci_trust_gates.py")
    ]
    
    forbidden = [" get $", " select $"]
    
    for script_path in scripts:
        if not script_path.exists():
            continue
            
        content = script_path.read_text(encoding="utf-8").lower()
        for pattern in forbidden:
            assert pattern not in content, f"Legacy TypeQL pattern '{pattern}' found in {script_path}"

def test_no_legacy_get_select_in_isolation_tests():
    """
    Ensure the integration tests also strictly follow match-only patterns.
    """
    test_path = Path("tests/integration/test_tenant_isolation.py")
    if not test_path.exists():
        pytest.skip("test_tenant_isolation.py not found")
        
    content = test_path.read_text(encoding="utf-8").lower()
    forbidden = ["get $", "select $"]
    
    for pattern in forbidden:
        assert pattern not in content, f"Legacy TypeQL pattern '{pattern}' found in {test_path}"
