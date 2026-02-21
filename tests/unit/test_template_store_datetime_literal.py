from __future__ import annotations

from src.montecarlo import template_store


def test_iso_now_emits_datetime_without_timezone_suffix():
    literal = template_store._iso_now()

    assert literal.endswith("Z") is False
    assert "+" not in literal
    assert literal.count("T") == 1
