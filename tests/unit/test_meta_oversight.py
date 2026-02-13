"""
Unit Tests: Meta-Oversight Agent

Tests for daily drift reports and alert generation.
"""

from datetime import date

from src.agents.meta_oversight import (
    Alert,
    AuthorityQueue,
    DriftIndicators,
    FragilityMetrics,
    GuardPressure,
    MetaOversightAgent,
    MetaOversightReport,
)


class TestGuardPressure:
    """Tests for GuardPressure metrics."""

    def test_guard_pressure_default_values(self):
        """GuardPressure initializes with zeros."""
        gp = GuardPressure()

        assert gp.speculative_rejections == 0
        assert gp.missing_claim_id_failures == 0
        assert gp.residue_validator_trips == 0

    def test_guard_pressure_to_dict(self):
        """GuardPressure serializes correctly."""
        gp = GuardPressure(
            speculative_rejections=5,
            speculative_rejection_sources=["agent-a", "agent-b"],
        )

        data = gp.to_dict()

        assert data["speculative_rejections"] == 5
        assert "agent-a" in data["speculative_rejection_sources"]


class TestMetaOversightReport:
    """Tests for MetaOversightReport."""

    def test_report_computes_severity_low(self):
        """Report severity is 'low' when all metrics are normal."""
        report = MetaOversightReport(
            report_id="test-001",
            report_date=date.today(),
            guard_pressure=GuardPressure(),
            drift_indicators=DriftIndicators(),
            fragility=FragilityMetrics(),
            authority_queue=AuthorityQueue(),
        )

        assert report.compute_severity() == "low"

    def test_report_computes_severity_critical_on_high_rejections(self):
        """Report severity is 'critical' when speculative rejections > 10."""
        report = MetaOversightReport(
            report_id="test-002",
            report_date=date.today(),
            guard_pressure=GuardPressure(speculative_rejections=15),
            drift_indicators=DriftIndicators(),
            fragility=FragilityMetrics(),
            authority_queue=AuthorityQueue(),
        )

        assert report.compute_severity() == "critical"

    def test_report_computes_severity_high_on_fragility(self):
        """Report severity is 'high' when flip_count > 5."""
        report = MetaOversightReport(
            report_id="test-003",
            report_date=date.today(),
            guard_pressure=GuardPressure(),
            drift_indicators=DriftIndicators(),
            fragility=FragilityMetrics(flip_count=7),
            authority_queue=AuthorityQueue(),
        )

        assert report.compute_severity() == "high"

    def test_report_renders_markdown(self):
        """Report renders as Markdown correctly."""
        report = MetaOversightReport(
            report_id="test-004",
            report_date=date.today(),
            guard_pressure=GuardPressure(speculative_rejections=3),
            drift_indicators=DriftIndicators(speculate_retrieval_trend=0.25),
            fragility=FragilityMetrics(flip_count=2),
            authority_queue=AuthorityQueue(pending_write_intents=5),
        )

        md = report.render_markdown()

        assert "# Meta-Oversight Report" in md
        assert "Guard Pressure" in md
        assert "Fragility" in md

    def test_report_includes_alerts_in_markdown(self):
        """Alert section appears when alerts exist."""
        report = MetaOversightReport(
            report_id="test-005",
            report_date=date.today(),
            guard_pressure=GuardPressure(),
            drift_indicators=DriftIndicators(),
            fragility=FragilityMetrics(),
            authority_queue=AuthorityQueue(),
            alerts=[
                Alert(
                    alert_id="alert-001",
                    severity="warning",
                    category="guard",
                    message="Test alert",
                ),
            ],
        )

        md = report.render_markdown()

        assert "🚨 Alerts" in md
        assert "Test alert" in md


class TestMetaOversightAgent:
    """Tests for MetaOversightAgent."""

    def test_agent_generates_report_with_date(self):
        """Agent generates report for specific date."""
        agent = MetaOversightAgent()

        report = agent.generate_daily_report(report_date=date(2026, 1, 27))

        assert report.report_date == date(2026, 1, 27)
        assert report.report_id == "report_2026-01-27"

    def test_agent_generates_report_for_today_by_default(self):
        """Agent defaults to today's date."""
        agent = MetaOversightAgent()

        report = agent.generate_daily_report()

        assert report.report_date == date.today()

    def test_agent_computes_alerts_for_threshold_breaches(self):
        """Agent generates alerts when thresholds breached."""
        agent = MetaOversightAgent()

        # Create a report with high guard pressure
        report = MetaOversightReport(
            report_id="test-alerts",
            report_date=date.today(),
            guard_pressure=GuardPressure(speculative_rejections=8),
            drift_indicators=DriftIndicators(),
            fragility=FragilityMetrics(flip_count=4),
            authority_queue=AuthorityQueue(expired_scope_locks=2),
        )

        alerts = agent._compute_alerts(report)

        # Should have alerts for rejections, fragility, and expired locks
        assert len(alerts) >= 2  # At minimum: rejections + expired locks

    def test_agent_alert_for_expired_scope_locks_is_critical(self):
        """Expired scope locks trigger critical alert."""
        agent = MetaOversightAgent()

        report = MetaOversightReport(
            report_id="test-critical",
            report_date=date.today(),
            guard_pressure=GuardPressure(),
            drift_indicators=DriftIndicators(),
            fragility=FragilityMetrics(),
            authority_queue=AuthorityQueue(expired_scope_locks=1),
        )

        alerts = agent._compute_alerts(report)

        critical_alerts = [a for a in alerts if a.severity == "critical"]
        assert len(critical_alerts) >= 1
