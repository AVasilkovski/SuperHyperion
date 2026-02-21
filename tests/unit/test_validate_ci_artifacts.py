from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_ci_artifacts", "scripts/validate_ci_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.validate_ci_artifacts


validate_ci_artifacts = _load_validator()


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def test_validate_ci_artifacts_passes_for_valid_payloads(tmp_path: Path):
    root = tmp_path / "ci_artifacts"
    schemas = tmp_path / "schemas"

    _write(
        schemas / "trust_gate_summary.v1.schema.json",
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "required": ["contract_version"], "properties": {"contract_version": {"const": "v1"}}},
    )
    _write(
        schemas / "policy_conflicts_summary.v1.schema.json",
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "required": ["contract_version"], "properties": {"contract_version": {"const": "v1"}}},
    )
    _write(
        schemas / "compliance_report.v1.schema.json",
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "required": ["contract_version"], "properties": {"contract_version": {"const": "v1"}}},
    )
    _write(
        schemas / "explainability_summary.v1.schema.json",
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "required": ["contract_version"], "properties": {"contract_version": {"enum": ["v1", "v1.1"]}}},
    )

    _write(root / "trust_gate_summary.json", {"contract_version": "v1"})
    _write(root / "conflicts" / "policy_conflicts_summary.json", {"contract_version": "v1"})
    _write(root / "compliance" / "compliance_report.json", {"contract_version": "v1"})
    _write(root / "tenant-default_run_explainability_summary.json", {"contract_version": "v1.1"})

    assert validate_ci_artifacts(root, schemas) == []


def test_validate_ci_artifacts_reports_schema_errors(tmp_path: Path):
    root = tmp_path / "ci_artifacts"
    schemas = tmp_path / "schemas"

    _write(
        schemas / "trust_gate_summary.v1.schema.json",
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "required": ["contract_version"], "properties": {"contract_version": {"const": "v1"}}},
    )
    _write(
        schemas / "policy_conflicts_summary.v1.schema.json",
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"},
    )
    _write(
        schemas / "compliance_report.v1.schema.json",
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"},
    )

    _write(root / "trust_gate_summary.json", {"contract_version": "invalid"})

    errors = validate_ci_artifacts(root, schemas)
    assert errors
    assert "trust_gate_summary.json" in errors[0]
