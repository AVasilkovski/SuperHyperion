from __future__ import annotations

from contextlib import contextmanager

from src.db.capabilities import WriteCap
from src.db.typedb_client import TypeDBConnection


class _Attr:
    def __init__(self, value):
        self._value = value

    def is_attribute(self):
        return True

    def as_attribute(self):
        return self

    def get_value(self):
        return self._value


class _Row:
    def column_names(self):
        return ["$name"]

    def get(self, col):
        assert col == "$name"
        return _Attr("alice")


class _Answer:
    def as_concept_rows(self):
        return [_Row()]


class _Promise:
    def resolve(self):
        return _Answer()


class _TxCallable:
    def __init__(self):
        self.queries: list[str] = []

    def query(self, q: str):
        self.queries.append(q)
        return _Promise()


class _QueryLegacy:
    def __init__(self):
        self.inserts: list[str] = []
        self.deletes: list[str] = []

    def insert(self, q: str):
        self.inserts.append(q)

    def delete(self, q: str):
        self.deletes.append(q)


class _TxLegacy:
    def __init__(self):
        self.query = _QueryLegacy()


def test_query_fetch_supports_callable_query_api(monkeypatch):
    tx = _TxCallable()
    db = TypeDBConnection()
    db._mock_mode = False

    @contextmanager
    def _tx_ctx(*_a, **_k):
        yield tx

    monkeypatch.setattr(db, "transaction", _tx_ctx)

    rows = db.query_fetch("match $x isa thing, has name $name; select $name;")
    assert rows == [{"name": "alice"}]


def test_query_insert_delete_support_legacy_query_object(monkeypatch):
    tx = _TxLegacy()
    db = TypeDBConnection()
    db._mock_mode = False

    @contextmanager
    def _tx_ctx(*_a, **_k):
        yield tx

    monkeypatch.setattr(db, "transaction", _tx_ctx)

    cap = WriteCap._mint()
    db.query_insert('insert $x isa thing;', cap=cap)
    db.query_delete('match $x isa thing; delete $x isa thing;', cap=cap)

    assert tx.query.inserts
    assert tx.query.deletes


class _AnswerTypedRows:
    def is_concept_rows(self):
        return True

    def is_concept_documents(self):
        return False

    def as_concept_documents(self):
        raise AssertionError("should not cast rows answer to documents")

    def as_concept_rows(self):
        return [_Row()]


class _PromiseTypedRows:
    def resolve(self):
        return _AnswerTypedRows()


class _TxCallableTypedRows:
    def query(self, _q: str):
        return _PromiseTypedRows()


def test_query_fetch_prefers_concept_rows_over_documents_when_typed(monkeypatch):
    tx = _TxCallableTypedRows()
    db = TypeDBConnection()
    db._mock_mode = False

    @contextmanager
    def _tx_ctx(*_a, **_k):
        yield tx

    monkeypatch.setattr(db, "transaction", _tx_ctx)

    rows = db.query_fetch("match $x isa thing, has name $name; select $name;")
    assert rows == [{"name": "alice"}]
