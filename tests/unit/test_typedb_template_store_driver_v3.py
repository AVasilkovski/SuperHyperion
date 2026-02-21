from __future__ import annotations

from src.montecarlo.template_store import TypeDBTemplateStore


class _AttrConcept:
    def __init__(self, value):
        self._value = value

    def is_attribute(self):
        return True

    def as_attribute(self):
        return self

    def get_value(self):
        return self._value


class _Row:
    def __init__(self, data):
        self._data = data

    def column_names(self):
        return list(self._data.keys())

    def get(self, col):
        return self._data[col]


class _Answer:
    def __init__(self, rows):
        self._rows = rows

    def as_concept_rows(self):
        return self._rows


class _Resolved:
    def __init__(self, answer):
        self._answer = answer

    def resolve(self):
        return self._answer


class _Tx:
    def __init__(self):
        self.calls = []
        self.query = self._query

    def _query(self, q):
        self.calls.append(q)
        if "get $spec" in q:
            answer = _Answer([_Row({"$spec": _AttrConcept("spec-hash")})])
            return _Resolved(answer)
        return _Resolved(None)

    def commit(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Driver:
    def __init__(self):
        self.tx = _Tx()

    def transaction(self, *_args, **_kwargs):
        return self.tx


def test_typedb_template_store_supports_v3_query_callable_api():
    store = TypeDBTemplateStore(_Driver())

    rows = store._read_query('match $m isa template-metadata, has spec-hash $spec; get $spec;')
    assert rows == [{"spec": "spec-hash"}]

    store._write_query('insert $x isa template-lifecycle-event;')


def test_typedb_template_store_freeze_uses_typeql3_delete_has_of_syntax():
    driver = _Driver()
    store = TypeDBTemplateStore(driver)

    store.freeze(
        template_id="codeact_v1",
        version="1.0.0",
        evidence_id="ev-1",
        claim_id="claim-1",
        scope_lock_id="scope-1",
    )

    freeze_query = driver.tx.calls[-1]
    assert "has frozen $frozen;" in freeze_query
    assert "$frozen == false;" in freeze_query
    assert "delete" in freeze_query
    assert "has $frozen of $m;" in freeze_query
