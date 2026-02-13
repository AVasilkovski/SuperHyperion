"""
Meta-Oversight Agent

Daily meta-oversight: boring, automatic, unavoidable.

Produces date-keyed meta-oversight-report entities.
Computes deterministic metrics only - no LLM summarization.

Read-only access to TypeDB.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class GuardPressure:
    """Guard pressure metrics (computed, not summarized)."""
    speculative_rejections: int = 0
    speculative_rejection_sources: List[str] = field(default_factory=list)
    missing_claim_id_failures: int = 0
    missing_claim_id_sources: List[str] = field(default_factory=list)
    residue_validator_trips: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "speculative_rejections": self.speculative_rejections,
            "speculative_rejection_sources": self.speculative_rejection_sources,
            "missing_claim_id_failures": self.missing_claim_id_failures,
            "missing_claim_id_sources": self.missing_claim_id_sources,
            "residue_validator_trips": self.residue_validator_trips,
        }


@dataclass
class DriftIndicators:
    """Drift indicator metrics."""
    top_conflict_claims: List[Dict[str, Any]] = field(default_factory=list)
    speculate_retrieval_trend: float = 0.0  # % of decisions = "speculate"
    epistemic_caps_triggered: int = 0
    cap_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "top_conflict_claims": self.top_conflict_claims,
            "speculate_retrieval_trend": self.speculate_retrieval_trend,
            "epistemic_caps_triggered": self.epistemic_caps_triggered,
            "cap_reasons": self.cap_reasons,
        }


@dataclass
class FragilityMetrics:
    """Fragility and sensitivity metrics."""
    flip_count: int = 0
    flipped_claims: List[Dict[str, Any]] = field(default_factory=list)
    high_sensitivity_axes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "flip_count": self.flip_count,
            "flipped_claims": self.flipped_claims,
            "high_sensitivity_axes": self.high_sensitivity_axes,
        }


@dataclass
class AuthorityQueue:
    """Authority queue metrics."""
    pending_write_intents: int = 0
    pending_intent_ids: List[str] = field(default_factory=list)
    expired_scope_locks: int = 0
    expired_lock_ids: List[str] = field(default_factory=list)
    auto_capped_proposals: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pending_write_intents": self.pending_write_intents,
            "pending_intent_ids": self.pending_intent_ids,
            "expired_scope_locks": self.expired_scope_locks,
            "expired_lock_ids": self.expired_lock_ids,
            "auto_capped_proposals": self.auto_capped_proposals,
        }


@dataclass
class Alert:
    """Single alert (threshold breach)."""
    alert_id: str
    severity: str  # "warning", "critical"
    category: str  # "guard", "fragility", "drift", "authority"
    message: str
    reference_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "reference_id": self.reference_id,
        }


@dataclass
class MetaOversightReport:
    """
    Daily meta-oversight report.
    
    Passive artifact + alert overlay.
    Persisted for audit, rendered for humans.
    """
    report_id: str
    report_date: date
    guard_pressure: GuardPressure
    drift_indicators: DriftIndicators
    fragility: FragilityMetrics
    authority_queue: AuthorityQueue
    alerts: List[Alert] = field(default_factory=list)
    severity: str = "low"  # "low", "medium", "high", "critical"
    created_at: datetime = field(default_factory=datetime.now)

    def compute_severity(self) -> str:
        """Compute overall report severity."""
        if self.guard_pressure.speculative_rejections > 10:
            return "critical"
        if self.fragility.flip_count > 5:
            return "high"
        if self.authority_queue.pending_write_intents > 20:
            return "high"
        if self.drift_indicators.epistemic_caps_triggered > 10:
            return "medium"
        return "low"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "report_date": self.report_date.isoformat(),
            "severity": self.severity,
            "guard_pressure": self.guard_pressure.to_dict(),
            "drift_indicators": self.drift_indicators.to_dict(),
            "fragility": self.fragility.to_dict(),
            "authority_queue": self.authority_queue.to_dict(),
            "alerts": [a.to_dict() for a in self.alerts],
            "created_at": self.created_at.isoformat(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def render_markdown(self) -> str:
        """Render report as human-readable Markdown."""
        lines = [
            f"# Meta-Oversight Report: {self.report_date.isoformat()}",
            f"**Severity:** {self.severity.upper()}",
            "",
        ]

        # Alerts section (top priority)
        if self.alerts:
            lines.append("## 🚨 Alerts")
            for alert in self.alerts:
                icon = "🔴" if alert.severity == "critical" else "🟡"
                lines.append(f"- {icon} **{alert.category}**: {alert.message}")
            lines.append("")

        # Guard Pressure
        lines.append("## Guard Pressure")
        gp = self.guard_pressure
        lines.append(f"- Speculative rejections: **{gp.speculative_rejections}**")
        lines.append(f"- Missing claim_id failures: **{gp.missing_claim_id_failures}**")
        lines.append(f"- Residue validator trips: **{gp.residue_validator_trips}**")
        lines.append("")

        # Fragility
        lines.append("## Fragility & Sensitivity")
        fr = self.fragility
        lines.append(f"- Flips under perturbation: **{fr.flip_count}**")
        if fr.high_sensitivity_axes:
            lines.append(f"- High sensitivity axes: {', '.join(fr.high_sensitivity_axes)}")
        lines.append("")

        # Drift Indicators
        lines.append("## Drift Indicators")
        di = self.drift_indicators
        lines.append(f"- Speculate retrieval trend: **{di.speculate_retrieval_trend:.1%}**")
        lines.append(f"- Epistemic caps triggered: **{di.epistemic_caps_triggered}**")
        lines.append("")

        # Authority Queue
        lines.append("## Authority Queue")
        aq = self.authority_queue
        lines.append(f"- Pending write-intents: **{aq.pending_write_intents}**")
        lines.append(f"- Expired scope locks: **{aq.expired_scope_locks}**")
        lines.append(f"- Auto-capped proposals: **{aq.auto_capped_proposals}**")

        return "\n".join(lines)


class MetaOversightAgent:
    """
    Daily meta-oversight agent.
    
    READ-ONLY access to TypeDB.
    Computes deterministic metrics only.
    No LLM summarization of computed values.
    """

    def __init__(self, db_client=None):
        """
        Initialize with read-only DB client.
        
        Args:
            db_client: TypeDB client with read-only permissions
        """
        self.db_client = db_client
        self._alert_counter = 0

    def generate_daily_report(
        self,
        report_date: Optional[date] = None,
    ) -> MetaOversightReport:
        """
        Generate daily oversight report.
        
        All metrics are computed, not summarized.
        """
        report_date = report_date or date.today()
        report_id = f"report_{report_date.isoformat()}"

        # Compute each section
        guard_pressure = self._compute_guard_pressure(report_date)
        drift_indicators = self._compute_drift_indicators(report_date)
        fragility = self._compute_fragility(report_date)
        authority_queue = self._compute_authority_queue(report_date)

        # Create report
        report = MetaOversightReport(
            report_id=report_id,
            report_date=report_date,
            guard_pressure=guard_pressure,
            drift_indicators=drift_indicators,
            fragility=fragility,
            authority_queue=authority_queue,
        )

        # Compute alerts and severity
        report.alerts = self._compute_alerts(report)
        report.severity = report.compute_severity()

        logger.info(f"Generated oversight report: {report_id} (severity={report.severity})")

        return report

    def _compute_guard_pressure(self, report_date: date) -> GuardPressure:
        """Compute guard pressure metrics from DB."""
        # TODO: Implement actual TypeDB queries
        # For now, return placeholder
        return GuardPressure()

    def _compute_drift_indicators(self, report_date: date) -> DriftIndicators:
        """Compute drift indicators from DB."""
        # TODO: Implement actual TypeDB queries
        return DriftIndicators()

    def _compute_fragility(self, report_date: date) -> FragilityMetrics:
        """Compute fragility metrics from DB."""
        # TODO: Implement actual TypeDB queries
        return FragilityMetrics()

    def _compute_authority_queue(self, report_date: date) -> AuthorityQueue:
        """Compute authority queue metrics from DB."""
        # TODO: Implement actual TypeDB queries
        return AuthorityQueue()

    def _compute_alerts(self, report: MetaOversightReport) -> List[Alert]:
        """Generate alerts for threshold breaches."""
        alerts = []

        # Guard pressure alerts
        if report.guard_pressure.speculative_rejections > 5:
            self._alert_counter += 1
            alerts.append(Alert(
                alert_id=f"alert_{self._alert_counter:04d}",
                severity="warning" if report.guard_pressure.speculative_rejections <= 10 else "critical",
                category="guard",
                message=f"{report.guard_pressure.speculative_rejections} speculative injection attempts blocked",
            ))

        # Fragility alerts
        if report.fragility.flip_count > 3:
            self._alert_counter += 1
            alerts.append(Alert(
                alert_id=f"alert_{self._alert_counter:04d}",
                severity="warning",
                category="fragility",
                message=f"{report.fragility.flip_count} claims flipped under perturbation",
            ))

        # Authority queue alerts
        if report.authority_queue.pending_write_intents > 10:
            self._alert_counter += 1
            alerts.append(Alert(
                alert_id=f"alert_{self._alert_counter:04d}",
                severity="warning",
                category="authority",
                message=f"{report.authority_queue.pending_write_intents} write-intents awaiting approval",
            ))

        if report.authority_queue.expired_scope_locks > 0:
            self._alert_counter += 1
            alerts.append(Alert(
                alert_id=f"alert_{self._alert_counter:04d}",
                severity="critical",
                category="authority",
                message=f"{report.authority_queue.expired_scope_locks} scope locks expired without action",
            ))

        return alerts


# Global instance (no DB client - must be configured)
meta_oversight_agent = MetaOversightAgent()
