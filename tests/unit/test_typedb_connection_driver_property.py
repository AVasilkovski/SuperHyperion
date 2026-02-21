from __future__ import annotations

from src.db.typedb_client import TypeDBConnection


def test_typedb_connection_exposes_driver_property_for_legacy_callers():
    conn = TypeDBConnection()

    assert conn.driver is None

    sentinel = object()
    conn._driver = sentinel
    assert conn.driver is sentinel
