import json

from src.cli import replay_cli


class _FakeDB:
    def __init__(self, responses):
        self._mock_mode = False
        self._responses = list(responses)

    def query_fetch(self, _query):
        if self._responses:
            return self._responses.pop(0)
        return []


def test_fetch_capsule_with_mutation_snapshot(monkeypatch):
    rows_with_mutation = [
        {
            "cid": "cap-1",
            "sid": "sess-1",
            "qh": "qh",
            "slid": "sl-1",
            "iid": "int-1",
            "pid": "prop-1",
            "esnap": json.dumps(["ev-1", "ev-2"]),
            "msnap": json.dumps(["mut-1"]),
            "chash": "hash-1",
        }
    ]

    monkeypatch.setattr(
        "src.db.typedb_client.TypeDBConnection",
        lambda: _FakeDB([rows_with_mutation]),
    )

    capsule = replay_cli._fetch_capsule("cap-1")

    assert capsule is not None
    assert capsule["capsule_id"] == "cap-1"
    assert capsule["mutation_ids"] == ["mut-1"]


def test_fetch_capsule_legacy_without_mutation_snapshot(monkeypatch):
    legacy_rows = [
        {
            "cid": "cap-legacy",
            "sid": "sess-legacy",
            "qh": "qh-old",
            "slid": "sl-old",
            "iid": "int-old",
            "pid": "prop-old",
            "esnap": json.dumps(["ev-legacy"]),
            "chash": "hash-old",
        }
    ]

    # First query (with mutation-snapshot) returns no rows; fallback query returns legacy row.
    monkeypatch.setattr(
        "src.db.typedb_client.TypeDBConnection",
        lambda: _FakeDB([[], legacy_rows]),
    )

    capsule = replay_cli._fetch_capsule("cap-legacy")

    assert capsule is not None
    assert capsule["capsule_id"] == "cap-legacy"
    assert capsule["evidence_ids"] == ["ev-legacy"]
    assert capsule["mutation_ids"] == []
