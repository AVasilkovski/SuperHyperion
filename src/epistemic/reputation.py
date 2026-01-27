"""
Source Reputation Model

v2.1: Tracks source credibility using Beta(α, β) distribution.
Updated when papers retracted, claims refuted, or experiments fail replication.
"""

from dataclasses import dataclass
from typing import Dict
import logging

logger = logging.getLogger(__name__)


@dataclass
class SourceReputation:
    """
    Reputation model for a source (author, publication, or agent).
    
    Uses Beta(α, β) distribution:
        - α: successful contributions (true claims, replicated results)
        - β: failures (retractions, refutations, failed replications)
        
    Expected reputation = α / (α + β)
    """
    entity_id: str
    alpha: float = 1.0  # Prior: 1 success
    beta: float = 1.0   # Prior: 1 failure
    
    @property
    def expected_value(self) -> float:
        """Expected reputation score (0 to 1)."""
        return self.alpha / (self.alpha + self.beta)
    
    @property
    def variance(self) -> float:
        """Variance of the Beta distribution."""
        total = self.alpha + self.beta
        return (self.alpha * self.beta) / (total ** 2 * (total + 1))
    
    @property
    def confidence(self) -> float:
        """Confidence in the reputation (inverse of variance)."""
        return 1.0 / (1.0 + self.variance * 10)
    
    def update(self, positive: bool, weight: float = 1.0) -> None:
        """
        Bayesian update based on new evidence.
        
        Args:
            positive: True if source was correct, False if wrong
            weight: Strength of the evidence (default 1.0)
        """
        if positive:
            self.alpha += weight
        else:
            self.beta += weight
    
    def prior_weight(self) -> float:
        """
        Get prior weight for Bayesian updates.
        
        Used when combining with evidence:
            posterior = prior_weight * prior + evidence_weight * evidence
        """
        return self.expected_value * self.confidence


class SourceReputationModel:
    """
    Manages reputation for all sources in the system.
    
    Updated when:
        - Papers are retracted
        - Claims are refuted
        - Experiments fail replication
    
    Feeds Bayesian priors, not direct answers.
    """
    
    def __init__(self):
        self._reputations: Dict[str, SourceReputation] = {}
    
    def get_reputation(self, entity_id: str) -> SourceReputation:
        """Get or create reputation for an entity."""
        if entity_id not in self._reputations:
            self._reputations[entity_id] = SourceReputation(entity_id=entity_id)
        return self._reputations[entity_id]
    
    def update_reputation(
        self,
        entity_id: str,
        positive: bool,
        weight: float = 1.0,
        reason: str = ""
    ) -> SourceReputation:
        """
        Update reputation based on new evidence.
        
        Args:
            entity_id: ID of the source entity
            positive: True if source was correct, False if wrong
            weight: Strength of the evidence
            reason: Explanation for the update (for audit)
            
        Returns:
            Updated SourceReputation
        """
        reputation = self.get_reputation(entity_id)
        old_value = reputation.expected_value
        reputation.update(positive, weight)
        
        logger.info(
            f"Reputation update: {entity_id} "
            f"{old_value:.3f} -> {reputation.expected_value:.3f} "
            f"({'positive' if positive else 'negative'}, weight={weight}) "
            f"reason: {reason}"
        )
        
        return reputation
    
    def on_retraction(self, source_id: str, publication_doi: str) -> None:
        """Handle paper retraction - significant reputation hit."""
        self.update_reputation(
            entity_id=source_id,
            positive=False,
            weight=3.0,  # Retractions are serious
            reason=f"Retraction of {publication_doi}"
        )
    
    def on_refutation(self, source_id: str, claim_id: str) -> None:
        """Handle claim refutation - moderate reputation hit."""
        self.update_reputation(
            entity_id=source_id,
            positive=False,
            weight=1.5,
            reason=f"Refutation of claim {claim_id}"
        )
    
    def on_replication_success(self, source_id: str, claim_id: str) -> None:
        """Handle successful replication - reputation boost."""
        self.update_reputation(
            entity_id=source_id,
            positive=True,
            weight=2.0,
            reason=f"Successful replication of {claim_id}"
        )
    
    def on_replication_failure(self, source_id: str, claim_id: str) -> None:
        """Handle failed replication - reputation hit."""
        self.update_reputation(
            entity_id=source_id,
            positive=False,
            weight=2.0,
            reason=f"Failed replication of {claim_id}"
        )
    
    def get_prior_weight(self, entity_id: str) -> float:
        """
        Get prior weight for a source to use in Bayesian updates.
        
        Returns 0.5 if source unknown (neutral prior).
        """
        if entity_id not in self._reputations:
            return 0.5  # Neutral prior for unknown sources
        return self._reputations[entity_id].prior_weight()
    
    def get_all_reputations(self) -> Dict[str, Dict]:
        """Get all reputations as a dictionary."""
        return {
            entity_id: {
                "alpha": rep.alpha,
                "beta": rep.beta,
                "expected_value": rep.expected_value,
                "confidence": rep.confidence,
            }
            for entity_id, rep in self._reputations.items()
        }


# Global instance
source_reputation_model = SourceReputationModel()
