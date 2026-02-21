#!/usr/bin/env python3
"""Validate CI artifacts against versioned JSON schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_file(data_path: Path, schema_path: Path) -> list[str]:
    data = _load_json(data_path)
    schema = _load_json(schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    messages: list[str] = []
    for err in errors:
        pointer = "/".join(str(x) for x in err.path) or "<root>"
        messages.append(
            f"{data_path} :: schema={schema_path} :: path={pointer} :: {err.message}"
        )
    return messages


def validate_ci_artifacts(root: Path, schemas: Path) -> list[str]:
    checks = [
        (root / "trust_gate_summary.json", schemas / "trust_gate_summary.v1.schema.json"),
        (root / "conflicts" / "policy_conflicts_summary.json", schemas / "policy_conflicts_summary.v1.schema.json"),
        (root / "compliance" / "compliance_report.json", schemas / "compliance_report.v1.schema.json"),
    ]

    errors: list[str] = []
    for data_path, schema_path in checks:
        if data_path.exists():
            errors.extend(_validate_file(data_path, schema_path))

    explainability_schema = schemas / "explainability_summary.v1.schema.json"
    if explainability_schema.exists():
        for exp_path in sorted(root.rglob("*_explainability_summary.json")):
            errors.extend(_validate_file(exp_path, explainability_schema))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate CI artifacts against JSON schemas")
    parser.add_argument("--root", default="ci_artifacts", help="Artifact root directory")
    parser.add_argument("--schemas", default="schemas", help="Schema directory")
    args = parser.parse_args()

    root = Path(args.root)
    schemas = Path(args.schemas)

    try:
        errors = validate_ci_artifacts(root=root, schemas=schemas)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"artifact schema validation failed: {exc}")
        return 1

    if errors:
        for msg in errors:
            print(msg)
        return 1

    print(f"artifact schema validation passed for root={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
