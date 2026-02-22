from unittest.mock import MagicMock

import pytest

from tests.integration.test_tenant_isolation import exec_write


def test_exec_write_materialization_exhaustion():
    """
    PROVES: exec_write calls materialization methods on the answer object
    based on query type to ensure TypeDB 3.8 mutations are executed.
    """
    mock_tx = MagicMock()
    mock_ans = MagicMock()
    
    # CASE 1: MATCH/INSERT (concept rows)
    mock_rows = MagicMock()
    mock_ans.as_concept_rows.return_value = mock_rows
    mock_tx.query.return_value.resolve.return_value = mock_ans
    
    exec_write(mock_tx, "insert $x isa tenant;")
    mock_ans.as_concept_rows.assert_called_once()
    mock_rows.__iter__.assert_called()

    # CASE 2: FETCH (concept documents)
    mock_tx.reset_mock()
    mock_ans.reset_mock()
    mock_docs = MagicMock()
    mock_ans.as_concept_documents.return_value = mock_docs
    mock_tx.query.return_value.resolve.return_value = mock_ans
    
    exec_write(mock_tx, "match $x isa tenant; fetch $x: tenant-id;")
    mock_ans.as_concept_documents.assert_called_once()
    mock_docs.__iter__.assert_called()


def test_exec_write_surfaces_errors():
    """
    PROVES: exec_write surfaces TypeDB errors with query context.
    """
    mock_tx = MagicMock()
    mock_tx.query.side_effect = Exception("Boom")
    
    with pytest.raises(AssertionError) as excinfo:
        exec_write(mock_tx, "insert $x isa tenant;")
    
    assert "TypeDB execution failed" in str(excinfo.value)
    assert "insert $x" in str(excinfo.value)
