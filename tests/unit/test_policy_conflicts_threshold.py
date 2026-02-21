from __future__ import annotations

from src.sdk.policy_conflicts import should_fail_on_severity, summarize_conflict_severity


def test_conflict_severity_counts_and_fail_thresholds():
    summary = {
        "static_conflicts": [{"severity": "error"}],
        "dynamic_conflicts": [{"severity": "warning"}, {"severity": "warning"}],
    }
    counts = summarize_conflict_severity(summary)
    assert counts == {"error": 1, "warning": 2, "total": 3}

    assert should_fail_on_severity(summary, "none") is False
    assert should_fail_on_severity(summary, "error") is True
    assert should_fail_on_severity(summary, "warning") is True
