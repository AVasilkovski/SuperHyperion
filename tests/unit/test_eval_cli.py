"""
Tests for Eval CLI (Phase 16.7).
"""

from src.cli.eval_cli import _compute_summary


def test_compute_summary_basic():
    """Verify basic metrics computation for a mixed set of runs."""
    results = [
        {
            "success": True,
            "status": "PASS",
            "hold_code": None,
            "evidence_count": 2,
            "claim_count": 1,
            "has_capsule": True,
            "latency_ms": 1000,
        },
        {
            "success": False,
            "status": "HOLD",
            "hold_code": "NO_EVIDENCE_PERSISTED",
            "evidence_count": 0,
            "claim_count": 0,
            "has_capsule": False,
            "latency_ms": 500,
        },
        {
            "success": False,
            "status": "HOLD",
            "hold_code": "SCOPE_LOCK_MISMATCH",
            "evidence_count": 1,
            "claim_count": 1,
            "has_capsule": False,
            "latency_ms": 800,
        },
        {
            "success": False,
            "status": "ERROR",
            "hold_code": "Crash",
            "evidence_count": 0,
            "claim_count": 0,
            "has_capsule": False,
            "latency_ms": 100,
        },
    ]

    summary = _compute_summary(results)

    assert summary["total_runs"] == 4
    assert summary["pass_rate"] == 0.25
    assert summary["hold_rate"] == 0.50
    assert summary["error_rate"] == 0.25
    assert summary["capsule_rate"] == 0.25
    assert summary["avg_latency_ms"] == 600.0
    assert summary["avg_evidence_count"] == 0.8
    assert summary["avg_claim_count"] == 0.5

    # Check hold codes breakdown
    holds = summary["hold_codes"]
    assert holds.get("NO_EVIDENCE_PERSISTED") == 1
    assert holds.get("SCOPE_LOCK_MISMATCH") == 1
    assert holds.get("Crash") == 1


def test_compute_summary_empty():
    """Verify empty results don't divide by zero."""
    summary = _compute_summary([])
    assert summary["total_runs"] == 0
    assert len(summary.keys()) == 1
