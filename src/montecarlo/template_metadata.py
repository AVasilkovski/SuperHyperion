"""
Template Metadata & Versioning Module

Constitutional layer for operator governance.
Templates are versioned, hashed, and frozen on first evidence.

INVARIANTS:
- Frozen templates are immutable
- Version bumps follow semver semantics
- Hash includes spec + normalized run() code
"""

import ast
import hashlib
import inspect
import json
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from .templates import Template


# =============================================================================
# Template Version
# =============================================================================

@dataclass(frozen=True, order=True)
class TemplateVersion:
    """
    Semantic version for templates.
    
    - major: Breaking change to contract
    - minor: New optional capabilities
    - patch: Bug fix (same semantics)
    """
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, s: str) -> "TemplateVersion":
        """Parse version string like '1.2.3'."""
        parts = s.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid version format: {s} (expected X.Y.Z)")
        try:
            return cls(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError as e:
            raise ValueError(f"Invalid version: {s}: {e}")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def is_compatible_upgrade(self, other: "TemplateVersion") -> bool:
        """Check if other is a compatible upgrade (same major, higher minor/patch)."""
        if self.major != other.major:
            return False
        if other.minor > self.minor:
            return True
        if other.minor == self.minor and other.patch > self.patch:
            return True
        return False


# =============================================================================
# Epistemic Semantics (Phase 16.2)
# =============================================================================

@dataclass
class EpistemicSemantics:
    """
    Governed epistemic semantics for a template.
    Included in spec_hash.
    """
    instrument: str = "confirmatory"  # confirmatory, falsification, replication, method_audit, consistency_check
    negative_role_on_fail: str = "none"  # refute, undercut, replicate, none
    default_failure_mode: str = "null_effect"  # null_effect, sign_flip, violated_assumption, nonidentifiable
    strength_model: str = "binary_default"  # binary_default, ci_proximity_to_null

    def to_canonical_dict(self) -> Dict[str, str]:
        return {
            "instrument": self.instrument,
            "negative_role_on_fail": self.negative_role_on_fail,
            "default_failure_mode": self.default_failure_mode,
            "strength_model": self.strength_model,
        }



# =============================================================================
# Template Capabilities (Security Surface)
# =============================================================================

class TemplateCapability(str, Enum):
    """Declared capabilities of a template."""
    FILESYSTEM = "filesystem"
    NETWORK = "network"
    RANDOMNESS = "randomness"
    EXTERNAL_PROCESS = "external_process"
    DATABASE = "database"


# =============================================================================
# Template Status (Lifecycle)
# =============================================================================

class TemplateStatus(str, Enum):
    """Template lifecycle status."""
    ACTIVE = "active"           # Can be used for new experiments
    DEPRECATED = "deprecated"   # Cannot be used for new, but queries work
    BANNED = "banned"           # Cannot be executed at all


# =============================================================================
# Template Spec (Declared Contract)
# =============================================================================

@dataclass
class TemplateSpec:
    """
    Declared contract for a template.
    
    This is what gets hashed for spec_hash.
    Changes to this require version bumps.
    """
    template_id: str
    version: TemplateVersion
    description: str

    # Input/output contract
    param_schema: Dict[str, Any]  # JSON schema of ParamModel
    output_schema: Dict[str, Any]  # JSON schema of OutputModel

    # Invariants (must always be true)
    invariants: List[str] = field(default_factory=list)

    # Dependencies on other templates
    depends_on: List[str] = field(default_factory=list)  # e.g. ["bootstrap_ci@1.0.0"]

    # Declared capabilities
    capabilities: Set[TemplateCapability] = field(default_factory=set)

    # Required contract tests (by stable ID)
    required_tests: List[str] = field(default_factory=list)

    # Determinism
    deterministic: bool = True

    # Phase 16.2: Governed epistemic semantics
    epistemic: EpistemicSemantics = field(default_factory=EpistemicSemantics)


    def to_canonical_json(self) -> str:
        """Return canonical JSON for hashing (sorted keys, no whitespace)."""
        data = {
            "template_id": self.template_id,
            "version": str(self.version),
            "description": self.description,
            "param_schema": self.param_schema,
            "output_schema": self.output_schema,
            "invariants": sorted(self.invariants),
            "depends_on": sorted(self.depends_on),
            "capabilities": sorted(c.value for c in self.capabilities),
            "required_tests": sorted(self.required_tests),
            "deterministic": self.deterministic,
            "epistemic": self.epistemic.to_canonical_dict(),
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def spec_hash(self) -> str:
        """Return SHA256 hash of canonical spec JSON."""
        return hashlib.sha256(self.to_canonical_json().encode()).hexdigest()


# =============================================================================
# Code Hash Utilities
# =============================================================================


def sha256_json_strict(data: Any) -> str:
    """
    Strict hash of JSON-serializable data.
    Raises exception on failure instead of fallback.
    """
    s = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def normalize_ast(source: str) -> str:
    """
    Normalize Python source to AST dump (ignoring line numbers/formatting).
    
    This allows hashing code semantics, not whitespace.
    """
    try:
        tree = ast.parse(source)
        # include_attributes=False ignores line numbers and column offsets
        return ast.dump(tree, include_attributes=False)
    except SyntaxError:
        # Fallback to raw source if AST parsing fails
        return source


def compute_code_hash(cls: type, strict: bool = False) -> str:
    """
    Compute hash of the entire template class implementation.
    
    Uses AST normalization on the class source code.
    If strict=True, raises exception on failure instead of returning placeholder.
    """
    try:
        source = inspect.getsource(cls)
        normalized = normalize_ast(source)
        return hashlib.sha256(normalized.encode()).hexdigest()
    except (OSError, TypeError) as e:
        if strict:
            raise RuntimeError(f"Failed to compute code hash for {cls}: {e}")
        # If we can't inspect source (e.g. REPL), return placeholder
        # In PROD this should probably fail, but for now we maintain robustness
        return f"hash-error-{str(e)}"

def compute_code_hash_strict(cls: type) -> str:
    """
    Compute code hash of template class, failing hard on error.
    
    Constitutional Seal Usage: This MUST be used during freeze/validation.
    """
    return compute_code_hash(cls, strict=True)


# =============================================================================
# Template Metadata (Governance Record)
# =============================================================================

@dataclass(frozen=True)
class TemplateMetadata:
    """
    Governance metadata for a template version.
    
    Persisted in TypeDB + manifest.json.
    Immutable: updates require creating new instance.
    """
    template_id: str
    version: TemplateVersion

    # Hashes (for integrity verification)
    spec_hash: str
    code_hash: str
    deps_hash: Optional[str] = None

    # Governance
    status: TemplateStatus = TemplateStatus.ACTIVE
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None

    # Freeze state
    frozen: bool = False
    frozen_at: Optional[datetime] = None
    first_evidence_id: Optional[str] = None

    # Freeze provenance
    freeze_claim_id: Optional[str] = None
    freeze_scope_lock_id: Optional[str] = None

    # Taint state
    tainted: bool = False
    tainted_at: Optional[datetime] = None
    tainted_reason: Optional[str] = None
    superseded_by: Optional[str] = None  # e.g. "bootstrap_ci@1.0.1"

    @property
    def qualified_id(self) -> str:
        """Return qualified ID like 'bootstrap_ci@1.0.0'."""
        return f"{self.template_id}@{self.version}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "template_id": self.template_id,
            "version": str(self.version),
            "spec_hash": self.spec_hash,
            "code_hash": self.code_hash,
            "deps_hash": self.deps_hash,
            "status": self.status.value,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "frozen": self.frozen,
            "frozen_at": self.frozen_at.isoformat() if self.frozen_at else None,
            "first_evidence_id": self.first_evidence_id,
            "freeze_claim_id": self.freeze_claim_id,
            "freeze_scope_lock_id": self.freeze_scope_lock_id,
            "tainted": self.tainted,
            "tainted_at": self.tainted_at.isoformat() if self.tainted_at else None,
            "tainted_reason": self.tainted_reason,
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemplateMetadata":
        """Create from dictionary."""
        return cls(
            template_id=data["template_id"],
            version=TemplateVersion.parse(data["version"]),
            spec_hash=data["spec_hash"],
            code_hash=data["code_hash"],
            deps_hash=data.get("deps_hash"),
            status=TemplateStatus(data.get("status", "active")),
            approved_by=data.get("approved_by"),
            approved_at=datetime.fromisoformat(data["approved_at"]) if data.get("approved_at") else None,
            frozen=data.get("frozen", False),
            frozen_at=datetime.fromisoformat(data["frozen_at"]) if data.get("frozen_at") else None,
            first_evidence_id=data.get("first_evidence_id"),
            freeze_claim_id=data.get("freeze_claim_id"),
            freeze_scope_lock_id=data.get("freeze_scope_lock_id"),
            tainted=data.get("tainted", False),
            tainted_at=datetime.fromisoformat(data["tainted_at"]) if data.get("tainted_at") else None,
            tainted_reason=data.get("tainted_reason"),
            superseded_by=data.get("superseded_by"),
        )


# =============================================================================
# Versioned Template Registry
# =============================================================================

# =============================================================================
# Versioned Template Registry
# =============================================================================

logger = logging.getLogger(__name__)

class VersionedTemplateRegistry:
    """
    Explicit registry of versioned templates.
    
    Keys are qualified IDs: 'template_id@version'
    """

    def __init__(self):
        self._templates: Dict[str, "Template"] = {}
        self._metadata: Dict[str, TemplateMetadata] = {}
        self._specs: Dict[str, TemplateSpec] = {}

    def register(
        self,
        template: "Template",
        spec: TemplateSpec,
        metadata: Optional[TemplateMetadata] = None,
    ) -> str:
        """
        Register a versioned template.
        
        Returns the qualified ID.
        """
        qualified_id = f"{spec.template_id}@{spec.version}"

        if qualified_id in self._templates:
            raise ValueError(f"Template already registered: {qualified_id}")

        # Compute hashes (strict validation for registration)
        spec_hash = spec.spec_hash()
        code_hash = compute_code_hash(type(template), strict=True)

        # Create metadata if not provided
        if metadata is None:
            metadata = TemplateMetadata(
                template_id=spec.template_id,
                version=spec.version,
                spec_hash=spec_hash,
                code_hash=code_hash,
            )
        else:
            # Validate provided metadata against computed hashes
            if metadata.spec_hash != spec_hash:
                raise ValueError(
                    f"Metadata sanity check failed for {qualified_id}: "
                    f"spec_hash mismatch (provided={metadata.spec_hash}, computed={spec_hash})"
                )
            if metadata.code_hash != code_hash:
                raise ValueError(
                    f"Metadata sanity check failed for {qualified_id}: "
                    f"code_hash mismatch (provided={metadata.code_hash}, computed={code_hash})"
                )

        self._templates[qualified_id] = template
        self._specs[qualified_id] = spec
        self._metadata[qualified_id] = metadata

        return qualified_id

    def get(self, qualified_id: str) -> Optional["Template"]:
        """Get a template by qualified ID."""
        return self._templates.get(qualified_id)

    def get_spec(self, qualified_id: str) -> Optional[TemplateSpec]:
        """Get spec by qualified ID."""
        return self._specs.get(qualified_id)

    def get_metadata(self, qualified_id: str) -> Optional[TemplateMetadata]:
        """Get metadata by qualified ID."""
        return self._metadata.get(qualified_id)

    def get_latest(self, template_id: str) -> Optional["Template"]:
        """Get the latest version of a template."""
        versions = [
            (TemplateVersion.parse(qid.split("@")[1]), qid)
            for qid in self._templates
            if qid.startswith(f"{template_id}@") and
               self._metadata[qid].status == TemplateStatus.ACTIVE
        ]
        if not versions:
            return None
        versions.sort(reverse=True)
        return self._templates[versions[0][1]]

    def list_all(self) -> List[str]:
        """List all registered qualified IDs."""
        return sorted(self._templates.keys())

    def list_by_status(self, status: TemplateStatus) -> List[str]:
        """List templates by status."""
        return [
            qid for qid, meta in self._metadata.items()
            if meta.status == status
        ]

    def freeze(
        self,
        qualified_id: str,
        evidence_id: str,
        claim_id: Optional[str] = None,
        scope_lock_id: Optional[str] = None,
    ) -> TemplateMetadata:
        """
        Freeze a template on first evidence.
        
        Returns updated metadata (new instance).
        """
        metadata = self._metadata.get(qualified_id)
        if not metadata:
            raise ValueError(f"Template not found: {qualified_id}")

        if metadata.frozen:
            # Idempotent freeze: return existing if frozen
            # Log warning if provenance drifts (e.g. different evidence ID)
            if metadata.first_evidence_id and evidence_id and metadata.first_evidence_id != evidence_id:
                logger.warning(
                    "Registry freeze called for already-frozen template with different evidence_id. "
                    "Keeping original first_evidence_id. qualified_id=%s frozen_first=%s new=%s",
                    qualified_id, metadata.first_evidence_id, evidence_id
                )
            return metadata

        new_meta = replace(
            metadata,
            frozen=True,
            frozen_at=datetime.now(),
            first_evidence_id=evidence_id,
            freeze_claim_id=claim_id,
            freeze_scope_lock_id=scope_lock_id,
        )
        self._metadata[qualified_id] = new_meta
        return new_meta

    def taint(
        self,
        qualified_id: str,
        reason: str,
        superseded_by: Optional[str] = None,
    ) -> TemplateMetadata:
        """
        Mark a template version as tainted.
        """
        metadata = self._metadata.get(qualified_id)
        if not metadata:
            raise ValueError(f"Template not found: {qualified_id}")

        new_meta = replace(
            metadata,
            tainted=True,
            tainted_at=datetime.now(),
            tainted_reason=reason,
            superseded_by=superseded_by,
        )
        self._metadata[qualified_id] = new_meta
        return new_meta

    def deprecate(self, qualified_id: str) -> TemplateMetadata:
        """Mark a template as deprecated."""
        metadata = self._metadata.get(qualified_id)
        if not metadata:
            raise ValueError(f"Template not found: {qualified_id}")

        new_meta = replace(metadata, status=TemplateStatus.DEPRECATED)
        self._metadata[qualified_id] = new_meta
        return new_meta

    def verify_hashes(self, qualified_id: str) -> bool:
        """Verify that current hashes match stored metadata."""
        template = self._templates.get(qualified_id)
        spec = self._specs.get(qualified_id)
        metadata = self._metadata.get(qualified_id)

        if not all([template, spec, metadata]):
            return False

        current_spec_hash = spec.spec_hash()
        current_code_hash = compute_code_hash(type(template), strict=True)

        return (
            current_spec_hash == metadata.spec_hash and
            current_code_hash == metadata.code_hash
        )

    def to_manifest(self) -> Dict[str, Any]:
        """Export registry to manifest format for CI."""
        manifest = {}
        for qid in self._templates:
            metadata = self._metadata[qid]
            spec = self._specs[qid]
            manifest[qid] = {
                "template_id": metadata.template_id,
                "version": str(metadata.version),
                "spec_hash": metadata.spec_hash,
                "code_hash": metadata.code_hash,
                "deps_hash": metadata.deps_hash,
                "depends_on": sorted(spec.depends_on),
                "capabilities": sorted(c.value for c in spec.capabilities),
                "frozen": metadata.frozen,
                "status": metadata.status.value,
            }
        return manifest
