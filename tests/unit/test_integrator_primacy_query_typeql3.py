from src.agents.integrator_agent import IntegratorAgent


def test_fetch_evidence_by_ids_uses_select_query_tail(monkeypatch):
    agent = IntegratorAgent()
    captured = {}

    def _fake_query_graph(query: str):
        captured["query"] = query
        return []

    monkeypatch.setattr(agent, "query_graph", _fake_query_graph)

    rows = agent._fetch_evidence_by_ids("sess-1", ["ev-1", "ev-2"])

    assert rows == []
    query = captured["query"]
    assert 'session-id "sess-1"' in query
    assert "select $id, $claim, $scope;" in query
    assert "get $id, $claim, $scope;" not in query
