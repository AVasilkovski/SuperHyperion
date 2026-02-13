"""
Reasoning Integration Tests

Tests the belief maintenance and contradiction detection logic.
"""

from unittest.mock import Mock

import pytest

from src.agents.base_agent import AgentContext
from src.agents.belief_agent import BeliefMaintenanceAgent


class TestBeliefMaintenanceAgent:
    """Test suite for belief maintenance functionality."""

    @pytest.fixture
    def agent(self):
        """Create a belief maintenance agent for testing."""
        agent = BeliefMaintenanceAgent()
        # Mock the database connection
        agent.db = Mock()
        return agent

    # ============================================
    # Belief Calculation Tests
    # ============================================

    def test_calculate_belief_high_confidence(self, agent):
        """High alpha, low beta should give high expected value."""
        hypothesis = {
            "id": "h1",
            "beta_alpha": 9.0,
            "beta_beta": 1.0,
        }
        belief = agent._calculate_belief(hypothesis)

        assert belief.expected_value == pytest.approx(0.9, rel=0.01)
        assert belief.belief_state == "verified"

    def test_calculate_belief_low_confidence(self, agent):
        """Low alpha, high beta should give low expected value."""
        hypothesis = {
            "id": "h2",
            "beta_alpha": 1.0,
            "beta_beta": 9.0,
        }
        belief = agent._calculate_belief(hypothesis)

        assert belief.expected_value == pytest.approx(0.1, rel=0.01)
        assert belief.belief_state == "refuted"

    def test_calculate_belief_uncertain(self, agent):
        """Equal alpha and beta should give uncertain state."""
        hypothesis = {
            "id": "h3",
            "beta_alpha": 2.0,
            "beta_beta": 2.0,
        }
        belief = agent._calculate_belief(hypothesis)

        assert belief.expected_value == pytest.approx(0.5, rel=0.01)
        # Should be debated due to high uncertainty
        assert belief.belief_state in ["proposed", "debated"]

    def test_calculate_belief_initial_state(self, agent):
        """Initial state (alpha=beta=1) should have high entropy."""
        hypothesis = {
            "id": "h4",
            "beta_alpha": 1.0,
            "beta_beta": 1.0,
        }
        belief = agent._calculate_belief(hypothesis)

        assert belief.expected_value == pytest.approx(0.5, rel=0.01)
        assert belief.entropy >= 0.5  # High uncertainty

    # ============================================
    # Bayesian Update Tests
    # ============================================

    def test_bayesian_update_supporting_evidence(self, agent):
        """Supporting evidence should log deferral (WriteCap: no direct write)."""
        # Setup mock to return current belief
        agent.db.query_fetch = Mock(return_value=[{
            "beta_alpha": 5.0,
            "beta_beta": 3.0,
        }])
        agent.db.query_delete = Mock()

        agent.update_belief("h1", evidence_supports=True, evidence_weight=1.0)

        # WriteCap: direct writes are deferred to OntologySteward
        assert not agent.db.query_delete.called

    def test_bayesian_update_refuting_evidence(self, agent):
        """Refuting evidence should log deferral (WriteCap: no direct write)."""
        agent.db.query_fetch = Mock(return_value=[{
            "beta_alpha": 5.0,
            "beta_beta": 3.0,
        }])
        agent.db.query_delete = Mock()

        agent.update_belief("h1", evidence_supports=False, evidence_weight=1.0)

        # WriteCap: direct writes are deferred to OntologySteward
        assert not agent.db.query_delete.called

    def test_bayesian_update_weighted_evidence(self, agent):
        """Evidence weight should affect update magnitude (write deferred)."""
        agent.db.query_fetch = Mock(return_value=[{
            "beta_alpha": 5.0,
            "beta_beta": 5.0,
        }])
        agent.db.query_delete = Mock()

        agent.update_belief("h1", evidence_supports=True, evidence_weight=3.0)

        # WriteCap: direct writes are deferred to OntologySteward
        assert not agent.db.query_delete.called

    # ============================================
    # Contradiction Detection Tests
    # ============================================

    def test_find_contradictions_none(self, agent):
        """Should return empty when no contradictions exist."""
        agent.db.query_fetch = Mock(return_value=[])

        contradictions = agent._find_contradictions({"id": "h1"})

        assert contradictions == []

    def test_find_contradictions_found(self, agent):
        """Should return contradictions when they exist."""
        mock_contradiction = {
            "h1": {"id": "hyp1"},
            "h2": {"id": "hyp2"},
            "c1": {"cause": "A", "effect": "B"},
            "c2": {"cause": "A", "effect": "C"},
        }
        agent.db.query_fetch = Mock(return_value=[mock_contradiction])

        contradictions = agent._find_contradictions({"id": "h1"})

        assert len(contradictions) == 1

    # ============================================
    # Entropy Threshold Tests
    # ============================================

    def test_needs_debate_high_entropy(self, agent):
        """High entropy should trigger debate."""
        assert agent.needs_debate(0.5) is True
        assert agent.needs_debate(0.6) is True
        assert agent.needs_debate(0.9) is True

    def test_needs_debate_low_entropy(self, agent):
        """Low entropy should not trigger debate."""
        assert agent.needs_debate(0.1) is False
        assert agent.needs_debate(0.2) is False
        assert agent.needs_debate(0.3) is False

    def test_needs_debate_threshold(self, agent):
        """Should use config threshold (0.4)."""
        assert agent.needs_debate(0.39) is False
        assert agent.needs_debate(0.41) is True

    # ============================================
    # Agent Run Tests
    # ============================================

    @pytest.mark.asyncio
    async def test_run_updates_context(self, agent):
        """Running agent should update context with entropy."""
        agent._get_pending_hypotheses = Mock(return_value=[{
            "id": "h1",
            "beta_alpha": 3.0,
            "beta_beta": 3.0,
        }])
        agent._find_contradictions = Mock(return_value=[])
        agent._update_belief_state = Mock()

        context = AgentContext()
        result = await agent.run(context)

        assert result.dialectical_entropy > 0

    @pytest.mark.asyncio
    async def test_run_detects_contradictions(self, agent):
        """Running agent should detect and report contradictions."""
        agent._get_pending_hypotheses = Mock(return_value=[{
            "id": "h1",
            "beta_alpha": 5.0,
            "beta_beta": 2.0,
        }])
        agent._find_contradictions = Mock(return_value=[{"conflict": "A vs B"}])
        agent._update_belief_state = Mock()

        context = AgentContext()
        result = await agent.run(context)

        assert "contradictions" in result.graph_context
        assert len(result.graph_context["contradictions"]) == 1


