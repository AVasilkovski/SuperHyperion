from src.verification.replay_verify import _verify_mutation_linkage, _verify_tenant_scope


class _FakeDB:
    def __init__(self, queries):
        self._mock_mode = False
        self._queries = queries

    def query_fetch(self, query: str):
        self._queries.append(query)
        return []


def test_verify_mutation_linkage_uses_select(monkeypatch):
    queries = []

    def _factory():
        return _FakeDB(queries)

    monkeypatch.setattr("src.db.typedb_client.TypeDBConnection", _factory)

    ok, details = _verify_mutation_linkage("cap-1", ["mut-1"])

    assert ok is False
    assert details["missing"] == ["mut-1"]
    assert any("select $mid;" in q for q in queries)
    assert all("get $mid;" not in q for q in queries)


def test_verify_tenant_scope_uses_select(monkeypatch):
    queries = []

    def _factory():
        return _FakeDB(queries)

    monkeypatch.setattr("src.db.typedb_client.TypeDBConnection", _factory)

    ok, code, _details = _verify_tenant_scope("cap-1", "tenant-1")

    assert ok is False
    assert code == "TENANT_SCOPE_MISSING"
    assert any("select $c;" in q for q in queries)
    assert any("select $any_t;" in q for q in queries)
    assert all("get $c;" not in q and "get $any_t;" not in q for q in queries)
