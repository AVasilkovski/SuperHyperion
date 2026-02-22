#!/usr/bin/env python3
"""
Generate Template Manifest

Generates templates_manifest.json from the versioned registry.
This manifest is used by CI for integrity verification.

Usage:
    python scripts/gen_template_manifest.py
    python scripts/gen_template_manifest.py --output manifest.json
"""

import argparse
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from montecarlo.versioned_registry import VERSIONED_REGISTRY


def generate_manifest(output_path: Path = None) -> dict:
    """
    Generate the template manifest.

    Returns dict with structure:
    {
        "bootstrap_ci@1.0.0": {
            "template_id": "bootstrap_ci",
            "version": "1.0.0",
            "spec_hash": "...",
            "code_hash": "...",
            "depends_on": [],
            "capabilities": ["randomness"],
            "frozen": false,
            "status": "active"
        },
        ...
    }
    """
    manifest = VERSIONED_REGISTRY.to_manifest()

    # Add generation metadata
    from datetime import datetime

    manifest["_meta"] = {
        "generated_at": datetime.now().isoformat(),
        "generator": "gen_template_manifest.py",
        "version": "1.0.0",
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
        print(f"[OK] Manifest written to {output_path}")

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Generate template manifest")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("templates_manifest.json"),
        help="Output path (default: templates_manifest.json)",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print manifest to stdout",
    )

    args = parser.parse_args()

    manifest = generate_manifest(args.output)

    if args.print:
        print(json.dumps(manifest, indent=2, sort_keys=True))

    # Summary
    template_count = len([k for k in manifest if not k.startswith("_")])
    print(f"\nSummary: {template_count} templates registered")

    for qid in sorted(manifest.keys()):
        if qid.startswith("_"):
            continue
        info = manifest[qid]
        status = "[FROZEN]" if info.get("frozen") else "[ACTIVE]"
        caps = ", ".join(info.get("capabilities", [])) or "none"
        print(f"  {status} {qid}: caps=[{caps}]")


if __name__ == "__main__":
    main()