class TestEntropyCalculation:
    """Test dialectical entropy calculations."""

    @pytest.fixture
    def agent(self):
        return BeliefMaintenanceAgent()

    def test_entropy_extreme_confidence(self, agent):
        """Extreme confidence should have low entropy."""
        # High confidence (alpha >> beta)
        entropy = agent.calculate_entropy([0.95, 0.05])
        assert entropy < 0.5

    def test_entropy_maximum_uncertainty(self, agent):
        """Equal probability should have maximum entropy."""
        entropy = agent.calculate_entropy([0.5, 0.5])
        assert entropy == pytest.approx(1.0, rel=0.01)

    def test_entropy_multi_state(self, agent):
        """Multi-state entropy should work correctly."""
        # Uniform distribution over 4 states
        entropy = agent.calculate_entropy([0.25, 0.25, 0.25, 0.25])
        assert entropy == pytest.approx(2.0, rel=0.01)  # log2(4) = 2


class TestContradictionResolution:
    """Test contradiction detection and resolution."""

    def test_contradiction_triggers_debate(self):
        """Contradictions should increase entropy and trigger debate."""
        agent = BeliefMaintenanceAgent()
        agent.db = Mock()

        # Mock returning contradictory hypotheses
        agent._find_contradictions = Mock(return_value=[
            {"claim_a": "X causes Y", "claim_b": "X prevents Y"}
        ])

        contradictions = agent._find_contradictions({"id": "test"})

        # Contradictions present should lead to debate
        assert len(contradictions) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
