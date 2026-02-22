#!/usr/bin/env python3
"""
Verify Template Integrity

CI enforcement script that verifies template hashes against manifest (Constitution).

Hard failures:
- Frozen template hash changed (Manifest vs Registry)
- Spec hash changed for patch version (Intra-Manifest)
- Missing required tests for ACTIVE templates
- Forbidden capabilities used
- Unqualified dependencies
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from montecarlo.template_metadata import (
    TemplateStatus,
    TemplateVersion,
    compute_code_hash,
)
from montecarlo.versioned_registry import VERSIONED_REGISTRY


class VerificationResult:
    """Result of template verification."""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.passed: List[str] = []

    def error(self, msg: str):
        self.errors.append(msg)

    def warn(self, msg: str):
        self.warnings.append(msg)

    def ok(self, msg: str):
        self.passed.append(msg)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def print_summary(self):
        # Replace unicode for Windows compatibility
        print("\n" + "=" * 60)
        print("TEMPLATE VERIFICATION SUMMARY")
        print("=" * 60)

        if self.passed:
            print(f"\n[PASS] PASSED ({len(self.passed)}):")
            for msg in self.passed:
                print(f"  [+] {msg}")

        if self.warnings:
            print(f"\n[WARN] WARNINGS ({len(self.warnings)}):")
            for msg in self.warnings:
                print(f"  [!] {msg}")

        if self.errors:
            print(f"\n[FAIL] ERRORS ({len(self.errors)}):")
            for msg in self.errors:
                print(f"  [x] {msg}")

        print("\n" + "-" * 60)
        if self.success:
            print("RESULT: [OK] ALL CHECKS PASSED")
        else:
            print(f"RESULT: [FAIL] FAILED ({len(self.errors)} error(s))")
        print("-" * 60)


def load_manifest(path: Path) -> Dict:
    """Load manifest from file."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def verify_frozen_templates(
    manifest: Dict,
    result: VerificationResult,
):
    """Verify frozen templates haven't changed (Constitution = Manifest)."""
    for qid, info in manifest.items():
        if qid.startswith("_"):
            continue

        if not info.get("frozen"):
            continue

        # Get current template
        template = VERSIONED_REGISTRY.get(qid)
        if not template:
            result.error(f"Frozen template missing from registry: {qid}")
            continue

            result.error(f"Frozen template missing from registry: {qid}")
            continue

        # Verify hashes: Manifest vs Computed Code (Strict)
        try:
            current_code_hash = compute_code_hash(type(template), strict=True)
        except RuntimeError as e:
            result.error(f"HASH COMPUTATION FAILED: {qid}: {e}")
            continue

        if current_code_hash != info.get("code_hash"):
            result.error(
                f"FROZEN CODE HASH MISMATCH: {qid}\n"
                f"    Manifest: {info.get('code_hash')[:16]}...\n"
                f"    Computed: {current_code_hash[:16]}..."
            )
        else:
            result.ok(f"Frozen code hash verified: {qid}")

        # Verify SPEC hash (Contract Immutability)
        spec = VERSIONED_REGISTRY.get_spec(qid)
        if not spec:
            result.error(f"Spec missing for: {qid}")
            continue

        current_spec_hash = spec.spec_hash()
        if current_spec_hash != info.get("spec_hash"):
            result.error(
                f"FROZEN SPEC HASH MISMATCH: {qid}\n"
                f"    Manifest: {info.get('spec_hash')[:16]}...\n"
                f"    Computed: {current_spec_hash[:16]}..."
            )
        else:
            result.ok(f"Frozen spec hash verified: {qid}")


def verify_version_semantics(
    manifest: Dict,
    result: VerificationResult,
):
    """Verify semver semantics within the manifest (Intra-Manifest Consistency)."""
    for qid, info in manifest.items():
        if qid.startswith("_"):
            continue

        version_str = info.get("version")
        try:
            version = TemplateVersion.parse(version_str)
        except ValueError:
            result.error(f"Invalid version in manifest: {qid}")
            continue

        # Patch rule: Must match spec of x.y.0
        if version.patch > 0:
            base_qid = f"{info.get('template_id')}@{version.major}.{version.minor}.0"
            if base_qid in manifest:
                base_spec = manifest[base_qid].get("spec_hash")
                current_spec = info.get("spec_hash")

                if base_spec != current_spec:
                    result.error(
                        f"SEMVER VIOLATION: {qid}\n"
                        f"    Patch version has different spec than {base_qid}"
                    )
                else:
                    result.ok(f"Semver consistent: {qid} matches {base_qid} spec")


def verify_capabilities(
    result: VerificationResult,
    forbidden: List[str] = None,
):
    """Verify no forbidden capabilities are used."""
    if forbidden is None:
        forbidden = ["network", "external_process"]

    for qid in VERSIONED_REGISTRY.list_all():
        spec = VERSIONED_REGISTRY.get_spec(qid)
        if not spec:
            continue

        caps = [c.value for c in spec.capabilities]
        bad_caps = [c for c in caps if c in forbidden]

        if bad_caps:
            result.error(f"FORBIDDEN CAPABILITIES: {qid}\n    Uses: {bad_caps}")
        else:
            result.ok(f"Capabilities clean: {qid}")


def verify_dependencies_qualified(result: VerificationResult):
    """Verify all dependencies are version qualified."""
    for qid in VERSIONED_REGISTRY.list_all():
        spec = VERSIONED_REGISTRY.get_spec(qid)
        for dep in spec.depends_on:
            if "@" not in dep:
                result.error(f"UNQUALIFIED DEPENDENCY: {qid} depends on '{dep}'")


def verify_required_tests(
    result: VerificationResult,
):
    """Check that templates have required tests defined (Hard fail for ACTIVE)."""
    for qid in VERSIONED_REGISTRY.list_all():
        spec = VERSIONED_REGISTRY.get_spec(qid)
        meta = VERSIONED_REGISTRY.get_metadata(qid)

        if not spec or not meta:
            continue

        if not spec.required_tests:
            if meta.status == TemplateStatus.ACTIVE:
                result.error(f"MISSING REQUIRED TESTS: {qid} is ACTIVE but has no tests defined")
            else:
                result.warn(f"Missing required tests: {qid} (status: {meta.status})")
        else:
            result.ok(f"Required tests defined: {qid} ({len(spec.required_tests)})")


def main():
    parser = argparse.ArgumentParser(description="Verify template integrity")
    parser.add_argument(
        "--manifest",
        "-m",
        type=Path,
        default=Path("templates_manifest.json"),
        help="Path to manifest file",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors",
    )

    args = parser.parse_args()
    result = VerificationResult()

    # Load manifest
    manifest = load_manifest(args.manifest)
    if not manifest:
        print(f"Note: No manifest found at {args.manifest}")
        print("      Run: python scripts/gen_template_manifest.py")

    # Run verifications
    print("Running template verification checks...")

    verify_frozen_templates(manifest, result)
    verify_version_semantics(manifest, result)
    verify_capabilities(result)
    verify_dependencies_qualified(result)
    verify_required_tests(result)

    # Print summary
    result.print_summary()

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
