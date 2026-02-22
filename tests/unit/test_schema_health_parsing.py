import sys
from unittest.mock import MagicMock

# Mock typedb.driver before importing scripts.schema_health
mock_typedb = MagicMock()
sys.modules["typedb"] = mock_typedb
sys.modules["typedb.driver"] = mock_typedb.driver

from scripts.schema_health import db_current_ordinal  # noqa: E402


def test_db_current_ordinal_parsing():
    mock_driver = MagicMock()
    mock_tx = MagicMock()
    mock_answer = MagicMock()
    mock_row_1 = MagicMock()
    mock_row_2 = MagicMock()
    
    # Mock transaction context manager
    mock_driver.transaction.return_value.__enter__.return_value = mock_tx
    
    # Mock tx.query(q).resolve() returning answer
    mock_query_res = MagicMock()
    mock_tx.query.side_effect = lambda q: mock_query_res if "select" in q else MagicMock()
    mock_query_res.resolve.return_value = mock_answer
    
    # Mock row 1: ordinal 5
    mock_attr_1 = MagicMock()
    mock_attr_1.is_attribute.return_value = True
    mock_attr_1.as_attribute.return_value.get_value.return_value = 5
    mock_row_1.get.return_value = mock_attr_1
    
    # Mock row 2: ordinal 10
    mock_attr_2 = MagicMock()
    mock_attr_2.is_attribute.return_value = True
    mock_attr_2.as_attribute.return_value.get_value.return_value = 10
    mock_row_2.get.return_value = mock_attr_2
    
    mock_answer.as_concept_rows.return_value = [mock_row_1, mock_row_2]
    
    result = db_current_ordinal(mock_driver, "test_db")
    assert result == 10

def test_db_current_ordinal_empty():
    mock_driver = MagicMock()
    mock_tx = MagicMock()
    mock_answer = MagicMock()
    
    mock_driver.transaction.return_value.__enter__.return_value = mock_tx
    
    mock_query_res = MagicMock()
    mock_tx.query.return_value = mock_query_res
    mock_query_res.resolve.return_value = mock_answer
    
    mock_answer.as_concept_rows.return_value = []
    
    result = db_current_ordinal(mock_driver, "test_db")
    assert result == 0
