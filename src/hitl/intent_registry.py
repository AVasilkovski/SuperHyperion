"""
Intent Registry (Phase 16.2)

Single source of truth for write-intent types and their constraints.
All policy, schema validation, scope-lock requirements, and executor
routing MUST derive from this registry.

INVARIANTS:
- If an intent type isn't in INTENT_REGISTRY, it doesn't exist.
- Lane is envelope metadata, NOT a payload field.
- Scope-lock policy is enforced (REQUIRED/FORBIDDEN).
- ID fields are validated per-intent (not just "claim_id").

Design:
- approval_policy: how the intent is routed after staging
- scope_lock_policy: keyed by lane for flexibility
- required_fields: mandatory payload fields
- required_id_fields: mandatory ID fields (claim_id, parent_claim_id, etc.)
- allowed_fields: superset of all valid payload fields (excludes "lane")
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, FrozenSet


class ApprovalPolicy(str, Enum):
    """How an intent is routed after staging."""

    AUTO = "auto"  # Immediately approved (low-risk)
    HITL = "hitl"  # Requires human approval
    DENY = "deny"  # Never allowed (blocked at stage time)


class ScopeLockPolicy(str, Enum):
    """Whether scope_lock_id is required."""

    REQUIRED = "required"  # Must have scope_lock_id
    OPTIONAL = "optional"  # May have scope_lock_id
    FORBIDDEN = "forbidden"  # Must NOT have scope_lock_id


@dataclass(frozen=True)
class IntentSpec:
    """
    Declared contract for an intent type.

    Attributes:
        intent_type: Canonical name (e.g., "create_proposition")
        allowed_fields: All valid payload fields (superset). Does NOT include "lane".
        required_fields: Mandatory payload fields (subset of allowed)
        required_id_fields: ID fields that must be non-empty (e.g., claim_id, parent_claim_id)
        allowed_lanes: Which lanes can stage this intent
        scope_lock_by_lane: Per-lane scope-lock requirement
        approval_by_lane: Per-lane approval routing
        description: Human-readable description
    """

    intent_type: str
    allowed_fields: FrozenSet[str]
    required_fields: FrozenSet[str]
    required_id_fields: FrozenSet[str]  # Replaces requires_claim_id
    allowed_lanes: FrozenSet[str]
    scope_lock_by_lane: Dict[str, ScopeLockPolicy]
    approval_by_lane: Dict[str, ApprovalPolicy]
    description: str = ""

    def get_approval_policy(self, lane: str) -> ApprovalPolicy:
        """Get approval policy for a given lane."""
        return self.approval_by_lane.get(lane, ApprovalPolicy.DENY)

    def get_scope_lock_policy(self, lane: str) -> ScopeLockPolicy:
        """Get scope-lock policy for a given lane."""
        return self.scope_lock_by_lane.get(lane, ScopeLockPolicy.FORBIDDEN)

    def is_lane_allowed(self, lane: str) -> bool:
        """Check if intent is allowed in the given lane."""
        return lane in self.allowed_lanes


# =============================================================================
# THE REGISTRY
# =============================================================================

INTENT_REGISTRY: Dict[str, IntentSpec] = {
    # -------------------------------------------------------------------------
    # Low-Risk Primitives (AUTO in both lanes)
    # -------------------------------------------------------------------------
    "metrics_update": IntentSpec(
        intent_type="metrics_update",
        allowed_fields=frozenset({"metrics", "session_id", "timestamp"}),
        required_fields=frozenset({"metrics"}),
        required_id_fields=frozenset(),
        allowed_lanes=frozenset({"grounded", "speculative"}),
        scope_lock_by_lane={
            "grounded": ScopeLockPolicy.OPTIONAL,
            "speculative": ScopeLockPolicy.OPTIONAL,
        },
        approval_by_lane={"grounded": ApprovalPolicy.AUTO, "speculative": ApprovalPolicy.AUTO},
        description="Append telemetry/metrics (non-mutating)",
    ),
    "cache_write": IntentSpec(
        intent_type="cache_write",
        allowed_fields=frozenset({"key", "value", "ttl_seconds"}),
        required_fields=frozenset({"key", "value"}),
        required_id_fields=frozenset(),
        allowed_lanes=frozenset({"grounded", "speculative"}),
        scope_lock_by_lane={
            "grounded": ScopeLockPolicy.OPTIONAL,
            "speculative": ScopeLockPolicy.OPTIONAL,
        },
        approval_by_lane={"grounded": ApprovalPolicy.AUTO, "speculative": ApprovalPolicy.AUTO},
        description="Write to ephemeral cache (non-durable)",
    ),
    "trace_append": IntentSpec(
        intent_type="trace_append",
        allowed_fields=frozenset({"trace_id", "event", "metadata"}),
        required_fields=frozenset({"trace_id", "event"}),
        required_id_fields=frozenset(),
        allowed_lanes=frozenset({"grounded", "speculative"}),
        scope_lock_by_lane={
            "grounded": ScopeLockPolicy.OPTIONAL,
            "speculative": ScopeLockPolicy.OPTIONAL,
        },
        approval_by_lane={"grounded": ApprovalPolicy.AUTO, "speculative": ApprovalPolicy.AUTO},
        description="Append to execution trace (audit-only)",
    ),
    # -------------------------------------------------------------------------
    # Claim/Proposition Creation
    # - create_claim: DENY in grounded (use create_proposition), AUTO in speculative
    # - create_proposition: grounded only, HITL
    # -------------------------------------------------------------------------
    "create_claim": IntentSpec(
        intent_type="create_claim",
        allowed_fields=frozenset({"claim_id", "content", "hypothesis_id"}),
        required_fields=frozenset({"claim_id", "content"}),
        required_id_fields=frozenset({"claim_id"}),
        allowed_lanes=frozenset({"speculative"}),  # DENY grounded (use create_proposition)
        scope_lock_by_lane={"speculative": ScopeLockPolicy.OPTIONAL},
        approval_by_lane={"speculative": ApprovalPolicy.AUTO},
        description="Create a speculative claim (grounded uses create_proposition)",
    ),
    "create_proposition": IntentSpec(
        intent_type="create_proposition",
        allowed_fields=frozenset({"claim_id", "content", "belief_state", "epistemic_status"}),
        required_fields=frozenset({"claim_id", "content"}),
        required_id_fields=frozenset({"claim_id"}),
        allowed_lanes=frozenset({"grounded"}),
        scope_lock_by_lane={"grounded": ScopeLockPolicy.REQUIRED},
        approval_by_lane={"grounded": ApprovalPolicy.HITL},
        description="Create a grounded proposition (ontology mutation)",
    ),
    # -------------------------------------------------------------------------
    # Epistemic Status Updates (HITL for grounded)
    # -------------------------------------------------------------------------
    "update_epistemic_status": IntentSpec(
        intent_type="update_epistemic_status",
        allowed_fields=frozenset({"claim_id", "new_status", "rationale", "evidence_ids"}),
        required_fields=frozenset({"claim_id", "new_status"}),
        required_id_fields=frozenset({"claim_id"}),
        allowed_lanes=frozenset({"grounded"}),
        scope_lock_by_lane={"grounded": ScopeLockPolicy.REQUIRED},
        approval_by_lane={"grounded": ApprovalPolicy.HITL},
        description="Update epistemic status of a proposition",
    ),
    "refute_claim": IntentSpec(
        intent_type="refute_claim",
        allowed_fields=frozenset({"claim_id", "refutation_evidence", "rationale"}),
        required_fields=frozenset({"claim_id", "refutation_evidence"}),
        required_id_fields=frozenset({"claim_id"}),
        allowed_lanes=frozenset({"grounded"}),
        scope_lock_by_lane={"grounded": ScopeLockPolicy.REQUIRED},
        approval_by_lane={"grounded": ApprovalPolicy.HITL},
        description="Refute a proposition based on negative evidence",
    ),
    # -------------------------------------------------------------------------
    # Phase 16.2: Theory Change Operator Intents
    # -------------------------------------------------------------------------
    "revise_proposition": IntentSpec(
        intent_type="revise_proposition",
        allowed_fields=frozenset(
            {"claim_id", "new_belief_state", "evidence_summary", "conflict_score"}
        ),
        required_fields=frozenset({"claim_id", "new_belief_state", "evidence_summary"}),
        required_id_fields=frozenset({"claim_id"}),
        allowed_lanes=frozenset({"grounded"}),
        scope_lock_by_lane={"grounded": ScopeLockPolicy.REQUIRED},
        approval_by_lane={"grounded": ApprovalPolicy.HITL},
        description="Revise belief state based on aggregated evidence (16.2)",
    ),
    "fork_proposition": IntentSpec(
        intent_type="fork_proposition",
        allowed_fields=frozenset({"parent_claim_id", "new_claim_id", "content", "fork_rationale"}),
        required_fields=frozenset({"parent_claim_id", "new_claim_id", "content", "fork_rationale"}),
        required_id_fields=frozenset({"parent_claim_id", "new_claim_id"}),  # Both IDs required
        allowed_lanes=frozenset({"grounded"}),
        scope_lock_by_lane={"grounded": ScopeLockPolicy.REQUIRED},
        approval_by_lane={"grounded": ApprovalPolicy.HITL},
        description="Fork a proposition into competing hypotheses (16.2)",
    ),
    "quarantine_proposition": IntentSpec(
        intent_type="quarantine_proposition",
        allowed_fields=frozenset({"claim_id", "quarantine_reason", "undercut_evidence"}),
        required_fields=frozenset({"claim_id", "quarantine_reason"}),
        required_id_fields=frozenset({"claim_id"}),
        allowed_lanes=frozenset({"grounded"}),
        scope_lock_by_lane={"grounded": ScopeLockPolicy.REQUIRED},
        approval_by_lane={"grounded": ApprovalPolicy.HITL},
        description="Quarantine a proposition due to methodological undercut (16.2)",
    ),
    # -------------------------------------------------------------------------
    # Proposal Staging (AUTO - just records intent, no mutation)
    # -------------------------------------------------------------------------
    "stage_epistemic_proposal": IntentSpec(
        intent_type="stage_epistemic_proposal",
        allowed_fields=frozenset(
            {"action", "claim_id", "evidence_ids", "conflict_score", "rationale"}
        ),
        required_fields=frozenset({"action", "claim_id"}),
        required_id_fields=frozenset({"claim_id"}),
        allowed_lanes=frozenset({"grounded", "speculative"}),
        scope_lock_by_lane={
            "grounded": ScopeLockPolicy.OPTIONAL,
            "speculative": ScopeLockPolicy.OPTIONAL,
        },
        approval_by_lane={"grounded": ApprovalPolicy.AUTO, "speculative": ApprovalPolicy.AUTO},
        description="Stage a theory change proposal for later review (16.2)",
    ),
}


# =============================================================================
# Registry Access Functions
# =============================================================================


def get_intent_spec(intent_type: str) -> IntentSpec:
    """
    Get the spec for an intent type.

    Raises:
        ValueError: If intent type is not in registry
    """
    spec = INTENT_REGISTRY.get(intent_type)
    if spec is None:
        raise ValueError(f"Unknown intent type: {intent_type}. Not in INTENT_REGISTRY.")
    return spec


def is_intent_type_known(intent_type: str) -> bool:
    """Check if intent type exists in registry."""
    return intent_type in INTENT_REGISTRY


def list_intent_types() -> list:
    """List all known intent types."""
    return list(INTENT_REGISTRY.keys())


def validate_intent_payload(
    intent_type: str,
    payload: Dict[str, Any],
    lane: str,
) -> None:
    """
    Validate an intent payload against its spec.

    INVARIANT: lane is envelope metadata, NOT a payload field.

    Raises:
        ValueError: If validation fails
    """
    spec = get_intent_spec(intent_type)

    # 1. Check lane is NOT in payload (lane is envelope metadata)
    if "lane" in payload:
        raise ValueError(
            f"Payload must not contain 'lane'; lane is an envelope field. "
            f"Remove 'lane' from payload for {intent_type}."
        )

    # 2. Check lane allowed for this intent type
    if not spec.is_lane_allowed(lane):
        raise ValueError(f"Intent type '{intent_type}' not allowed in lane '{lane}'")

    # 3. Check required fields present
    missing = spec.required_fields - set(payload.keys())
    if missing:
        raise ValueError(f"Missing required fields for {intent_type}: {missing}")

    # 4. Check for unknown fields
    unknown = set(payload.keys()) - spec.allowed_fields
    if unknown:
        raise ValueError(f"Unknown fields for {intent_type}: {unknown}")

    # 5. Check ID fields are non-empty
    missing_ids = {f for f in spec.required_id_fields if not payload.get(f)}
    if missing_ids:
        raise ValueError(f"Missing or empty ID fields for {intent_type}: {missing_ids}")


def get_approval_decision(intent_type: str, lane: str) -> ApprovalPolicy:
    """Get the approval policy for an intent in a given lane."""
    spec = get_intent_spec(intent_type)
    return spec.get_approval_policy(lane)


def requires_scope_lock(intent_type: str, lane: str) -> bool:
    """Check if scope_lock_id is required for this intent in this lane."""
    spec = get_intent_spec(intent_type)
    policy = spec.get_scope_lock_policy(lane)
    return policy == ScopeLockPolicy.REQUIRED
