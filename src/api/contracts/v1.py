"""
TRUST-1.2 - v1 API Contracts
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.sdk.types import GovernedResultV1, ReplayVerdictV1


class RoleEnum(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class RunRequestV1(BaseModel):
    """Request payload for triggering a governed run."""
    model_config = ConfigDict(extra="forbid")

    query: str
    session_id: Optional[str] = None
    thread_id: Optional[str] = None
    mode: str = "grounded"
    options: Dict[str, Any] = Field(default_factory=dict)


class RunResponseV1(BaseModel):
    """Response payload enclosing the result of a governed run."""
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    result: GovernedResultV1


class CapsuleListItemV1(BaseModel):
    """A minimal reference to a capsule for listing."""
    model_config = ConfigDict(extra="forbid")

    capsule_id: str
    session_id: Optional[str] = None
    query_hash: Optional[str] = None
    scope_lock_id: Optional[str] = None
    intent_id: Optional[str] = None
    proposal_id: Optional[str] = None
    created_at: str


class CapsuleListV1(BaseModel):
    """Paginated collection of capsules."""
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    tenant_id: str
    items: List[CapsuleListItemV1]
    next_cursor: Optional[str] = None


class AuditExportV1(BaseModel):
    """Cryptographic audit export for a specific capsule."""
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    tenant_id: str
    capsule_manifest: Dict[str, Any]
    replay_verdict: ReplayVerdictV1
