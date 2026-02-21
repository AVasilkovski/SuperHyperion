from __future__ import annotations

import types


def test_load_typedb_succeeds_without_typedbdriver_symbol(monkeypatch):
    from src.db import typedb_client as tc

    fake_driver_module = types.ModuleType("typedb.driver")

    class _FakeTypeDB:
        pass

    class _FakeTransactionType:
        READ = object()
        WRITE = object()

    class _FakeCredentials:
        pass

    class _FakeDriverOptions:
        pass

    fake_driver_module.TypeDB = _FakeTypeDB
    fake_driver_module.TransactionType = _FakeTransactionType
    fake_driver_module.Credentials = _FakeCredentials
    fake_driver_module.DriverOptions = _FakeDriverOptions
    # Intentionally omit TypeDBDriver to simulate compatibility case.

    monkeypatch.setattr(tc, "TYPEDB_AVAILABLE", False)
    monkeypatch.setattr(tc, "TypeDB", None)
    monkeypatch.setattr(tc, "TypeDBDriver", None)
    monkeypatch.setattr(tc, "TransactionType", None)
    monkeypatch.setattr(tc, "Credentials", None)
    monkeypatch.setattr(tc, "DriverOptions", None)

    sys_mod = __import__("sys")
    fake_typedb_pkg = types.ModuleType("typedb")
    fake_typedb_pkg.driver = fake_driver_module
    monkeypatch.setitem(sys_mod.modules, "typedb", fake_typedb_pkg)
    monkeypatch.setitem(sys_mod.modules, "typedb.driver", fake_driver_module)

    assert tc._load_typedb() is True
    assert tc.TypeDB is _FakeTypeDB
    assert tc.TransactionType is _FakeTransactionType
    assert tc.TypeDBDriver is None
